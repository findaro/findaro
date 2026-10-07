"""Hybrid search: BM25 + k-NN retrieved in one msearch, fused with Reciprocal Rank Fusion.

With `understand` on (M2), the query is first turned into a QueryPlan: price/attribute filters, soft
sort, boosts and a cleaned semantic text that drives both retrievers. See zerch.understand.
"""

from __future__ import annotations

import asyncio
import hashlib
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import orjson

from zerch.errors import ApiError
from zerch.index.ops import alias_name
from zerch.schema.model import Role, Schema
from zerch.search import query as Q
from zerch.search.models import Chip, Hit, RelaxedFilter, SearchRequest, SearchResponse, Understood
from zerch.state import State
from zerch.understand.plan import PlanFilter, QueryPlan, Relaxation
from zerch.understand.rules import describe_price
from zerch.understand.service import cached_dictionary, understand

_SRC = ["zz_raw"]
CURRENCY_SYMBOLS = {"INR": "₹", "USD": "$", "EUR": "€", "GBP": "£", "JPY": "¥", "AUD": "A$", "CAD": "C$",
                    "SGD": "S$", "AED": "AED ", "CNY": "¥"}


class _LRU(OrderedDict):
    def __init__(self, maxsize: int):
        super().__init__()
        self.maxsize = maxsize

    def get_(self, k: str) -> Any:
        if k in self:
            self.move_to_end(k)
            return self[k]
        return None

    def put(self, k: str, v: Any) -> None:
        self[k] = v
        self.move_to_end(k)
        while len(self) > self.maxsize:
            self.popitem(last=False)


_query_vecs = _LRU(4096)


async def embed_query(state: State, q: str) -> list[float]:
    key = f"emb:{state.embedder.name}:{hashlib.sha1(q.encode()).hexdigest()}"
    v = _query_vecs.get_(key)
    if v is not None:
        return v
    raw = await state.redis.get(key)
    if raw:
        vec = np.frombuffer(raw, dtype=np.float32).tolist()
    else:
        arr = (await asyncio.to_thread(state.embedder.embed_queries, [q]))[0]
        await state.redis.set(key, arr.astype(np.float32).tobytes(), ex=86_400)
        vec = arr.tolist()
    _query_vecs.put(key, vec)
    return vec


def rrf(lists: list[list[dict[str, Any]]], k: int) -> list[tuple[str, float, dict[str, Any]]]:
    """Reciprocal Rank Fusion. Returns (id, score, best hit) ordered by fused score."""
    scores: dict[str, float] = {}
    hits: dict[str, dict[str, Any]] = {}
    for lst in lists:
        for rank, h in enumerate(lst):
            did = h["_id"]
            scores[did] = scores.get(did, 0.0) + 1.0 / (k + rank + 1)
            hits.setdefault(did, h)
    order = sorted(scores, key=lambda d: (-scores[d], d))
    return [(d, scores[d], hits[d]) for d in order]


def _hit(h: dict[str, Any], score: float, names: dict[str, str]) -> Hit:
    hl = None
    if h.get("highlight"):
        hl = {names.get(k, k): " … ".join(v) for k, v in h["highlight"].items() if v}
    return Hit(id=h["_id"], score=round(score, 6), document=h["_source"]["zz_raw"], highlights=hl or None)


async def _msearch(state: State, index: str, bodies: list[dict[str, Any]]) -> list[dict[str, Any]]:
    lines = []
    for b in bodies:
        lines.append(b"{}")
        lines.append(orjson.dumps(b))
    r = await state.os.msearch(index=index, body=b"\n".join(lines) + b"\n")
    for sub in r["responses"]:
        if "error" in sub:
            raise RuntimeError(f"opensearch error: {sub['error']}")
    return r["responses"]


def _cache_key(pid: str, project: dict[str, Any], req: SearchRequest) -> str:
    body = orjson.dumps(req.model_dump(mode="json"), option=orjson.OPT_SORT_KEYS)
    h = hashlib.sha1(body).hexdigest()
    return f"srch:{pid}:{project['data_version']}:{project['schema_version']}:{h}"


# --- re-ranking ------------------------------------------------------------------------------------------

@dataclass
class _Signal:
    path: str  # docvalue field
    values: set[str]  # lowercased values that count as a match
    weight: float


@dataclass
class _Rerank:
    signals: list[_Signal] = field(default_factory=list)
    price_path: str | None = None
    price_order: str | None = None  # soft sort direction

    @property
    def fields(self) -> list[str]:
        out = {s.path for s in self.signals}
        if self.price_path:
            out.add(self.price_path)
        return sorted(out)


def _rerank_spec(schema: Schema, plan: QueryPlan | None, soft_sort: bool) -> _Rerank:
    rr = _Rerank()
    if plan is None:
        return rr

    def add(fld: str, value: Any, weight: float) -> None:
        path = Q.docvalue_path(schema, fld)
        if path is None:
            return
        vals = value if isinstance(value, list) else [value]
        rr.signals.append(_Signal(path, {str(v).lower() for v in vals}, weight))

    for b in plan.boosts:
        add(b.field, b.value, b.weight)
    for f in plan.filters:
        if not f.strict and f.op in ("eq", "in"):
            add(f.field, f.value, 0.5)  # documents that actually have the value beat ones lacking the field
    if soft_sort and plan.sort is not None:
        rr.price_path = Q.docvalue_path(schema, plan.sort.field)
        rr.price_order = plan.sort.order
    return rr


def _apply_rerank(fused: list[tuple[str, float, dict[str, Any]]], rr: _Rerank,
                  unit: float) -> list[tuple[str, float, dict[str, Any]]]:
    if not rr.signals and not rr.price_path:
        return fused
    bonus = {d: 0.0 for d, _, _ in fused}
    for d, _, h in fused:
        fv = h.get("fields") or {}
        for sig in rr.signals:
            if any(str(v).lower() in sig.values for v in fv.get(sig.path, [])):
                bonus[d] += sig.weight * unit
    if rr.price_path:
        head = [(d, h) for d, _, h in fused[:60]]
        prices = sorted(p for _, h in head for p in (h.get("fields") or {}).get(rr.price_path, [])[:1])
        if len(prices) >= 3:
            t1, t2 = prices[len(prices) // 3], prices[2 * len(prices) // 3]
            for d, h in head:
                p = (h.get("fields") or {}).get(rr.price_path, [None])[0]
                if p is None:
                    continue
                if rr.price_order == "asc":
                    bonus[d] += unit * (2.0 if p <= t1 else 1.0 if p <= t2 else 0.0)
                else:
                    bonus[d] += unit * (2.0 if p >= t2 else 1.0 if p >= t1 else 0.0)
    out = [(d, sc + bonus[d], h) for d, sc, h in fused]
    out.sort(key=lambda x: (-x[1], x[0]))
    return out


# --- understood (UI-facing view of the plan) -------------------------------------------------------------

def _symbol(schema: Schema, project_dict: Any) -> str:
    cur = getattr(project_dict, "currency", None) if project_dict is not None else None
    return CURRENCY_SYMBOLS.get(str(cur).upper(), f"{cur} " if cur else "")


def _value_label(v: Any) -> str:
    if isinstance(v, list):
        return " or ".join(_value_label(x) for x in v)
    s = str(v)
    return s.split(" > ")[-1] if " > " in s else s


def _filter_label(f: PlanFilter, schema: Schema, symbol: str) -> str:
    spec = schema.get(f.field)
    if spec is not None and spec.role == Role.price and f.op == "range":
        return describe_price(f, symbol)
    if f.op == "range" and isinstance(f.value, dict):
        lo, hi = f.value.get("gte"), f.value.get("lte")
        name = f.field.replace("_", " ")
        if lo is not None and lo == hi:
            return f"{name}: {lo:g}"
        return f"{name} {'≤ ' + format(hi, 'g') if hi is not None else '≥ ' + format(lo, 'g')}"
    return _value_label(f.value)


def build_understood(query: str, plan: QueryPlan | None, schema: Schema, symbol: str, quality: str,
                     relaxations: list[Relaxation], semantic: str) -> Understood:
    if plan is None:
        return Understood(query=query, semantic_text=semantic, match_quality=quality, source="off")
    chips: list[Chip] = []
    for f in plan.filters:
        chips.append(Chip(label=_filter_label(f, schema, symbol), kind="filter", field=f.field, op=f.op,
                          value=f.value, source=f.text or "", confidence=round(f.confidence, 2)))
    seen = set()
    for b in plan.boosts:
        label = _value_label(b.value)
        if (b.field, label) in seen or b.origin == "fuzzy":
            continue
        seen.add((b.field, label))
        chips.append(Chip(label=label, kind="boost", field=b.field, op="in" if isinstance(b.value, list) else "eq",
                          value=b.value, source=b.text or "", confidence=0.6))
    if plan.sort is not None:
        chips.append(Chip(label="Lower prices first" if plan.sort.order == "asc" else "Higher prices first",
                          kind="sort", field=plan.sort.field, op=plan.sort.order, value=None,
                          source=plan.sort.text or "", confidence=0.8))
    relaxed = [RelaxedFilter(field=r.field, value=r.value, reason=r.reason,
                             label=_filter_label(PlanFilter(field=r.field, op="range" if isinstance(r.value, dict)
                                                            else "eq", value=r.value), schema, symbol))
               for r in relaxations]
    return Understood(query=query, semantic_text=semantic, chips=chips, relaxations=relaxed, match_quality=quality,
                      source=plan.source)


# --- search ----------------------------------------------------------------------------------------------

@dataclass
class _Result:
    hits: list[Hit]
    total: int
    aggs: dict[str, Any] | None
    lexical_hits: int = 0
    vector_top: float | None = None
    timings: dict[str, float] = field(default_factory=dict)


async def search(state: State, pid: str, project: dict[str, Any], schema: Schema | None, req: SearchRequest,
                 use_cache: bool = True, use_plan_cache: bool = True) -> SearchResponse:
    t0 = time.perf_counter()
    s = state.settings
    ttl = s.search_cache_ttl if use_cache else 0
    ckey = _cache_key(pid, project, req) if ttl else None
    if ckey:
        cached = await state.redis.get(ckey)
        if cached:
            resp = SearchResponse.model_validate_json(cached)
            resp.cached = True
            resp.took_ms = round((time.perf_counter() - t0) * 1000, 2)
            return resp

    if schema is None:  # nothing ingested yet
        return SearchResponse(query=req.query, total=0, page=req.page, size=req.size, hits=[], facets={},
                              took_ms=round((time.perf_counter() - t0) * 1000, 2),
                              understood=Understood(query=req.query, semantic_text=req.query, match_quality="none"))

    explicit = Q.build_filters(schema, req.filters)
    aggs = Q.facet_aggs(schema, req.facets, req.facet_size)
    hard_sort = Q.sort_clause(schema, req.sort) if req.sort else None
    offset = (req.page - 1) * req.size
    if offset + req.size > s.max_result_window:
        raise ApiError(400, "page_too_deep", f"page * size must be <= {s.max_result_window}")
    q = req.query.strip()

    plan: QueryPlan | None = None
    info: dict[str, Any] = {}
    t_u = time.perf_counter()
    if req.understand and q:
        plan, info = await understand(state, pid, project, schema, q, use_plan_cache)
        # Explicit filters win; the words behind an overridden inferred filter leave the search text too
        # ("black kurta" + filters={color: White} searches for "kurta").
        overridden = [f for f in plan.filters if f.field in req.filters]
        plan.filters = [f for f in plan.filters if f.field not in req.filters]
        drop = {w for f in overridden for w in (f.text or "").split()}
        if drop:
            kept = [w for w in plan.semantic_text.split() if w not in drop]
            plan.semantic_text = " ".join(kept)
            plan.keywords = kept
    understand_ms = round((time.perf_counter() - t_u) * 1000, 2)

    relaxations: list[Relaxation] = []
    while True:
        result = await _retrieve(state, pid, schema, req, plan, explicit, aggs, hard_sort, offset)
        if result.total == 0 and plan is not None and plan.filters and not relaxations:
            weakest = min(plan.filters, key=lambda f: (f.confidence, f.strict))
            plan.filters.remove(weakest)
            relaxations.append(Relaxation(field=weakest.field, value=weakest.value,
                                          reason="no results with this filter"))
            continue
        break
    if plan is not None:
        plan.relaxations = relaxations

    # Backfill: inferred attribute filters ("red", "silk") can leave a short page. Show the exact matches
    # first, then fill the page from the same query without those attribute filters (price stays strict).
    close: list[str] = []
    soft = [f for f in plan.filters if not f.strict] if plan is not None else []
    if soft and not req.sort and offset == 0 and 0 < result.total < req.size:  # first page only
        loose = plan.model_copy(update={"filters": [f for f in plan.filters if f.strict]})
        wide = await _retrieve(state, pid, schema, req, loose, explicit, aggs, hard_sort, 0)
        seen = {h.id for h in result.hits}
        extra = [h for h in wide.hits if h.id not in seen][: req.size - len(result.hits)]
        if extra:
            close = [h.id for h in extra]
            result.hits = result.hits + extra
            result.total = max(result.total, wide.total)
            for k, v in wide.timings.items():
                result.timings[f"backfill_{k}"] = v

    semantic = plan.semantic_text if plan is not None else q
    quality = "good"
    if plan is not None and semantic:
        if result.lexical_hits == 0:
            top = result.vector_top if result.vector_top is not None else 0.0
            quality = "weak" if top >= s.match_floor else "none"
        elif relaxations:
            quality = "weak"
    if quality == "none":
        result = _Result(hits=[], total=0, aggs=None, lexical_hits=0, vector_top=result.vector_top,
                         timings=result.timings)

    understood = build_understood(req.query, plan, schema, _symbol(schema, cached_dictionary(pid)), quality,
                                  relaxations, semantic)
    understood.close_matches = close
    debug = None
    if req.debug:
        debug = {
            "plan": plan.model_dump(mode="json") if plan is not None else None,
            "llm": info,
            "timings_ms": {"understand": understand_ms, **result.timings,
                           "total": round((time.perf_counter() - t0) * 1000, 2)},
            "lexical_hits": result.lexical_hits,
            "vector_top_score": result.vector_top,
        }
    resp = SearchResponse(query=req.query, total=result.total, page=req.page, size=req.size, hits=result.hits,
                          facets=Q.read_facets(schema, req.facets, result.aggs), understood=understood, debug=debug,
                          took_ms=round((time.perf_counter() - t0) * 1000, 2))
    if ckey:
        await state.redis.set(ckey, resp.model_dump_json(), ex=ttl)
    return resp


async def _retrieve(state: State, pid: str, schema: Schema, req: SearchRequest, plan: QueryPlan | None,
                    explicit: list[dict[str, Any]], aggs: dict[str, Any], hard_sort: list[dict[str, Any]] | None,
                    offset: int) -> _Result:
    s = state.settings
    index = alias_name(s.index_prefix, pid)
    names = Q.key_to_name(schema)
    timings: dict[str, float] = {}
    filters = list(explicit)
    if plan is not None:
        for f in plan.filters:
            c = Q.plan_filter_clause(schema, f)
            if c is not None:
                filters.append(c)
    text = plan.semantic_text.strip() if plan is not None else req.query.strip()
    expansions = plan.expansions if plan is not None else []
    soft = plan is not None and plan.sort is not None and not req.sort

    if not text:  # browse: filters only
        sort = hard_sort
        if sort is None and soft:
            spec = schema.get(plan.sort.field)
            sort = [{f"f.{spec.key}": {"order": plan.sort.order, "missing": "_last"}}, {"zz_id": {"order": "asc"}}]
        body: dict[str, Any] = {
            "query": {"bool": {"filter": filters, "must": [{"match_all": {}}]}},
            "from": offset, "size": req.size, "_source": _SRC, "aggs": aggs, "track_total_hits": True,
            "sort": sort or [{"zz_id": {"order": "asc"}}],
        }
        t = time.perf_counter()
        r = await state.os.search(index=index, body=body)
        timings["retrieve"] = round((time.perf_counter() - t) * 1000, 2)
        total = r["hits"]["total"]["value"]
        return _Result(hits=[_hit(h, h.get("_score") or 0.0, names) for h in r["hits"]["hits"]], total=total,
                       aggs=r.get("aggregations"), lexical_hits=total, timings=timings)

    t = time.perf_counter()
    vec_text = " ".join([text, *expansions])
    vec = await embed_query(state, vec_text)
    timings["embed"] = round((time.perf_counter() - t) * 1000, 2)
    lexical = Q.lexical_query(schema, text, expansions)
    window = min(s.max_result_window, max(s.rank_window, offset + req.size))
    knn_body = {"query": Q.knn_clause(vec, max(window, s.knn_k), filters), "size": window, "track_total_hits": False}
    hl = Q.highlight(schema, text, expansions) if req.highlight else None

    if hard_sort:
        t = time.perf_counter()
        knn_r = await state.os.search(index=index, body={**knn_body, "_source": False})
        vec_hits = Q.accept_vector_hits(knn_r["hits"]["hits"], s.knn_min_score, s.knn_relative_cutoff)
        body = {"query": Q.union_query(lexical, [h["_id"] for h in vec_hits], filters), "from": offset,
                "size": req.size, "_source": _SRC, "aggs": aggs, "track_total_hits": True, "sort": hard_sort}
        if hl:
            body["highlight"] = hl
        lex_count = {"query": {"bool": {"filter": filters, "must": [lexical]}}, "size": 0, "track_total_hits": 1}
        r, lc = await _msearch(state, index, [body, lex_count])
        timings["retrieve"] = round((time.perf_counter() - t) * 1000, 2)
        return _Result(hits=[_hit(h, h.get("_score") or 0.0, names) for h in r["hits"]["hits"]],
                       total=r["hits"]["total"]["value"], aggs=r.get("aggregations"),
                       lexical_hits=lc["hits"]["total"]["value"],
                       vector_top=knn_r["hits"]["hits"][0]["_score"] if knn_r["hits"]["hits"] else None,
                       timings=timings)

    # Pass 1: rank both retrievers over the window (ids + the few doc values re-ranking needs).
    rr = _rerank_spec(schema, plan, soft)
    extra: dict[str, Any] = {"docvalue_fields": rr.fields} if rr.fields else {}
    lex_body = {"query": {"bool": {"filter": filters, "must": [lexical]}}, "size": window, "_source": False,
                "track_total_hits": False, **extra}
    t = time.perf_counter()
    lex_r, knn_r = await _msearch(state, index, [lex_body, {**knn_body, "_source": False, **extra}])
    timings["retrieve"] = round((time.perf_counter() - t) * 1000, 2)
    knn_hits = knn_r["hits"]["hits"]
    vec_hits = Q.accept_vector_hits(knn_hits, s.knn_min_score, s.knn_relative_cutoff)
    fused = rrf([lex_r["hits"]["hits"], vec_hits], s.rrf_k)
    fused = _apply_rerank(fused, rr, 1.0 / (s.rrf_k + 1))
    page = fused[offset : offset + req.size]
    page_ids = [d for d, _, _ in page]

    # Pass 2: totals/facets over the match set + documents/highlights for the page only.
    union_body = {"query": Q.union_query(lexical, [h["_id"] for h in vec_hits], filters), "size": 0,
                  "aggs": aggs, "track_total_hits": True}
    docs_body: dict[str, Any] = {"query": {"ids": {"values": page_ids}}, "size": len(page_ids), "_source": _SRC}
    if hl:
        docs_body["highlight"] = hl
    t = time.perf_counter()
    uni_r, docs_r = await _msearch(state, index, [union_body, docs_body])
    timings["fetch"] = round((time.perf_counter() - t) * 1000, 2)
    by_id = {h["_id"]: h for h in docs_r["hits"]["hits"]}
    return _Result(hits=[_hit(by_id[d], sc, names) for d, sc, _ in page if d in by_id],
                   total=uni_r["hits"]["total"]["value"], aggs=uni_r.get("aggregations"),
                   lexical_hits=len(lex_r["hits"]["hits"]),
                   vector_top=knn_hits[0]["_score"] if knn_hits else None, timings=timings)

