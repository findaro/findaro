"""Postgres access for projects, keys and jobs."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import delete, insert, select, update
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from zerch.db import api_keys, job_payloads, jobs, projects
from zerch.ids import hash_key, new_id, new_key
from zerch.schema.model import Schema


def now() -> datetime:
    return datetime.now(UTC)


async def create_project(db: AsyncEngine, name: str) -> dict[str, str]:
    pid = new_id("prj")
    admin, search = new_key("admin"), new_key("search")
    async with db.begin() as conn:
        await conn.execute(insert(projects).values(id=pid, name=name))
        for kind, key in (("admin", admin), ("search", search)):
            await conn.execute(insert(api_keys).values(
                id=new_id("key"), project_id=pid, kind=kind, key_hash=hash_key(key), key_prefix=key[:14]))
    return {"project_id": pid, "admin_key": admin, "search_key": search}


async def get_project(db: AsyncEngine | AsyncConnection, pid: str) -> dict[str, Any] | None:
    q = select(projects).where(projects.c.id == pid)
    if isinstance(db, AsyncConnection):
        row = (await db.execute(q)).mappings().first()
    else:
        async with db.connect() as conn:
            row = (await conn.execute(q)).mappings().first()
    return dict(row) if row else None


async def list_projects(db: AsyncEngine) -> list[dict[str, Any]]:
    async with db.connect() as conn:
        rows = (await conn.execute(select(projects.c.id, projects.c.name, projects.c.created_at, projects.c.limits)
                                   .order_by(projects.c.created_at))).mappings().all()
    return [dict(r) for r in rows]


async def delete_project(db: AsyncEngine, pid: str) -> None:
    async with db.begin() as conn:
        await conn.execute(delete(projects).where(projects.c.id == pid))


async def lookup_key(db: AsyncEngine, key: str) -> dict[str, Any] | None:
    async with db.connect() as conn:
        row = (await conn.execute(
            select(api_keys.c.id, api_keys.c.project_id, api_keys.c.kind).where(api_keys.c.key_hash == hash_key(key))
        )).mappings().first()
    return dict(row) if row else None


async def update_project(conn: AsyncConnection, pid: str, **values: Any) -> None:
    await conn.execute(update(projects).where(projects.c.id == pid).values(**values))


async def bump_data_version(db: AsyncEngine, pid: str) -> None:
    async with db.begin() as conn:
        await conn.execute(update(projects).where(projects.c.id == pid)
                           .values(data_version=projects.c.data_version + 1))


def load_schema(raw: dict | None) -> Schema | None:
    return Schema.model_validate(raw) if raw else None


# --- jobs -------------------------------------------------------------------------------------------

async def create_job(db: AsyncEngine, pid: str, kind: str, *, params: dict | None = None,
                     payload: bytes | None = None, fmt: str = "json", total: int | None = None) -> str:
    jid = new_id("job")
    async with db.begin() as conn:
        await conn.execute(insert(jobs).values(id=jid, project_id=pid, kind=kind, params=params or {}, total=total))
        if payload is not None:
            await conn.execute(insert(job_payloads).values(job_id=jid, format=fmt, data=payload))
    return jid


async def get_job(db: AsyncEngine, pid: str, jid: str) -> dict[str, Any] | None:
    async with db.connect() as conn:
        row = (await conn.execute(select(jobs).where(jobs.c.id == jid, jobs.c.project_id == pid))).mappings().first()
    return dict(row) if row else None


async def list_jobs(db: AsyncEngine, pid: str, limit: int = 20) -> list[dict[str, Any]]:
    async with db.connect() as conn:
        rows = (await conn.execute(
            select(jobs).where(jobs.c.project_id == pid).order_by(jobs.c.created_at.desc()).limit(limit)
        )).mappings().all()
    return [dict(r) for r in rows]


def job_public(row: dict[str, Any]) -> dict[str, Any]:
    out = {k: row[k] for k in ("id", "kind", "status", "total", "processed", "succeeded", "failed", "message")}
    out["errors"] = (row.get("errors") or [])[:50]
    for k in ("created_at", "started_at", "finished_at"):
        out[k] = row[k].isoformat() if row.get(k) else None
    return out
