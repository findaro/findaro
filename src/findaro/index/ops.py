"""OpenSearch index lifecycle: one alias per project pointing at a versioned physical index."""

from __future__ import annotations

from typing import Any

import orjson
from opensearchpy import AsyncOpenSearch, NotFoundError

from findaro.index.mapping import index_body, properties
from findaro.schema.model import Schema


def alias_name(prefix: str, pid: str) -> str:
    return f"{prefix}-{pid}".lower()


def index_name(prefix: str, pid: str, version: int) -> str:
    return f"{prefix}-{pid}-v{version}".lower()


async def create_index(os: AsyncOpenSearch, name: str, schema: Schema, dim: int) -> None:
    await os.indices.create(index=name, body=index_body(schema, dim))


async def point_alias(os: AsyncOpenSearch, alias: str, new_index: str) -> list[str]:
    """Atomically point alias at new_index. Returns indices it previously pointed at."""
    old: list[str] = []
    try:
        old = list((await os.indices.get_alias(name=alias)).keys())
    except NotFoundError:
        pass
    actions: list[dict[str, Any]] = [{"remove": {"index": i, "alias": alias}} for i in old if i != new_index]
    actions.append({"add": {"index": new_index, "alias": alias}})
    await os.indices.update_aliases(body={"actions": actions})
    return [i for i in old if i != new_index]


async def add_fields(os: AsyncOpenSearch, index: str, schema: Schema) -> None:
    await os.indices.put_mapping(index=index, body={"properties": properties(schema)})


async def bulk(os: AsyncOpenSearch, index: str, actions: list[tuple[str, str, dict | None]],
               refresh: bool | str = False) -> list[dict[str, Any]]:
    """actions: (op, id, body) with op in {'index', 'delete'}. Returns per-item errors."""
    if not actions:
        return []
    lines: list[bytes] = []
    for op, did, body in actions:
        lines.append(orjson.dumps({op: {"_index": index, "_id": did}}))
        if op == "index":
            lines.append(orjson.dumps(body, option=orjson.OPT_SERIALIZE_NUMPY))
    payload = b"\n".join(lines) + b"\n"
    resp = await os.bulk(body=payload, refresh=refresh)
    errors = []
    if resp.get("errors") or any(op == "delete" for op, _, _ in actions):
        for item in resp["items"]:
            (op, res), = item.items()
            if op == "delete" and res.get("result") == "not_found":
                errors.append({"id": res.get("_id"), "error": "not_found"})
            elif res.get("error"):
                err = res["error"]
                reason = err.get("reason") if isinstance(err, dict) else str(err)
                caused = err.get("caused_by", {}).get("reason") if isinstance(err, dict) else None
                errors.append({"id": res.get("_id"), "error": f"{reason}{': ' + caused if caused else ''}"[:500]})
    return errors


async def drop_indices(os: AsyncOpenSearch, prefix: str, pid: str) -> None:
    await os.indices.delete(index=f"{alias_name(prefix, pid)}-v*", ignore_unavailable=True,
                            params={"expand_wildcards": "all"})


async def count(os: AsyncOpenSearch, alias: str) -> int:
    try:
        return int((await os.count(index=alias))["count"])
    except NotFoundError:
        return 0
