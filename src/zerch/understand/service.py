"""understand(): query -> validated QueryPlan. Rules always; LLM only when the rules plan is unsure."""

from __future__ import annotations

import asyncio
import hashlib
import logging
import time
from typing import Any

import orjson

from zerch import usage
from zerch.llm.base import LLMError
from zerch.schema.model import Schema
from zerch.understand import dictionary as dict_mod
from zerch.understand.dictionary import Compiled, compile_payload
from zerch.understand.lexicon import default_lexicon, fold
from zerch.understand.llm_planner import call_llm, merge
from zerch.understand.plan import QueryPlan, validate_plan
from zerch.understand.rules import RulesParser

log = logging.getLogger("zerch.understand")

_RECHECK_S = 5.0
# pid -> (checked_at, schema_version, Compiled)
_dicts: dict[str, tuple[float, int, Compiled]] = {}
_locks: dict[str, asyncio.Lock] = {}
_inflight: dict[str, asyncio.Task] = {}  # plan cache key -> running planner call (shared by identical queries)
MAX_CONCURRENT_PLANNER_CALLS = 2


def lexicon(state: Any):
    return default_lexicon(tuple(p.strip() for p in state.settings.locale_packs.split(",") if p.strip()))


async def get_dictionary(state: Any, pid: str, project: dict[str, Any], schema: Schema) -> Compiled | None:
    now = time.monotonic()
    hit = _dicts.get(pid)
    if hit and hit[1] == project["schema_version"]:
        checked, _, comp = hit
        if comp.data_version >= project["data_version"] or now - checked < _RECHECK_S:
            return comp
    lock = _locks.setdefault(pid, asyncio.Lock())
    async with lock:
        hit = _dicts.get(pid)
        if hit and hit[1] == project["schema_version"] and (
                hit[2].data_version >= project["data_version"] or time.monotonic() - hit[0] < _RECHECK_S):
            return hit[2]
        row = await dict_mod.load_row(state, pid)
        if row is None:
            # First search on a project indexed before dictionaries existed: build it once, inline.
            payload = await dict_mod.refresh(state, pid)
            if payload is None:
                return None
        else:
            payload = row[1]
        comp = compile_payload(payload, schema, lexicon(state))
        _dicts[pid] = (time.monotonic(), project["schema_version"], comp)
        return comp


def cached_dictionary(pid: str) -> Compiled | None:
    hit = _dicts.get(pid)
    return hit[2] if hit else None


def _plan_key(pid: str, project: dict[str, Any], query: str) -> str:
    norm = " ".join(fold(query).split())
    return f"qplan:{pid}:{project['schema_version']}:{hashlib.sha1(norm.encode()).hexdigest()}"


async def understand(state: Any, pid: str, project: dict[str, Any], schema: Schema, query: str,
                     use_plan_cache: bool = True, allow_llm: bool = True) -> tuple[QueryPlan, dict[str, Any]]:
    s = state.settings
    t0 = time.perf_counter()
    d = await get_dictionary(state, pid, project, schema)
    t_dict = time.perf_counter()
    plan = validate_plan(RulesParser(schema, lexicon(state), d).parse(query), schema, d)
    info: dict[str, Any] = {"llm": "not_needed", "dictionary_ms": round((t_dict - t0) * 1000, 2),
                            "rules_ms": round((time.perf_counter() - t_dict) * 1000, 2)}
    need = bool(plan.unparsed_tokens) or plan.confidence < s.planner_confidence_threshold
    allow_llm = allow_llm and usage.llm_allowed(project)
    if not need or not s.understand_llm:
        return plan, info
    if not allow_llm:  # e.g. search-as-you-type: rules only, but still use a plan the LLM made earlier
        info["llm"] = "skipped"

    key = _plan_key(pid, project, query)
    if use_plan_cache:
        raw = await state.redis.get(key)
        if raw:
            info["llm"] = "cache"
            return validate_plan(merge(plan, orjson.loads(raw), schema, d, "cache"), schema, d), info

    if not allow_llm:
        return plan, info
    llm = getattr(state, "planner", None)
    if llm is None:
        info["llm"] = "unavailable"
        return plan, info

    rules_plan = plan
    task = _inflight.get(key)
    if task is None:
        if len(_inflight) >= MAX_CONCURRENT_PLANNER_CALLS:
            info["llm"] = "busy"  # don't queue more model calls behind slow ones; the rules plan is used
            return plan, info

        async def run() -> dict[str, Any]:
            out = await call_llm(llm, query, schema, d, rules_plan)
            await state.redis.set(key, orjson.dumps(out), ex=s.plan_cache_ttl)
            return out

        task = asyncio.create_task(run())
        _inflight[key] = task  # a timed-out call keeps running and fills the cache for the next request
        task.add_done_callback(lambda _t, k=key: _inflight.pop(k, None))
        task.add_done_callback(_log_failure)
    t_llm = time.perf_counter()
    try:
        out = await asyncio.wait_for(asyncio.shield(task), timeout=s.planner_timeout_ms / 1000)
    except TimeoutError:
        info.update(llm="timeout", llm_ms=round((time.perf_counter() - t_llm) * 1000, 1))
        return plan, info
    except (LLMError, ValueError) as e:
        info.update(llm="error", llm_error=str(e)[:200], llm_ms=round((time.perf_counter() - t_llm) * 1000, 1))
        return plan, info
    info.update(llm="called", llm_ms=round((time.perf_counter() - t_llm) * 1000, 1))
    return validate_plan(merge(plan, out, schema, d, "llm"), schema, d), info


def _log_failure(task: asyncio.Task) -> None:
    if not task.cancelled() and task.exception() is not None:
        log.warning("planner call failed: %s", task.exception())
