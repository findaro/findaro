"""Build OpenSearch query DSL from a SearchRequest + project Schema."""

from __future__ import annotations

from typing import Any

from zerch.errors import ApiError
from zerch.schema.infer import parse_bool, parse_number
from zerch.schema.model import NUMBER_ROLES, TEXT_ROLES, Role, Schema

# <=2 query terms: all must match; longer queries may miss about a third of their terms.
MSM = "2<-34%"
RANGE_OPS = {"gte", "gt", "lte", "lt"}


def _bad(msg: str) -> ApiError:
    return ApiError(400, "invalid_filter", msg)


def build_filters(schema: Schema, filters: dict[str, Any]) -> list[dict[str, Any]]:
    """Filter syntax per field role:
    string fields:  "v" | ["v1", "v2"] (any of) | {"not": "v" | [...]}
    numbers:        12 | [1, 2] | {"gte": 1, "lte": 9}
    category:       "A > B" (matches the path and everything below it) | [...]
    boolean:        true | false
    """
    clauses: list[dict[str, Any]] = []
    for name, cond in filters.items():
        spec = schema.get(name)
        if spec is None:
            raise _bad(f"unknown filter field {name!r}")
        if not spec.filterable:
            raise _bad(f"field {name!r} is not filterable (role {spec.role})")
        if spec.role in NUMBER_ROLES:
            fld = f"f.{spec.key}"
            if isinstance(cond, dict):
                bad = set(cond) - RANGE_OPS
                if bad or not cond:
                    raise _bad(f"numeric filter on {name!r} accepts only {sorted(RANGE_OPS)}")
                rng = {}
                for op, val in cond.items():
                    n = parse_number(val)
                    if n is None:
                        raise _bad(f"{name}.{op} must be a number")
                    rng[op] = n
                clauses.append({"range": {fld: rng}})
            else:
                vals = [parse_number(v) for v in (cond if isinstance(cond, list) else [cond])]
                if any(v is None for v in vals) or not vals:
                    raise _bad(f"filter on {name!r} must be a number, list of numbers or range object")
                clauses.append({"terms": {fld: vals}})
        elif spec.role == Role.boolean:
            b = parse_bool(cond)
            if b is None:
                raise _bad(f"filter on {name!r} must be true or false")
            clauses.append({"term": {f"f.{spec.key}": b}})
        else:
            fld = f"zz_path.{spec.key}.norm" if spec.role == Role.category else f"f.{spec.key}.norm"
            negate = isinstance(cond, dict)
            if negate:
                if set(cond) != {"not"}:
                    raise _bad(f"filter on {name!r}: object form must be {{\"not\": ...}}")
                cond = cond["not"]
            vals = cond if isinstance(cond, list) else [cond]
            if not vals or any(isinstance(v, dict | list) or v is None for v in vals):
                raise _bad(f"filter on {name!r} must be a string or list of strings")
            norm = [_norm_path(str(v)) if spec.role == Role.category else str(v).lower() for v in vals]
            q = {"terms": {fld: norm}}
            clauses.append({"bool": {"must_not": [q]}} if negate else q)
    return clauses


def _norm_path(v: str) -> str:
    parts = [p.strip() for p in v.replace(">>", ">").split(">") if p.strip()]
    return " > ".join(parts).lower()


def search_fields(schema: Schema) -> list[str]:
    out = []
    for f in schema.fields:
        if not f.searchable or not f.weight:
            continue
        path = f"f.{f.key}" if f.role in TEXT_ROLES else f"f.{f.key}.text"
        out.append(f"{path}^{f.weight:g}")
    return out


def lexical_query(schema: Schema, q: str, expansions: list[str] | None = None) -> dict[str, Any]:
    should: list[dict[str, Any]] = []
    fields = search_fields(schema)
    if fields:
        should.append({"multi_match": {"query": q, "type": "cross_fields", "fields": fields, "operator": "or",
                                       "minimum_should_match": MSM, "boost": 2.0}})
    should.append({"match": {"zz_all": {"query": q, "fuzziness": "AUTO", "prefix_length": 1, "max_expansions": 30,
                                        "minimum_should_match": MSM}}})
    should.append({"match": {"zz_all.phon": {"query": q, "minimum_should_match": MSM, "boost": 0.5}}})
    for t in schema.by_role(Role.title):
        should.append({"match_phrase": {f"f.{t.key}": {"query": q, "slop": 2, "boost": 2.0}}})
    idf = schema.id_field
    should.append({"term": {f"f.{idf.key}.norm": {"value": q.strip().lower(), "boost": 20.0}}})
    if expansions:
        # synonyms from the locale pack: any one of them is enough, at a lower weight than the query words
        should.append({"match": {"zz_all": {"query": " ".join(expansions), "boost": 0.6}}})
    return {"bool": {"should": should, "minimum_should_match": 1}}


def plan_filter_clause(schema: Schema, f: Any) -> dict[str, Any] | None:
    """Compile a validated PlanFilter. Non-strict filters also let through documents lacking the field."""
    spec = schema.get(f.field)
    if spec is None:
        return None
    if spec.role in NUMBER_ROLES:
        path = f"f.{spec.key}"
        if f.op == "range":
            clause: dict[str, Any] = {"range": {path: f.value}}
        else:
            clause = {"terms": {path: f.value if isinstance(f.value, list) else [f.value]}}
    elif spec.role == Role.boolean:
        path = f"f.{spec.key}"
        clause = {"term": {path: f.value}}
    elif spec.role == Role.category:
        path = f"zz_path.{spec.key}"
        vals = f.value if isinstance(f.value, list) else [f.value]
        clause = {"terms": {f"{path}.norm": [_norm_path(str(v)) for v in vals]}}
    else:
        path = f"f.{spec.key}"
        vals = f.value if isinstance(f.value, list) else [f.value]
        clause = {"terms": {f"{path}.norm": [str(v).lower() for v in vals]}}
    if f.strict:
        return clause
    return {"bool": {"should": [clause, {"bool": {"must_not": [{"exists": {"field": path}}]}}],
                     "minimum_should_match": 1}}


def docvalue_path(schema: Schema, field: str) -> str | None:
    spec = schema.get(field)
    if spec is None or spec.role in TEXT_ROLES:
        return None
    return f"zz_path.{spec.key}" if spec.role == Role.category else f"f.{spec.key}"


def knn_clause(vec: list[float], k: int, filters: list[dict[str, Any]]) -> dict[str, Any]:
    body: dict[str, Any] = {"vector": vec, "k": k}
    if filters:
        body["filter"] = {"bool": {"filter": filters}}
    return {"knn": {"zz_vec": body}}


def accept_vector_hits(hits: list[dict[str, Any]], min_score: float, rel_cutoff: float) -> list[dict[str, Any]]:
    if not hits:
        return []
    floor = max(min_score, hits[0]["_score"] - rel_cutoff) if rel_cutoff > 0 else min_score
    return [h for h in hits if h["_score"] >= floor]


def union_query(lexical: dict[str, Any], vector_ids: list[str], filters: list[dict[str, Any]]) -> dict[str, Any]:
    """Match set = lexical matches + accepted vector candidates. Drives totals, facets and sorted results."""
    should: list[dict[str, Any]] = [lexical]
    if vector_ids:
        should.append({"ids": {"values": vector_ids}})
    return {"bool": {"filter": filters, "should": should, "minimum_should_match": 1}}


def facet_aggs(schema: Schema, names: list[str] | None, size: int) -> dict[str, Any]:
    specs = [f for f in schema.fields if f.facet] if names is None else []
    if names is not None:
        for n in names:
            spec = schema.get(n)
            if spec is None or not spec.filterable or spec.role in TEXT_ROLES:
                raise ApiError(400, "invalid_facet", f"cannot facet on {n!r}")
            specs.append(spec)
    aggs: dict[str, Any] = {}
    for i, f in enumerate(specs):
        key = f"a{i}"
        if f.role in NUMBER_ROLES:
            aggs[key] = {"stats": {"field": f"f.{f.key}"}}
        elif f.role == Role.category:
            aggs[key] = {"terms": {"field": f"zz_path.{f.key}", "size": size * 3}}
        else:
            aggs[key] = {"terms": {"field": f"f.{f.key}", "size": size}}
    return aggs


def read_facets(schema: Schema, names: list[str] | None, aggs: dict[str, Any] | None) -> dict[str, Any]:
    if not aggs:
        return {}
    specs = [f for f in schema.fields if f.facet] if names is None else [schema.get(n) for n in names]
    out: dict[str, Any] = {}
    for i, f in enumerate(specs):
        a = aggs.get(f"a{i}")
        if a is None or f is None:
            continue
        if f.role in NUMBER_ROLES:
            out[f.name] = {"type": "stats", "min": a.get("min"), "max": a.get("max"), "count": a.get("count", 0)}
        else:
            vals = []
            for b in a.get("buckets", []):
                v = b.get("key_as_string", b["key"]) if f.role == Role.boolean else b["key"]
                vals.append({"value": v, "count": b["doc_count"]})
            out[f.name] = {"type": "category" if f.role == Role.category else "terms", "values": vals}
    return out


def sort_clause(schema: Schema, sort: list[Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for s in sort:
        if s.field in ("_score", "relevance"):
            out.append({"_score": {"order": s.order if s.order else "desc"}})
            continue
        spec = schema.get(s.field)
        if spec is None or not spec.sortable:
            raise ApiError(400, "invalid_sort", f"cannot sort by {s.field!r}")
        out.append({f"f.{spec.key}": {"order": s.order, "missing": "_last",
                                      "unmapped_type": "double" if spec.role in NUMBER_ROLES else "keyword"}})
    out.append({"_score": {"order": "desc"}})
    out.append({"zz_id": {"order": "asc"}})
    return out


def highlight(schema: Schema, q: str, expansions: list[str] | None = None) -> dict[str, Any] | None:
    fields: dict[str, Any] = {}
    for f in schema.by_role(Role.title):
        fields[f"f.{f.key}"] = {"number_of_fragments": 0}
    for f in schema.by_role(Role.description):
        fields[f"f.{f.key}"] = {"fragment_size": 160, "number_of_fragments": 1, "no_match_size": 0}
    if not fields:
        return None
    return {
        "pre_tags": ["<em>"],
        "post_tags": ["</em>"],
        "require_field_match": False,
        "fields": fields,
        "highlight_query": {"multi_match": {"query": " ".join([q, *(expansions or [])]), "fields": list(fields),
                                            "fuzziness": "AUTO", "prefix_length": 1}},
    }


def key_to_name(schema: Schema) -> dict[str, str]:
    return {f"f.{f.key}": f.name for f in schema.fields}
