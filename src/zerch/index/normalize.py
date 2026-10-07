"""Turn a raw document into the indexed shape, according to the schema."""

from __future__ import annotations

import hashlib
from typing import Any

from zerch.schema.infer import parse_bool, parse_number
from zerch.schema.model import Role, Schema, flatten

MAX_TEXT = 20_000
EMBED_CHARS = 1200


class DocError(ValueError):
    pass


def _as_list(v: Any) -> list[Any]:
    if v is None:
        return []
    return v if isinstance(v, list) else [v]


def _strings(v: Any, sep: str | None) -> list[str]:
    out = []
    for x in _as_list(v):
        if x is None or isinstance(x, dict | list):
            continue
        s = str(x).strip()
        if not s:
            continue
        if sep and isinstance(x, str) and sep in s:
            out.extend(p.strip() for p in s.split(sep) if p.strip())
        else:
            out.append(s)
    return out


def category_paths(v: Any, sep: str | None) -> tuple[list[str], list[str]]:
    """Return (normalised full paths, all prefixes) for a category value."""
    paths, prefixes = [], []
    for raw in _strings(v, None):
        parts = [p.strip() for p in (raw.split(sep) if sep else [raw]) if p.strip()]
        if not parts:
            continue
        paths.append(" > ".join(parts))
        for i in range(1, len(parts) + 1):
            p = " > ".join(parts[:i])
            if p not in prefixes:
                prefixes.append(p)
    return paths, prefixes


def doc_id(raw: dict[str, Any], schema: Schema) -> str:
    flat = flatten(raw)
    v = flat.get(schema.id_field.name)
    if v is None or isinstance(v, dict | list) or str(v).strip() == "":
        raise DocError(f"missing id field {schema.id_field.name!r}")
    s = str(v).strip()
    if len(s) > 512:
        raise DocError("id longer than 512 characters")
    return s


def normalize(raw: dict[str, Any], schema: Schema) -> tuple[str, dict[str, Any], str]:
    """Returns (id, indexed body without vector, text to embed)."""
    did = doc_id(raw, schema)
    flat = flatten(raw)
    f: dict[str, Any] = {}
    paths: dict[str, Any] = {}
    for spec in schema.fields:
        v = flat.get(spec.name)
        if v is None:
            continue
        match spec.role:
            case Role.id:
                f[spec.key] = did
            case Role.title | Role.description | Role.text:
                text = " ".join(_strings(v, None))[:MAX_TEXT]
                if text:
                    f[spec.key] = text
            case Role.facet | Role.keyword:
                vals = [s[:512] for s in _strings(v, spec.separator)]
                if vals:
                    f[spec.key] = vals if spec.multi or len(vals) > 1 else vals[0]
            case Role.currency:
                vals = [s.upper() for s in _strings(v, None)]
                if vals:
                    f[spec.key] = vals[0]
            case Role.numeric | Role.price:
                nums = [n for n in (parse_number(x) for x in _as_list(v)) if n is not None]
                if nums:
                    f[spec.key] = nums if spec.multi else nums[0]
            case Role.boolean:
                b = parse_bool(v[0] if isinstance(v, list) and v else v)
                if b is not None:
                    f[spec.key] = b
            case Role.category:
                full, prefixes = category_paths(v, spec.separator)
                if full:
                    f[spec.key] = full
                    paths[spec.key] = prefixes
            case _:
                pass
    body = {"zz_id": did, "zz_raw": raw, "f": f}
    if paths:
        body["zz_path"] = paths
    etext = embed_text(f, schema)
    body["zz_ehash"] = hashlib.sha1(etext.encode()).hexdigest()
    return did, body, etext


def embed_text(f: dict[str, Any], schema: Schema) -> str:
    """Compact text for the dense retriever: title, category, attributes, then descriptions."""
    parts: list[str] = []
    for spec in schema.by_role(Role.title):
        if spec.key in f:
            parts.append(f[spec.key])
    for spec in schema.by_role(Role.category):
        for p in _as_list(f.get(spec.key)):
            parts.append(p)
    attrs = []
    for spec in schema.by_role(Role.facet, Role.keyword):
        if spec.key in f and spec.searchable:
            vals = _as_list(f[spec.key])[:6]
            attrs.append(f"{spec.name.split('.')[-1].replace('_', ' ')}: {', '.join(vals)}")
    if attrs:
        parts.append("; ".join(attrs[:12]))
    for spec in schema.by_role(Role.description, Role.text):
        if spec.key in f:
            parts.append(f[spec.key])
    return ". ".join(parts)[:EMBED_CHARS]
