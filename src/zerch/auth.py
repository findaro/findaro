"""API key auth. Admin keys manage one project; search keys (browser-safe) can only search it."""

from __future__ import annotations

import hmac
import re
import time
from dataclasses import dataclass
from typing import Any

from fastapi import Request

from zerch import store
from zerch.errors import ApiError
from zerch.state import State

_KEY_TTL = 60.0
_PROJECT_TTL = 2.0
_key_cache: dict[str, tuple[float, dict[str, Any] | None]] = {}
_project_cache: dict[str, tuple[float, dict[str, Any] | None]] = {}


@dataclass
class Principal:
    key_id: str
    project_id: str
    kind: str  # admin | search


def extract_key(request: Request) -> str | None:
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return request.headers.get("x-zerch-key")


async def authenticate(request: Request, state: State) -> Principal:
    key = extract_key(request)
    if not key:
        raise ApiError(401, "unauthorized", "missing API key (Authorization: Bearer <key>)")
    now = time.monotonic()
    hit = _key_cache.get(key)
    if hit and hit[0] > now:
        row = hit[1]
    else:
        row = await store.lookup_key(state.db, key)
        if len(_key_cache) > 10_000:
            _key_cache.clear()
        _key_cache[key] = (now + _KEY_TTL, row)
    if row is None:
        raise ApiError(401, "unauthorized", "invalid API key")
    p = Principal(key_id=row["id"], project_id=row["project_id"], kind=row["kind"])
    await check_origin(request, state, p)
    await rate_limit(state, p)
    return p


_LOCAL = re.compile(r"^https?://(localhost|127\.0\.0\.1|\[::1\])(:\d+)?$")


def origin_allowed(origin: str, allowed: list[str], allow_localhost: bool) -> bool:
    origin = origin.rstrip("/").lower()
    if allow_localhost and _LOCAL.match(origin):
        return True
    for pattern in allowed:
        pattern = pattern.rstrip("/").lower()
        if pattern == "*" or pattern == origin:
            return True
        if "*." in pattern:  # https://*.example.com matches one or more subdomain levels
            scheme, _, host = pattern.partition("://*.")
            if origin.startswith(scheme + "://") and origin.endswith("." + host):
                return True
    return False


async def check_origin(request: Request, state: State, p: Principal) -> None:
    """Browsers always send Origin on cross-site requests; server-to-server calls usually don't."""
    origin = request.headers.get("origin")
    if not origin:
        return
    if p.kind == "admin":
        raise ApiError(403, "admin_key_in_browser", "admin keys must stay server-side; use the search key")
    project = await cached_project(state, p.project_id)
    allowed = (project or {}).get("allowed_origins") or []
    if not origin_allowed(origin, allowed, state.settings.allow_localhost_origins):
        raise ApiError(403, "origin_not_allowed",
                       f"origin {origin} is not in this project's allowed_origins "
                       "(PUT /v1/projects/{id}/settings with the admin key)")


async def rate_limit(state: State, p: Principal) -> None:
    limit = state.settings.rate_limit_per_second
    if limit <= 0:
        return
    bucket = f"rl:{p.key_id}:{int(time.time())}"
    pipe = state.redis.pipeline()
    pipe.incr(bucket)
    pipe.expire(bucket, 2)
    n, _ = await pipe.execute()
    if n > limit:
        raise ApiError(429, "rate_limited", f"rate limit of {limit} requests/second exceeded")


def require_admin(p: Principal, project_id: str) -> None:
    if p.kind != "admin":
        raise ApiError(403, "forbidden", "this endpoint needs the project's admin key")
    if p.project_id != project_id:
        raise ApiError(404, "not_found", "project not found")


def check_bootstrap(request: Request, state: State) -> None:
    token = state.settings.bootstrap_token
    if not token:
        return
    given = extract_key(request) or ""
    if not hmac.compare_digest(given.encode(), token.encode()):
        raise ApiError(401, "unauthorized", "creating projects requires the bootstrap token")


async def cached_project(state: State, pid: str) -> dict[str, Any] | None:
    now = time.monotonic()
    hit = _project_cache.get(pid)
    if hit and hit[0] > now:
        return hit[1]
    row = await store.get_project(state.db, pid)
    _project_cache[pid] = (now + _PROJECT_TTL, row)
    return row


def forget_project(pid: str) -> None:
    _project_cache.pop(pid, None)
    for k, (_, row) in list(_key_cache.items()):
        if row and row["project_id"] == pid:
            _key_cache.pop(k, None)
