"""Process-wide resources (DB engine, OpenSearch, Redis, embedder)."""

from __future__ import annotations

from dataclasses import dataclass

import redis.asyncio as aioredis
from opensearchpy import AsyncOpenSearch
from sqlalchemy.ext.asyncio import AsyncEngine

from zerch.config import Settings, get_settings
from zerch.db import init_db, make_engine
from zerch.embeddings import Embedder, get_embedder


@dataclass
class State:
    settings: Settings
    db: AsyncEngine
    os: AsyncOpenSearch
    redis: aioredis.Redis
    embedder: Embedder

    async def close(self) -> None:
        await self.os.close()
        await self.redis.aclose()
        await self.db.dispose()


async def create_state(settings: Settings | None = None, embedder: Embedder | None = None) -> State:
    settings = settings or get_settings()
    db = make_engine(settings.database_url)
    await init_db(db)
    os_client = AsyncOpenSearch(hosts=[settings.opensearch_url], timeout=30, http_compress=False, maxsize=25)
    r = aioredis.from_url(settings.redis_url, decode_responses=False)
    return State(settings=settings, db=db, os=os_client, redis=r, embedder=embedder or get_embedder())
