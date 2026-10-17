"""findaro website server: static pages from SITE_PUBLIC_DIR plus POST /api/request-access.

Runs from the findaro image without loading the search engine:

    uvicorn app:app --app-dir site/server

Env: SITE_DATABASE_URL (postgresql://...), SITE_REDIS_URL (rate limits), SITE_PUBLIC_DIR, optional
SITE_NOTIFY_WEBHOOK (Slack/Discord-compatible incoming webhook; gets name, company and plan, never the message).
Leads are stored in the `site_leads` table; list them with `python site/server/leads.py`.
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
from contextlib import asynccontextmanager
from pathlib import Path

import asyncpg
import httpx
import redis.asyncio as aioredis
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, ValidationError

log = logging.getLogger("findaro.site")

PUBLIC = Path(os.environ.get("SITE_PUBLIC_DIR", Path(__file__).resolve().parent.parent / "public"))
PER_IP_PER_HOUR = 5
PER_DAY = 200
EMAIL = re.compile(r"^[^@\s]{1,64}@[^@\s]+\.[A-Za-z]{2,}$")

SCHEMA = """
CREATE TABLE IF NOT EXISTS site_leads (
    id BIGSERIAL PRIMARY KEY,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    name TEXT NOT NULL,
    email TEXT NOT NULL,
    company TEXT NOT NULL,
    website TEXT,
    catalog_size TEXT,
    plan TEXT,
    message TEXT,
    ip_hash TEXT,
    status TEXT NOT NULL DEFAULT 'new'
)"""


class Lead(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    email: str = Field(min_length=3, max_length=200)
    company: str = Field(min_length=1, max_length=200)
    website: str | None = Field(None, max_length=300)
    catalog_size: str | None = Field(None, max_length=40)
    plan: str | None = Field(None, max_length=40)
    message: str | None = Field(None, max_length=4000)
    company_url_hp: str | None = Field(None, max_length=300)  # honeypot: people never fill it


@asynccontextmanager
async def lifespan(app: FastAPI):
    logging.basicConfig(level=logging.INFO)
    app.state.pg = await asyncpg.create_pool(os.environ["SITE_DATABASE_URL"], min_size=1, max_size=3)
    async with app.state.pg.acquire() as conn:
        await conn.execute(SCHEMA)
    app.state.redis = aioredis.from_url(os.environ.get("SITE_REDIS_URL", "redis://localhost:6379/1"))
    yield
    await app.state.pg.close()
    await app.state.redis.aclose()


app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)


def _client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for", "")
    return fwd.split(",")[0].strip() or (request.client.host if request.client else "")


async def _over_limit(r: aioredis.Redis, ip_hash: str) -> bool:
    pipe = r.pipeline()
    pipe.incr(f"site:lead:ip:{ip_hash}")
    pipe.expire(f"site:lead:ip:{ip_hash}", 3600, nx=True)
    pipe.incr("site:lead:day")
    pipe.expire("site:lead:day", 86400, nx=True)
    per_ip, _, per_day, _ = await pipe.execute()
    return per_ip > PER_IP_PER_HOUR or per_day > PER_DAY


async def _notify(lead: Lead) -> None:
    url = os.environ.get("SITE_NOTIFY_WEBHOOK")
    if not url:
        return
    text = f"New findaro access request: {lead.name} ({lead.company}), plan {lead.plan or '-'}, " \
           f"catalog {lead.catalog_size or '-'}"
    try:
        async with httpx.AsyncClient(timeout=5) as c:
            await c.post(url, json={"text": text, "content": text})
    except httpx.HTTPError as e:
        log.warning("lead notification failed: %s", e)


@app.post("/api/request-access")
async def request_access(request: Request) -> JSONResponse:
    try:
        lead = Lead.model_validate_json(await request.body())
    except ValidationError:
        return JSONResponse({"error": "invalid"}, status_code=400)
    if lead.company_url_hp:  # bot: pretend it worked
        return JSONResponse({"ok": True})
    if not EMAIL.match(lead.email.strip()):
        return JSONResponse({"error": "invalid_email"}, status_code=400)
    ip_hash = hashlib.sha256(_client_ip(request).encode()).hexdigest()[:16]
    if await _over_limit(request.app.state.redis, ip_hash):
        return JSONResponse({"error": "rate_limited"}, status_code=429)
    async with request.app.state.pg.acquire() as conn:
        await conn.execute(
            "INSERT INTO site_leads (name, email, company, website, catalog_size, plan, message, ip_hash)"
            " VALUES ($1, $2, $3, $4, $5, $6, $7, $8)",
            lead.name.strip(), lead.email.strip().lower(), lead.company.strip(), lead.website, lead.catalog_size,
            lead.plan, lead.message, ip_hash)
    await _notify(lead)
    return JSONResponse({"ok": True})


@app.get("/healthz", include_in_schema=False)
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.api_route("/api/{rest:path}", methods=["GET", "POST", "PUT", "DELETE"], include_in_schema=False)
async def api_not_found(rest: str) -> JSONResponse:
    return JSONResponse({"error": "not_found"}, status_code=404)


# html=True serves index.html for directories and 404.html for missing pages
app.mount("/", StaticFiles(directory=PUBLIC, html=True, check_dir=False), name="public")
