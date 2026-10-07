"""Hybrid search: BM25 + k-NN retrieved in one msearch, fused with Reciprocal Rank Fusion."""

from __future__ import annotations

import asyncio
import hashlib
import time
from collections import OrderedDict
from typing import Any

import numpy as np
import orjson

from zerch.index.ops import alias_name
from zerch.schema.model import Schema
from zerch.search import query as Q
from zerch.search.models import Hit, SearchRequest, SearchResponse
from zerch.state import State

_SRC = ["zz_raw"]


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
            # Prefer the lexical hit (it carries highlights); lists are passed lexical-first.
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


async def search(state: State, pid: str, project: dict[str, Any], schema: Schema | None, req: SearchRequest,
                 use_cache: bool = True) -> SearchResponse:
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
                              took_ms=round((time.perf_counter() - t0) * 1000, 2))

    filters = Q.build_filters(schema, req.filters)
    aggs = Q.facet_aggs(schema, req.facets, req.facet_size)
    sort = Q.sort_clause(schema, req.sort) if req.sort else None
    names = Q.key_to_name(schema)
    offset = (req.page - 1) * req.size
    if offset + req.size > s.max_result_window:
        from zerch.errors import ApiError

        raise ApiError(400, "page_too_deep", f"page * size must be <= {s.max_result_window}")
    index = alias_name(s.index_prefix, pid)
    q = req.query.strip()

    if not q:
        body: dict[str, Any] = {
            "query": {"bool": {"filter": filters, "must": [{"match_all": {}}]}},
            "from": offset, "size": req.size, "_source": _SRC, "aggs": aggs, "track_total_hits": True,
            "sort": sort or [{"zz_id": {"order": "asc"}}],
        }
        r = await state.os.search(index=index, body=body)
        hits = [_hit(h, h.get("_score") or 0.0, names) for h in r["hits"]["hits"]]
        total = r["hits"]["total"]["value"]
        facets = Q.read_facets(schema, req.facets, r.get("aggregations"))
    else:
        vec = await embed_query(state, q)
        lexical = Q.lexical_query(schema, q)
        window = min(s.max_result_window, max(s.rank_window, offset + req.size))
        knn_body = {"query": Q.knn_clause(vec, max(window, s.knn_k), filters), "size": window,
                    "track_total_hits": False}
        hl = Q.highlight(schema, q) if req.highlight else None
        if sort:
            knn_r = await state.os.search(index=index, body={**knn_body, "_source": False})
            vec_hits = Q.accept_vector_hits(knn_r["hits"]["hits"], s.knn_min_score, s.knn_relative_cutoff)
            body = {"query": Q.union_query(lexical, [h["_id"] for h in vec_hits], filters), "from": offset,
                    "size": req.size, "_source": _SRC, "aggs": aggs, "track_total_hits": True, "sort": sort}
            if hl:
                body["highlight"] = hl
            r = await state.os.search(index=index, body=body)
            hits = [_hit(h, h.get("_score") or 0.0, names) for h in r["hits"]["hits"]]
            total = r["hits"]["total"]["value"]
            facets = Q.read_facets(schema, req.facets, r.get("aggregations"))
        else:
            # Pass 1: rank both retrievers over the window, ids only (cheap).
            lex_body = {"query": {"bool": {"filter": filters, "must": [lexical]}}, "size": window,
                        "_source": False, "track_total_hits": False}
            lex_r, knn_r = await _msearch(state, index, [lex_body, {**knn_body, "_source": False}])
            vec_hits = Q.accept_vector_hits(knn_r["hits"]["hits"], s.knn_min_score, s.knn_relative_cutoff)
            fused = rrf([lex_r["hits"]["hits"], vec_hits], s.rrf_k)
            page = fused[offset : offset + req.size]
            page_ids = [d for d, _, _ in page]
            # Pass 2: totals/facets over the match set + documents/highlights for the page only.
            union_body = {"query": Q.union_query(lexical, [h["_id"] for h in vec_hits], filters), "size": 0,
                          "aggs": aggs, "track_total_hits": True}
            docs_body: dict[str, Any] = {"query": {"ids": {"values": page_ids}}, "size": len(page_ids),
                                         "_source": _SRC}
            if hl:
                docs_body["highlight"] = hl
            uni_r, docs_r = await _msearch(state, index, [union_body, docs_body])
            by_id = {h["_id"]: h for h in docs_r["hits"]["hits"]}
            hits = [_hit(by_id[d], sc, names) for d, sc, _ in page if d in by_id]
            total = uni_r["hits"]["total"]["value"]
            facets = Q.read_facets(schema, req.facets, uni_r.get("aggregations"))

    resp = SearchResponse(query=req.query, total=total, page=req.page, size=req.size, hits=hits, facets=facets,
                          took_ms=round((time.perf_counter() - t0) * 1000, 2))
    if ckey:
        await state.redis.set(ckey, resp.model_dump_json(), ex=ttl)
    return resp
