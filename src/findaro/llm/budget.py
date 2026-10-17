"""A daily cap on LLM calls for one deployment, so a public demo can't run up an unbounded bill.

Every model call (planner, chat classification, answers) increments one Redis counter per UTC day. Past
`llm_daily_call_limit` the call raises LLMError, which every caller already handles by falling back to the rules
plan or a template answer.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

from findaro.llm.base import LLMError

log = logging.getLogger("findaro.llm")


class BudgetedLLM:
    def __init__(self, inner: Any, redis: Any, daily_limit: int):
        self._inner, self._redis, self._limit = inner, redis, daily_limit
        self.name = getattr(inner, "name", "llm")
        if hasattr(inner, "stream"):
            self.stream = self._stream

    async def _spend(self) -> None:
        key = f"llm:calls:{datetime.now(UTC):%Y%m%d}"
        pipe = self._redis.pipeline()
        pipe.incr(key)
        pipe.expire(key, 2 * 86_400)
        n, _ = await pipe.execute()
        if n > self._limit:
            if n == self._limit + 1:
                log.warning("daily LLM call limit (%d) reached; using rules and templates until tomorrow (UTC)",
                            self._limit)
            raise LLMError("daily LLM call limit reached")

    async def complete(self, prompt: str, **kw: Any) -> str:
        await self._spend()
        return await self._inner.complete(prompt, **kw)

    async def _stream(self, prompt: str, **kw: Any) -> AsyncIterator[str]:
        await self._spend()
        async for chunk in self._inner.stream(prompt, **kw):
            yield chunk

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)
