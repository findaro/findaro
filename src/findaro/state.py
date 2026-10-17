"""Process-wide resources (DB engine, OpenSearch, Redis, embedder)."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import redis.asyncio as aioredis
from opensearchpy import AsyncOpenSearch
from sqlalchemy.ext.asyncio import AsyncEngine

from findaro.config import Settings, get_settings
from findaro.db import init_db, make_engine
from findaro.embeddings import Embedder, get_embedder


@dataclass
class State:
    settings: Settings
    db: AsyncEngine
    os: AsyncOpenSearch
    redis: aioredis.Redis
    embedder: Embedder
    planner: Any = None  # findaro.llm.LLM used by the query planner; None disables the LLM path
    chat_llm: Any = None  # findaro.llm.LLM for chat turns (classification fallback + answers); None = templates

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
    return State(settings=settings, db=db, os=os_client, redis=r, embedder=embedder or get_embedder(),
                 planner=make_planner(settings), chat_llm=make_chat_llm(settings))


def make_planner(settings: Settings) -> Any:
    if not settings.understand_llm:
        return None
    from findaro.llm import LLMError, get_llm

    if (settings.planner_provider or settings.llm_provider) == "none":
        return None
    try:
        provider = settings.planner_provider or settings.llm_provider
        model = settings.planner_model or {"anthropic": "claude-haiku-4-5", "ollama": "llama3.2:3b"}.get(provider)
        return get_llm(provider, model)
    except LLMError as e:
        logging.getLogger("findaro").warning("query planner LLM disabled: %s", e)
        return None


def make_chat_llm(settings: Settings) -> Any:
    from findaro.llm import LLMError, get_llm

    # Paid providers only when chosen explicitly (FINDARO_CHAT_PROVIDER=openai|anthropic); a key in .env alone never
    # turns them on. "none" disables the chat LLM (template answers).
    provider = settings.chat_provider or settings.llm_provider
    if provider == "none":
        return None
    model = settings.chat_model or {"openai": "gpt-4.1-mini", "anthropic": "claude-haiku-4-5"}.get(provider)
    try:
        return get_llm(provider, model, reasoning_effort=settings.chat_reasoning_effort)
    except (LLMError, TypeError) as e:
        logging.getLogger("findaro").warning("chat LLM disabled: %s", e)
        return None
