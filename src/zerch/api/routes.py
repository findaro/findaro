from __future__ import annotations

import re
from typing import Any

import orjson
from fastapi import APIRouter, Depends, File, Query, Request, Response, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, ValidationError

from zerch import store
from zerch.auth import Principal, authenticate, cached_project, check_bootstrap, forget_project, require_admin
from zerch.chat.service import ChatRequest, chat_turn
from zerch.errors import ApiError
from zerch.index import ops
from zerch.ingest.parse import PayloadError, detect_format
from zerch.schema.model import Schema, SchemaError, SchemaUpdate
from zerch.search.models import SearchRequest, SearchResponse
from zerch.search.service import search as run_search
from zerch.state import State

router = APIRouter()


def get_state(request: Request) -> State:
    return request.app.state.zerch


async def principal(request: Request, state: State = Depends(get_state)) -> Principal:
    return await authenticate(request, state)


async def admin_for(project_id: str, p: Principal = Depends(principal)) -> Principal:
    require_admin(p, project_id)
    return p


class CreateProject(BaseModel):
    name: str = Field("default", max_length=200)


class ProjectSettings(BaseModel):
    allowed_origins: list[str] | None = Field(None, max_length=100)


class DeleteIds(BaseModel):
    ids: list[str] = Field(min_length=1, max_length=100_000)


def _accepted(jid: str, pid: str) -> dict[str, Any]:
    return {"job_id": jid, "status": "queued", "status_url": f"/v1/projects/{pid}/jobs/{jid}"}


@router.get("/healthz", include_in_schema=False)
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


@router.post("/v1/projects", status_code=201)
async def create_project(request: Request, body: CreateProject | None = None,
                         state: State = Depends(get_state)) -> dict[str, Any]:
    check_bootstrap(request, state)
    out = await store.create_project(state.db, (body or CreateProject()).name)
    return {**out, "name": (body or CreateProject()).name}


@router.get("/v1/projects/{project_id}")
async def get_project(project_id: str, _: Principal = Depends(admin_for),
                      state: State = Depends(get_state)) -> dict[str, Any]:
    p = await store.get_project(state.db, project_id)
    if p is None:
        raise ApiError(404, "not_found", "project not found")
    return {
        "project_id": p["id"], "name": p["name"], "created_at": p["created_at"].isoformat(),
        "document_count": await ops.count(state.os, ops.alias_name(state.settings.index_prefix, project_id)),
        "has_schema": p["schema"] is not None, "schema_version": p["schema_version"],
        "reindex_pending": p["pending_schema"] is not None, "allowed_origins": p["allowed_origins"] or [],
    }


@router.put("/v1/projects/{project_id}/settings")
async def put_settings(project_id: str, body: ProjectSettings, _: Principal = Depends(admin_for),
                       state: State = Depends(get_state)) -> dict[str, Any]:
    """Project settings. `allowed_origins`: browser origins that may use the search key
    (exact like "https://shop.example.com", or "https://*.example.com"; localhost always works in dev)."""
    values: dict[str, Any] = {}
    if body.allowed_origins is not None:
        bad = [o for o in body.allowed_origins if o != "*" and not re.match(r"^https?://[^/\s]+$", o.rstrip("/"))]
        if bad:
            raise ApiError(400, "invalid_origin", f"origins look like https://shop.example.com; got {bad}")
        values["allowed_origins"] = [o.rstrip("/") for o in body.allowed_origins]
    if values:
        async with state.db.begin() as conn:
            await store.update_project(conn, project_id, **values)
        forget_project(project_id)
    p = await store.get_project(state.db, project_id)
    return {"allowed_origins": p["allowed_origins"] or []}


@router.delete("/v1/projects/{project_id}", status_code=204)
async def delete_project(project_id: str, _: Principal = Depends(admin_for),
                         state: State = Depends(get_state)) -> Response:
    await ops.drop_indices(state.os, state.settings.index_prefix, project_id)
    try:
        await state.os.indices.delete_alias(index="_all", name=ops.alias_name(state.settings.index_prefix, project_id),
                                            ignore=(404,))
    except Exception:  # noqa: BLE001 - alias goes away with its indices anyway
        pass
    await store.delete_project(state.db, project_id)
    forget_project(project_id)
    return Response(status_code=204)


# --- documents ------------------------------------------------------------------------------------

@router.post("/v1/projects/{project_id}/documents", status_code=202)
async def upsert_documents(project_id: str, request: Request, _: Principal = Depends(admin_for),
                           state: State = Depends(get_state)) -> dict[str, Any]:
    raw = await request.body()
    if len(raw) > state.settings.max_upload_mb * 1024 * 1024:
        raise ApiError(413, "too_large", f"body exceeds {state.settings.max_upload_mb} MB; use /import")
    try:
        data = orjson.loads(raw)
    except orjson.JSONDecodeError as e:
        raise ApiError(400, "invalid_json", str(e)) from e
    if isinstance(data, dict) and "documents" in data:
        data = data["documents"]
    if not isinstance(data, list) or not data:
        raise ApiError(400, "invalid_documents", "body must be a non-empty JSON array of documents")
    if len(data) > state.settings.max_documents_per_request:
        raise ApiError(413, "too_many_documents",
                       f"at most {state.settings.max_documents_per_request} documents per request; use /import")
    jid = await store.create_job(state.db, project_id, "upsert", payload=orjson.dumps(data), fmt="json",
                                 total=len(data))
    return _accepted(jid, project_id)


@router.post("/v1/projects/{project_id}/import", status_code=202)
async def import_file(project_id: str, file: UploadFile = File(...),
                      format: str | None = Query(None, description="csv | jsonl | json"),  # noqa: A002
                      _: Principal = Depends(admin_for), state: State = Depends(get_state)) -> dict[str, Any]:
    try:
        fmt = detect_format(file.filename, file.content_type, format)
    except PayloadError as e:
        raise ApiError(400, "invalid_format", str(e)) from e
    limit = state.settings.max_upload_mb * 1024 * 1024
    data = await file.read(limit + 1)
    if len(data) > limit:
        raise ApiError(413, "too_large", f"file exceeds {state.settings.max_upload_mb} MB")
    if not data.strip():
        raise ApiError(400, "empty_file", "uploaded file is empty")
    jid = await store.create_job(state.db, project_id, "import", payload=data, fmt=fmt,
                                 params={"filename": file.filename})
    return _accepted(jid, project_id)


@router.delete("/v1/projects/{project_id}/documents/{doc_id}", status_code=202)
async def delete_document(project_id: str, doc_id: str, _: Principal = Depends(admin_for),
                          state: State = Depends(get_state)) -> dict[str, Any]:
    jid = await store.create_job(state.db, project_id, "delete", params={"ids": [doc_id]}, total=1)
    return _accepted(jid, project_id)


@router.post("/v1/projects/{project_id}/documents/delete", status_code=202)
async def delete_documents(project_id: str, body: DeleteIds, _: Principal = Depends(admin_for),
                           state: State = Depends(get_state)) -> dict[str, Any]:
    jid = await store.create_job(state.db, project_id, "delete", params={"ids": body.ids}, total=len(body.ids))
    return _accepted(jid, project_id)


@router.get("/v1/projects/{project_id}/documents/{doc_id}")
async def get_document(project_id: str, doc_id: str, _: Principal = Depends(admin_for),
                       state: State = Depends(get_state)) -> dict[str, Any]:
    r = await state.os.search(index=ops.alias_name(state.settings.index_prefix, project_id), ignore_unavailable=True,
                              body={"query": {"ids": {"values": [doc_id]}}, "_source": ["zz_raw"], "size": 1})
    hits = r.get("hits", {}).get("hits", [])
    if not hits:
        raise ApiError(404, "not_found", "document not found")
    return {"id": doc_id, "document": hits[0]["_source"]["zz_raw"]}


# --- jobs -----------------------------------------------------------------------------------------

@router.get("/v1/projects/{project_id}/jobs/{job_id}")
async def get_job(project_id: str, job_id: str, _: Principal = Depends(admin_for),
                  state: State = Depends(get_state)) -> dict[str, Any]:
    row = await store.get_job(state.db, project_id, job_id)
    if row is None:
        raise ApiError(404, "not_found", "job not found")
    return store.job_public(row)


@router.get("/v1/projects/{project_id}/jobs")
async def list_jobs(project_id: str, limit: int = Query(20, ge=1, le=100), _: Principal = Depends(admin_for),
                    state: State = Depends(get_state)) -> dict[str, Any]:
    return {"jobs": [store.job_public(r) for r in await store.list_jobs(state.db, project_id, limit)]}


# --- schema ---------------------------------------------------------------------------------------

@router.get("/v1/projects/{project_id}/schema")
async def get_schema(project_id: str, _: Principal = Depends(admin_for),
                     state: State = Depends(get_state)) -> dict[str, Any]:
    p = await store.get_project(state.db, project_id)
    if p is None:
        raise ApiError(404, "not_found", "project not found")
    if p["schema"] is None and p["pending_schema"] is None:
        raise ApiError(404, "no_schema", "no schema yet: ingest documents or PUT a schema")
    return {"schema": p["schema"], "pending_schema": p["pending_schema"], "schema_version": p["schema_version"]}


@router.put("/v1/projects/{project_id}/schema")
async def put_schema(project_id: str, request: Request, response: Response, _: Principal = Depends(admin_for),
                     state: State = Depends(get_state)) -> dict[str, Any]:
    try:
        body = SchemaUpdate.model_validate_json(await request.body())
        schema = Schema.build(body.fields, inferred=False)
    except (ValidationError, SchemaError) as e:
        msg = str(e) if isinstance(e, SchemaError) else "invalid schema"
        details = None if isinstance(e, SchemaError) else [
            {"loc": list(x["loc"]), "msg": x["msg"]} for x in e.errors()]
        raise ApiError(400, "invalid_schema", msg, details) from e
    async with state.db.begin() as conn:
        p = await store.get_project(conn, project_id)
        if p is None:
            raise ApiError(404, "not_found", "project not found")
        await store.update_project(conn, project_id, pending_schema=schema.public())
    # Every schema change is applied by a reindex job, queued behind any pending ingest.
    jid = await store.create_job(state.db, project_id, "reindex")
    forget_project(project_id)
    response.status_code = 202
    return {**_accepted(jid, project_id), "pending_schema": schema.public()}


# --- search ---------------------------------------------------------------------------------------

@router.post("/v1/search", response_model=SearchResponse, response_model_exclude_none=True)
async def search(body: SearchRequest, request: Request, p: Principal = Depends(principal),
                 state: State = Depends(get_state)) -> SearchResponse:
    project = await cached_project(state, p.project_id)
    if project is None:
        raise ApiError(404, "not_found", "project not found")
    schema = store.load_schema(project["schema"])
    no_cache = "no-cache" in request.headers.get("cache-control", "")
    # Eval/benchmark hook: force the query planner to run instead of reusing a cached LLM plan.
    bypass_plans = request.headers.get("x-zerch-plan-cache", "").lower() == "bypass"
    return await run_search(state, p.project_id, project, schema, body, use_cache=not no_cache,
                            use_plan_cache=not bypass_plans)


# --- chat -----------------------------------------------------------------------------------------

@router.post("/v1/chat", response_class=StreamingResponse)
async def chat(body: ChatRequest, p: Principal = Depends(principal),
               state: State = Depends(get_state)) -> StreamingResponse:
    """Conversational search over Server-Sent Events: session, plan, results, clarify?, text*, done."""
    if not body.message.strip() and body.apply is None and not body.patch:
        raise ApiError(400, "empty_message", "send a message, or a `patch` (e.g. from a chip)")
    project = await cached_project(state, p.project_id)
    if project is None:
        raise ApiError(404, "not_found", "project not found")
    schema = store.load_schema(project["schema"])
    return StreamingResponse(chat_turn(state, p.project_id, project, schema, body), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
