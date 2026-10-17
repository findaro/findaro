"""Integration fixtures. Needs `docker compose up -d postgres opensearch redis`.

Tests use their own database (findaro_test), Redis DB 15 and index prefix, and the deterministic hash
embedder, so they never interfere with a running dev stack.
"""

from __future__ import annotations

import os
import random
from collections.abc import AsyncIterator
from typing import Any

import asyncpg
import httpx
import pytest
from sqlalchemy.engine import make_url

from findaro.config import Settings
from findaro.embeddings.hashing import HashEmbedder
from findaro.ingest.processor import run_pending
from findaro.main import create_app
from findaro.state import State, create_state

TEST_DB = os.environ.get("FINDARO_TEST_DATABASE_URL", "postgresql+asyncpg://findaro:findaro@localhost:54329/findaro_test")


def make_settings(**over: Any) -> Settings:
    base = dict(
        database_url=TEST_DB,
        opensearch_url=os.environ.get("FINDARO_TEST_OPENSEARCH_URL", "http://localhost:19200"),
        redis_url=os.environ.get("FINDARO_TEST_REDIS_URL", "redis://localhost:63799/15"),
        index_prefix="findarotest",
        embedder="hash",
        search_cache_ttl=0,
        rate_limit_per_second=0,
        bulk_batch_size=50,
        match_floor=0.0,  # the hash embedder's scores aren't on e5's scale
        chat_provider="none",  # tests never call a real LLM (fakes are injected where needed)
        planner_provider="none",
        openai_api_key=None,
        anthropic_api_key=None,
        understand_llm=True,
    )
    base.update(over)
    return Settings(_env_file=None, **base)


async def _ensure_database(url: str) -> None:
    u = make_url(url)
    conn = await asyncpg.connect(user=u.username, password=u.password, host=u.host, port=u.port, database="postgres")
    try:
        exists = await conn.fetchval("SELECT 1 FROM pg_database WHERE datname = $1", u.database)
        if not exists:
            await conn.execute(f'CREATE DATABASE "{u.database}"')
    finally:
        await conn.close()


@pytest.fixture(scope="session")
async def state() -> AsyncIterator[State]:
    await _ensure_database(TEST_DB)
    st = await create_state(make_settings(), HashEmbedder())
    await st.os.indices.delete(index="findarotest-*", ignore_unavailable=True, params={"expand_wildcards": "all"})
    async with st.db.begin() as conn:
        await conn.exec_driver_sql("TRUNCATE projects, api_keys, jobs, job_payloads CASCADE")
    await st.redis.flushdb()
    yield st
    await st.close()


@pytest.fixture(scope="session")
async def client(state: State) -> AsyncIterator[httpx.AsyncClient]:
    app = create_app(state.settings, state.embedder)
    app.state.findaro = state  # lifespan is not run by ASGITransport
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        yield c


class Project:
    def __init__(self, client: httpx.AsyncClient, state: State, data: dict[str, Any]):
        self.client, self.state = client, state
        self.id: str = data["project_id"]
        self.admin_key: str = data["admin_key"]
        self.search_key: str = data["search_key"]

    @property
    def admin(self) -> dict[str, str]:
        return {"authorization": f"Bearer {self.admin_key}"}

    @property
    def searcher(self) -> dict[str, str]:
        return {"authorization": f"Bearer {self.search_key}"}

    async def ingest(self, docs: list[dict[str, Any]]) -> dict[str, Any]:
        r = await self.client.post(f"/v1/projects/{self.id}/documents", json=docs, headers=self.admin)
        assert r.status_code == 202, r.text
        return await self.finish(r.json()["job_id"])

    async def finish(self, job_id: str) -> dict[str, Any]:
        await run_pending(self.state)
        r = await self.client.get(f"/v1/projects/{self.id}/jobs/{job_id}", headers=self.admin)
        assert r.status_code == 200, r.text
        return r.json()

    async def search(self, **body: Any) -> dict[str, Any]:
        r = await self.client.post("/v1/search", json=body, headers=self.searcher)
        assert r.status_code == 200, r.text
        return r.json()


async def new_project(client: httpx.AsyncClient, state: State, name: str = "t") -> Project:
    r = await client.post("/v1/projects", json={"name": name})
    assert r.status_code == 201, r.text
    return Project(client, state, r.json())


@pytest.fixture
async def project(client: httpx.AsyncClient, state: State) -> Project:
    return await new_project(client, state)


# --- a small generic catalog ------------------------------------------------------------------------

KINDS = [
    ("Running Shoes", "Footwear > Men > Running Shoes", ["Mesh", "Knit"]),
    ("Kolhapuri Chappal", "Footwear > Women > Chappals", ["Leather"]),
    ("Cotton Kurta", "Apparel > Men > Kurtas", ["Cotton", "Linen"]),
    ("Pressure Cooker", "Home > Cookware > Pressure Cookers", ["Aluminium", "Steel"]),
    ("Water Bottle", "Home > Storage > Bottles", ["Steel", "Copper", "Plastic"]),
    ("Phone Cover", "Electronics > Mobile > Covers", ["Silicone", "Leather"]),
]
COLORS = ["Black", "White", "Blue", "Red", "Green"]
BRANDS = ["Zorvik", "Tarangi", "Mehrava", "Kosmo", "Lumbini"]


def make_catalog(n: int = 60, seed: int = 7) -> list[dict[str, Any]]:
    rng = random.Random(seed)
    docs = []
    for i in range(n):
        kind, cat, mats = KINDS[i % len(KINDS)]
        color, brand, mat = rng.choice(COLORS), rng.choice(BRANDS), rng.choice(mats)
        price = rng.choice([199, 299, 499, 799, 999, 1499, 2499])
        docs.append({
            "id": f"P{i:03d}",
            "title": f"{brand} {color} {mat} {kind}",
            "description": f"A {color.lower()} {kind.lower()} made of {mat.lower()} by {brand}. Great for daily use.",
            "brand": brand,
            "category": cat,
            "color": color,
            "material": mat,
            "price": price,
            "currency": "INR",
            "tags": rng.sample(["new", "sale", "bestseller", "eco"], 2),
            "in_stock": i % 5 != 0,
            "rating": round(3 + (i % 20) / 10, 1),
            "image_url": f"https://img.example.com/{i}.jpg",
            "url": f"https://shop.example.com/p/{i}",
        })
    return docs


@pytest.fixture(scope="session")
def catalog() -> list[dict[str, Any]]:
    return make_catalog()


@pytest.fixture(scope="session")
async def loaded(client: httpx.AsyncClient, state: State, catalog: list[dict[str, Any]]) -> Project:
    """A project with the generic catalog ingested (shared, read-only)."""
    p = await new_project(client, state, "loaded")
    job = await p.ingest(catalog)
    assert job["status"] == "succeeded", job
    return p
