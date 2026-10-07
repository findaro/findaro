"""Executes ingest jobs. Runs in the worker process (or inline in tests)."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import numpy as np
from sqlalchemy import select, text, update

from zerch import store
from zerch.db import job_payloads, jobs
from zerch.index import ops
from zerch.index.normalize import DocError, normalize
from zerch.ingest.parse import PayloadError, parse
from zerch.schema import Schema, SchemaError, flatten, infer_fields, infer_schema
from zerch.state import State

log = logging.getLogger("zerch.ingest")
MAX_ERRORS = 1000


class JobFailed(Exception):
    pass


class Progress:
    def __init__(self, state: State, jid: str, errors: list[dict[str, Any]] | None = None):
        self.state, self.jid = state, jid
        self.processed = self.succeeded = self.failed = 0
        self.errors: list[dict[str, Any]] = list(errors or [])
        self.failed = len(self.errors)

    def fail(self, did: str | None, msg: str, row: int | None = None) -> None:
        self.failed += 1
        if len(self.errors) < MAX_ERRORS:
            e: dict[str, Any] = {"error": msg}
            if did is not None:
                e["id"] = did
            if row is not None:
                e["row"] = row
            self.errors.append(e)

    async def flush(self, **extra: Any) -> None:
        async with self.state.db.begin() as conn:
            await conn.execute(update(jobs).where(jobs.c.id == self.jid).values(
                processed=self.processed, succeeded=self.succeeded, failed=self.failed, errors=self.errors, **extra))


# --- claiming -----------------------------------------------------------------------------------------

CLAIM_SQL = text("""
    SELECT j.id FROM jobs j
    WHERE j.status = 'queued'
      AND j.created_at = (SELECT min(q.created_at) FROM jobs q
                          WHERE q.project_id = j.project_id AND q.status IN ('queued', 'running'))
    ORDER BY j.created_at
    LIMIT 1
    FOR UPDATE SKIP LOCKED
""")


async def claim_next(state: State) -> dict[str, Any] | None:
    async with state.db.begin() as conn:
        jid = (await conn.execute(CLAIM_SQL)).scalar()
        if jid is None:
            return None
        await conn.execute(update(jobs).where(jobs.c.id == jid).values(status="running", started_at=store.now()))
        row = (await conn.execute(select(jobs).where(jobs.c.id == jid))).mappings().first()
    return dict(row)


async def requeue_stale(state: State) -> None:
    async with state.db.begin() as conn:
        await conn.execute(update(jobs).where(jobs.c.status == "running").values(status="queued"))


async def run_pending(state: State, limit: int | None = None) -> int:
    """Run queued jobs until none are left (or `limit` reached). Returns number executed."""
    n = 0
    while limit is None or n < limit:
        job = await claim_next(state)
        if job is None:
            break
        await run_job(state, job)
        n += 1
    return n


async def run_job(state: State, job: dict[str, Any]) -> None:
    jid, pid, kind = job["id"], job["project_id"], job["kind"]
    log.info("job %s (%s) for %s started", jid, kind, pid)
    progress = Progress(state, jid)
    try:
        if kind in ("upsert", "import"):
            async with state.db.connect() as conn:
                p = (await conn.execute(select(job_payloads).where(job_payloads.c.job_id == jid))).mappings().first()
            if p is None:
                raise JobFailed("payload missing")
            try:
                docs, parse_errors = parse(p["data"], p["format"])
            except PayloadError as e:
                raise JobFailed(str(e)) from e
            progress = Progress(state, jid, parse_errors)
            async with state.db.begin() as conn:
                await conn.execute(update(jobs).where(jobs.c.id == jid).values(total=len(docs) + len(parse_errors)))
            await ingest_documents(state, pid, docs, progress)
            async with state.db.begin() as conn:
                await conn.execute(job_payloads.delete().where(job_payloads.c.job_id == jid))
        elif kind == "delete":
            await delete_documents(state, pid, list(job["params"].get("ids", [])), progress)
        elif kind == "reindex":
            await reindex(state, pid, progress)
        else:
            raise JobFailed(f"unknown job kind {kind}")
        status = "succeeded" if progress.failed == 0 else ("failed" if progress.succeeded == 0 and progress.processed
                                                             else "completed_with_errors")
        await progress.flush(status=status, finished_at=store.now())
        log.info("job %s %s: ok=%d failed=%d", jid, status, progress.succeeded, progress.failed)
    except (JobFailed, SchemaError) as e:
        await progress.flush(status="failed", message=str(e), finished_at=store.now())
        log.warning("job %s failed: %s", jid, e)
    except Exception as e:  # noqa: BLE001 - job must always reach a terminal state
        log.exception("job %s crashed", jid)
        await progress.flush(status="failed", message=f"internal error: {type(e).__name__}: {e}"[:1000],
                             finished_at=store.now())


# --- operations ---------------------------------------------------------------------------------------

async def _ensure_index(state: State, pid: str, docs: list[dict[str, Any]]) -> tuple[Schema, str]:
    """Infer the schema on first ingest; add newly seen fields afterwards. Returns (schema, physical index)."""
    s = state.settings
    async with state.db.begin() as conn:
        project = await store.get_project(conn, pid)
        if project is None:
            raise JobFailed("project no longer exists")
        schema = store.load_schema(project["schema"])
        if schema is None:
            schema = infer_schema(docs)
            version = project["index_version"] + 1
            name = ops.index_name(s.index_prefix, pid, version)
            await ops.create_index(state.os, name, schema, state.embedder.dim)
            await ops.point_alias(state.os, ops.alias_name(s.index_prefix, pid), name)
            await store.update_project(conn, pid, schema=schema.public(), index_version=version,
                                       schema_version=project["schema_version"] + 1)
            return schema, name
        name = ops.index_name(s.index_prefix, pid, project["index_version"])
        known = {f.name for f in schema.fields}
        seen = {k for d in docs for k in flatten(d)}
        new = seen - known
        if new:
            schema = schema.with_fields(infer_fields(docs, new))
            await ops.add_fields(state.os, name, schema)
            await store.update_project(conn, pid, schema=schema.public(),
                                       schema_version=project["schema_version"] + 1)
        return schema, name


async def _embed(state: State, texts: list[str]) -> np.ndarray:
    return await asyncio.to_thread(state.embedder.embed_documents, texts)


async def ingest_documents(state: State, pid: str, docs: list[dict[str, Any]], progress: Progress) -> None:
    if not docs:
        return
    schema, index = await _ensure_index(state, pid, docs)
    bs = state.settings.bulk_batch_size
    for start in range(0, len(docs), bs):
        batch = docs[start : start + bs]
        ids, bodies, texts = [], [], []
        for i, raw in enumerate(batch):
            try:
                did, body, etext = normalize(raw, schema)
            except DocError as e:
                progress.fail(None, str(e), row=start + i + 1)
                continue
            ids.append(did)
            bodies.append(body)
            texts.append(etext)
        if bodies:
            vecs = await _embed(state, texts)
            for body, v in zip(bodies, vecs, strict=True):
                body["zz_vec"] = v
            errors = await ops.bulk(state.os, index, [("index", d, b) for d, b in zip(ids, bodies, strict=True)])
            for e in errors:
                progress.fail(e["id"], e["error"])
            progress.succeeded += len(bodies) - len(errors)
        progress.processed += len(batch)
        await progress.flush()
    await state.os.indices.refresh(index=index)
    await store.bump_data_version(state.db, pid)


async def delete_documents(state: State, pid: str, ids: list[str], progress: Progress) -> None:
    project = await store.get_project(state.db, pid)
    if project is None or project["schema"] is None:
        for did in ids:
            progress.fail(did, "not_found")
        progress.processed = len(ids)
        return
    index = ops.index_name(state.settings.index_prefix, pid, project["index_version"])
    bs = state.settings.bulk_batch_size * 4
    for start in range(0, len(ids), bs):
        chunk = ids[start : start + bs]
        errors = await ops.bulk(state.os, index, [("delete", str(d), None) for d in chunk])
        for e in errors:
            progress.fail(e["id"], e["error"])
        progress.succeeded += len(chunk) - len(errors)
        progress.processed += len(chunk)
        await progress.flush()
    await state.os.indices.refresh(index=index)
    await store.bump_data_version(state.db, pid)


async def reindex(state: State, pid: str, progress: Progress) -> None:
    """Build a new physical index from the pending schema, then swap the alias."""
    s = state.settings
    project = await store.get_project(state.db, pid)
    if project is None:
        raise JobFailed("project no longer exists")
    schema = store.load_schema(project["pending_schema"]) or store.load_schema(project["schema"])
    if schema is None:
        raise JobFailed("project has no schema")
    old_version = project["index_version"]
    new_version = old_version + 1
    alias = ops.alias_name(s.index_prefix, pid)
    new_index = ops.index_name(s.index_prefix, pid, new_version)

    if old_version == 0:  # nothing indexed yet: just create the index
        await ops.create_index(state.os, new_index, schema, state.embedder.dim)
        await ops.point_alias(state.os, alias, new_index)
    else:
        old_index = ops.index_name(s.index_prefix, pid, old_version)
        total = await ops.count(state.os, old_index)
        async with state.db.begin() as conn:
            await conn.execute(update(jobs).where(jobs.c.id == progress.jid).values(total=total))
        # Fields that arrived after the pending schema was written still need roles.
        await ops.create_index(state.os, new_index, schema, state.embedder.dim)
        resp = await state.os.search(index=old_index, scroll="2m", size=500,
                                     body={"query": {"match_all": {}}, "_source": ["zz_raw", "zz_vec", "zz_ehash"]})
        scroll_id = resp.get("_scroll_id")
        try:
            while hits := resp["hits"]["hits"]:
                raws = [h["_source"]["zz_raw"] for h in hits]
                known = {f.name for f in schema.fields}
                new = {k for d in raws for k in flatten(d)} - known
                if new:
                    schema = schema.with_fields(infer_fields(raws, new))
                    await ops.add_fields(state.os, new_index, schema)
                actions, need, need_idx = [], [], []
                for h in hits:
                    src = h["_source"]
                    try:
                        did, body, etext = normalize(src["zz_raw"], schema)
                    except DocError as e:
                        progress.fail(h["_id"], str(e))
                        continue
                    if body["zz_ehash"] == src.get("zz_ehash") and src.get("zz_vec"):
                        body["zz_vec"] = src["zz_vec"]
                    else:
                        need.append(etext)
                        need_idx.append(len(actions))
                    actions.append(("index", did, body))
                if need:
                    vecs = await _embed(state, need)
                    for i, v in zip(need_idx, vecs, strict=True):
                        actions[i][2]["zz_vec"] = v
                errors = await ops.bulk(state.os, new_index, actions)
                for e in errors:
                    progress.fail(e["id"], e["error"])
                progress.succeeded += len(actions) - len(errors)
                progress.processed += len(hits)
                await progress.flush()
                resp = await state.os.scroll(scroll_id=scroll_id, scroll="2m")
                scroll_id = resp.get("_scroll_id", scroll_id)
        finally:
            if scroll_id:
                await state.os.clear_scroll(scroll_id=scroll_id, ignore=(404,))
        await state.os.indices.refresh(index=new_index)
        old = await ops.point_alias(state.os, alias, new_index)
        for idx in old:
            await state.os.indices.delete(index=idx, ignore_unavailable=True)

    async with state.db.begin() as conn:
        p = await store.get_project(conn, pid)
        await store.update_project(conn, pid, schema=schema.public(), pending_schema=None, index_version=new_version,
                                   schema_version=p["schema_version"] + 1, data_version=p["data_version"] + 1)
