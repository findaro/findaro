"""findaro website server: static pages from SITE_PUBLIC_DIR plus POST /api/request-access.

Runs from the findaro image without loading the search engine:

    uvicorn app:app --app-dir site/server

Env: SITE_DATABASE_URL (postgresql://...), SITE_REDIS_URL (rate limits), SITE_PUBLIC_DIR, optional
SITE_NOTIFY_WEBHOOK (incoming webhook that gets every field of the lead: a rich embed for Discord URLs, plain
text for Slack-compatible ones). Use a private channel: the payload has the lead's email and message.
Leads are stored in the `site_leads` table; list them with `python site/server/leads.py`.
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
from contextlib import asynccontextmanager
from datetime import UTC, datetime
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
MD_SPECIAL = re.compile(r"([\\*_~`|>\[\]<#])")

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


def _md(value: str | None, limit: int = 1024) -> str:
    """User text as literal Discord/Slack markdown: escaped, trimmed to the field limit, never empty."""
    value = (value or "").strip()
    if not value:
        return "-"
    value = MD_SPECIAL.sub(r"\\\1", value)
    return value if len(value) <= limit else value[: limit - 1] + "…"


def _lead_fields(lead: Lead) -> list[tuple[str, str]]:
    return [("Name", lead.name), ("Email", lead.email.strip().lower()), ("Company", lead.company),
            ("Website", lead.website), ("Plan", lead.plan), ("Catalog size", lead.catalog_size)]


def _discord_payload(lead: Lead, lead_id: int) -> dict:
    return {
        "allowed_mentions": {"parse": []},  # form text must never ping @everyone or a role
        "embeds": [{
            "title": "New access request",
            "color": 0xEF8354,
            "description": _md(lead.message, 4000) if (lead.message or "").strip() else "*No message*",
            "fields": [{"name": k, "value": _md(v), "inline": True} for k, v in _lead_fields(lead)],
            "footer": {"text": f"site_leads #{lead_id}"},
            "timestamp": datetime.now(UTC).isoformat(),
        }],
    }


def _text_payload(lead: Lead, lead_id: int) -> dict:
    lines = [f"*New findaro access request* (site_leads #{lead_id})"]
    lines += [f"{k}: {_md(v)}" for k, v in _lead_fields(lead)]
    lines.append(f"Message: {_md(lead.message, 3000)}")
    return {"text": "\n".join(lines)}


async def _notify(lead: Lead, lead_id: int) -> None:
    url = os.environ.get("SITE_NOTIFY_WEBHOOK")
    if not url:
        return
    discord = "discord.com/api/webhooks/" in url or "discordapp.com/api/webhooks/" in url
    payload = _discord_payload(lead, lead_id) if discord else _text_payload(lead, lead_id)
    try:
        async with httpx.AsyncClient(timeout=5) as c:
            r = await c.post(url, json=payload)
            r.raise_for_status()
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
        lead_id = await conn.fetchval(
            "INSERT INTO site_leads (name, email, company, website, catalog_size, plan, message, ip_hash)"
            " VALUES ($1, $2, $3, $4, $5, $6, $7, $8) RETURNING id",
            lead.name.strip(), lead.email.strip().lower(), lead.company.strip(), lead.website, lead.catalog_size,
            lead.plan, lead.message, ip_hash)
    await _notify(lead, lead_id)
    return JSONResponse({"ok": True})


@app.get("/healthz", include_in_schema=False)
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.api_route("/api/{rest:path}", methods=["GET", "POST", "PUT", "DELETE"], include_in_schema=False)
async def api_not_found(rest: str) -> JSONResponse:
    return JSONResponse({"error": "not_found"}, status_code=404)


# html=True serves index.html for directories and 404.html for missing pages
app.mount("/", StaticFiles(directory=PUBLIC, html=True, check_dir=False), name="public")
