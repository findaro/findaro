"""Per-project usage metering and operator-set limits.

Search and chat requests increment a Redis counter on the hot path (one INCR); the worker moves those counts
into the Postgres `usage` table every `usage_flush_interval` seconds. Totals = flushed rows + pending counters.

Limits live in `projects.limits` and are set by the operator (bootstrap token), never by the project's keys:

    searches_per_month  quota for search + chat (search-as-you-type requests, `llm: false`, are metered as
                        `typeahead` and don't count)
    documents           max documents in the index; new writes are refused once it's reached
    llm                 false: rules-only query understanding and template chat answers for this project
    block_at_percent    refuse search/chat past this % of the quota (unset: never block, only report)
    plan                free-form label for the operator

An empty dict means unlimited (the self-hosted default).
"""

from __future__ import annotations

import logging
import time
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from findaro.db import usage
from findaro.errors import ApiError

log = logging.getLogger("findaro.usage")

METRICS = ("search", "typeahead", "chat")
QUOTA_METRICS = ("search", "chat")
_FLUSHED_TTL = 60.0
_flushed_cache: dict[tuple[str, str], tuple[float, int]] = {}


class Limits(BaseModel):
    plan: str | None = Field(None, max_length=40)
    searches_per_month: int | None = Field(None, ge=0)
    documents: int | None = Field(None, ge=0)
    llm: bool = True
    block_at_percent: int | None = Field(None, ge=100, le=1000)


def limits_of(project: dict[str, Any] | None) -> Limits:
    return Limits.model_validate((project or {}).get("limits") or {})


def llm_allowed(project: dict[str, Any] | None) -> bool:
    return ((project or {}).get("limits") or {}).get("llm", True) is not False


def current_period() -> str:
    return datetime.now(UTC).strftime("%Y-%m")


def _key(pid: str, period: str, metric: str) -> str:
    return f"use:{pid}:{period}:{metric}"


async def _flushed_quota_use(state: Any, pid: str, period: str) -> int:
    now = time.monotonic()
    hit = _flushed_cache.get((pid, period))
    if hit and hit[0] > now:
        return hit[1]
    async with state.db.connect() as conn:
        n = (await conn.execute(select(func.coalesce(func.sum(usage.c.count), 0)).where(
            usage.c.project_id == pid, usage.c.period == period, usage.c.metric.in_(QUOTA_METRICS)))).scalar_one()
    _flushed_cache[(pid, period)] = (now + _FLUSHED_TTL, int(n))
    return int(n)


async def meter(state: Any, pid: str, project: dict[str, Any], metric: str) -> None:
    """Count one request; raise 429 quota_exceeded first if the project blocks past its quota."""
    period = current_period()
    lim = limits_of(project)
    if metric in QUOTA_METRICS and lim.block_at_percent and lim.searches_per_month is not None:
        pending = await state.redis.mget([_key(pid, period, m) for m in QUOTA_METRICS])
        used = await _flushed_quota_use(state, pid, period) + sum(int(v or 0) for v in pending)
        if used >= lim.searches_per_month * lim.block_at_percent / 100:
            raise ApiError(429, "quota_exceeded", "this project has used its monthly search quota")
    await state.redis.incr(_key(pid, period, metric))


async def flush(state: Any) -> int:
    """Move pending Redis counters into Postgres. Returns the number of counters moved."""
    moved = 0
    async for raw in state.redis.scan_iter(match="use:*", count=500):
        key = raw.decode() if isinstance(raw, bytes) else raw
        try:
            _, pid, period, metric = key.split(":")
        except ValueError:
            continue
        n = int(await state.redis.getdel(key) or 0)
        if not n:
            continue
        try:
            async with state.db.begin() as conn:
                stmt = pg_insert(usage).values(project_id=pid, period=period, metric=metric, count=n)
                await conn.execute(stmt.on_conflict_do_update(
                    index_elements=[usage.c.project_id, usage.c.period, usage.c.metric],
                    set_={"count": usage.c.count + stmt.excluded.count}))
        except Exception as e:  # noqa: BLE001 - keep the count for the next flush (unless the project is gone)
            if "foreign key" not in str(e).lower():
                await state.redis.incrby(key, n)
                log.warning("usage flush failed for %s: %s", key, e)
            continue
        moved += 1
    return moved


async def totals(state: Any, pids: list[str], period: str) -> dict[str, dict[str, int]]:
    """{project_id: {metric: count}} for one month, flushed + pending."""
    out = {pid: dict.fromkeys(METRICS, 0) for pid in pids}
    if not pids:
        return out
    async with state.db.connect() as conn:
        rows = (await conn.execute(select(usage.c.project_id, usage.c.metric, usage.c.count).where(
            usage.c.project_id.in_(pids), usage.c.period == period))).all()
    for pid, metric, n in rows:
        out[pid][metric] = out[pid].get(metric, 0) + int(n)
    keys = [(pid, m) for pid in pids for m in METRICS]
    pending = await state.redis.mget([_key(pid, period, m) for pid, m in keys])
    for (pid, m), v in zip(keys, pending, strict=True):
        out[pid][m] += int(v or 0)
    return out


def report(lim: Limits, counts: dict[str, int], documents: int | None) -> dict[str, Any]:
    used = sum(counts.get(m, 0) for m in QUOTA_METRICS)
    quota = lim.searches_per_month
    return {
        "usage": counts,
        "quota_used": used,
        "quota": quota,
        "quota_percent": round(100 * used / quota, 1) if quota else None,
        "documents": documents,
        "documents_limit": lim.documents,
        "over_limit": bool((quota is not None and used > quota)
                           or (lim.documents is not None and documents is not None and documents > lim.documents)),
    }
