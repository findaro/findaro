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
from zerch.search.models import (
    Chip,
    Display,
    Hit,
    Pill,
    PillValue,
    RelaxedFilter,
    SearchRequest,
    SearchResponse,
    Understood,
)
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
    if f.op == "not":
        return f"Not {_value_label(f.value)}"
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
    from zerch.understand.patch import remove_ops

    chips: list[Chip] = []
    for f in plan.filters:
        chips.append(Chip(label=_filter_label(f, schema, symbol), kind="filter", field=f.field, op=f.op,
                          value=f.value, source=f.text or "", confidence=round(f.confidence, 2),
                          remove=remove_ops("filter", f.field, f.op, f.value, schema)))
    seen = set()
    for b in plan.boosts:
        label = _value_label(b.value)
        if (b.field, label) in seen or b.origin == "fuzzy":
            continue
        seen.add((b.field, label))
        op = "in" if isinstance(b.value, list) else "eq"
        chips.append(Chip(label=label, kind="boost", field=b.field, op=op, value=b.value, source=b.text or "",
                          confidence=0.6, remove=remove_ops("boost", b.field, op, b.value, schema)))
    if plan.sort is not None:
        chips.append(Chip(label="Lower prices first" if plan.sort.order == "asc" else "Higher prices first",
                          kind="sort", field=plan.sort.field, op=plan.sort.order, value=None,
                          source=plan.sort.text or "", confidence=0.8,
                          remove=remove_ops("sort", plan.sort.field, plan.sort.order, None, schema)))
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
    focus: str | None = None  # category path the lexical matches agree on (filler/backfill stay inside it)


async def search(state: State, pid: str, project: dict[str, Any], schema: Schema | None, req: SearchRequest,
                 use_cache: bool = True, use_plan_cache: bool = True,
                 plan_override: QueryPlan | None = None) -> SearchResponse:
    """Run a search. `plan_override` (chat turns) skips query understanding and executes that plan."""
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
    if plan_override is not None:
        plan, info = plan_override.model_copy(deep=True), {"llm": "not_needed"}
    elif req.understand and q:
        plan, info = await understand(state, pid, project, schema, q, use_plan_cache, allow_llm=req.llm)
        # Explicit filters win; the words behind an overridden inferred filter leave the search text too
        # ("black kurta" + filters={color: White} searches for "kurta").
        overridden = [f for f in plan.filters if f.field in req.filters]
        plan.filters = [f for f in plan.filters if f.field not in req.filters]
        drop = {w for f in overridden for w in (f.text or "").split()}
        if drop:
            kept = [w for w in plan.semantic_text.split() if w not in drop]
            plan.semantic_text = " ".join(kept)
            plan.keywords = kept
    if req.patch:
        from zerch.understand.patch import apply_patch
        from zerch.understand.service import get_dictionary

        if plan is None:
            plan = QueryPlan(query=q, semantic_text=q, keywords=q.split())
        plan = apply_patch(plan, req.patch, schema, await get_dictionary(state, pid, project, schema))
    if hard_sort is None and plan is not None and plan.sort is not None and plan.sort.mode == "hard":
        from zerch.search.models import SortItem

        hard_sort = Q.sort_clause(schema, [SortItem(field=plan.sort.field, order=plan.sort.order)])
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

    close: list[str] = []
    if plan is not None and not req.sort and offset == 0 and 0 < result.total < req.size:
        close = await _backfill(state, pid, schema, req, plan, explicit, aggs, result)

    semantic = plan.semantic_text if plan is not None else q
    quality = "good"
    if plan is not None and semantic:
        quality = match_quality(schema, plan, result, s.match_floor, cached_dictionary(pid))
        if quality == "good" and relaxations:
            quality = "weak"
    if quality == "none":
        result = _Result(hits=[], total=0, aggs=None, lexical_hits=0, vector_top=result.vector_top,
                         timings=result.timings)
        close = []

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
            "focus_category": result.focus,
        }
    facets = Q.read_facets(schema, req.facets, result.aggs)
    resp = SearchResponse(query=req.query, total=result.total, page=req.page, size=req.size, hits=result.hits,
                          facets=facets, understood=understood, debug=debug,
                          pills=facet_pills(schema, plan, facets, result.total),
                          display=display_fields(schema, getattr(cached_dictionary(pid), "currency", None)),
                          took_ms=round((time.perf_counter() - t0) * 1000, 2))
    if ckey:
        await state.redis.set(ckey, resp.model_dump_json(), ex=ttl)
    return resp


def display_fields(schema: Schema, currency: str | None) -> Display:
    from zerch.understand.plan import primary_price_field

    def first(role: Role) -> str | None:
        return next((f.name for f in schema.by_role(role)), None)

    price = primary_price_field(schema)
    other = next((f.name for f in schema.by_role(Role.price) if f.name != price), None)
    nums = [f.name for f in schema.by_role(Role.numeric)]
    rating = next((n for n in nums if "rating" in n.lower() and "count" not in n.lower()), None)
    count = next((n for n in nums if "rating" in n.lower() and "count" in n.lower()), None)
    stock = next((f.name for f in schema.by_role(Role.boolean) if "stock" in f.name.lower()), None)
    return Display(id=schema.id_field.name, title=first(Role.title), price=price, compare_at_price=other,
                   currency=currency, image=first(Role.image_url), url=first(Role.url), rating=rating,
                   rating_count=count, in_stock=stock)


def facet_pills(schema: Schema, plan: QueryPlan | None, facets: dict[str, Any], total: int,
                max_fields: int = 3, max_values: int = 5) -> list[Pill]:
    """Attribute choices that split the current results usefully (spread out, covering most results)."""
    import math

    from zerch.understand.patch import PatchOp

    taken = {f.field for f in plan.filters} if plan is not None else set()
    scored = []
    for spec in schema.fields:
        if spec.role != Role.facet or spec.multi or spec.name in taken:
            continue
        fv = facets.get(spec.name)
        if not fv or fv.get("type") != "terms":
            continue
        vals = [v for v in fv.get("values", []) if v["count"] > 0]
        counts = [v["count"] for v in vals]
        if len(vals) < 2 or not total or sum(counts) < 0.5 * total:
            continue
        n = sum(counts)
        h = -sum(c / n * math.log(c / n) for c in counts) / math.log(len(counts))
        scored.append((h * min(1.0, n / total), spec, vals))
    pills = []
    for _, spec, vals in sorted(scored, key=lambda x: -x[0])[:max_fields]:
        pills.append(Pill(field=spec.name, label=spec.name.replace("_", " ").capitalize(), values=[
            PillValue(value=v["value"], label=str(v["value"]), count=v["count"],
                      patch=[PatchOp(op="add_filter", field=spec.name, value=v["value"])])
            for v in sorted(vals, key=lambda v: -v["count"])[:max_values]]))
    return pills


def _category_path(schema: Schema) -> tuple[Any, str] | tuple[None, None]:
    cats = schema.by_role(Role.category)
    return (cats[0], f"zz_path.{cats[0].key}") if cats else (None, None)


def focus_category(lex_hits: list[dict[str, Any]], path: str, plan: QueryPlan | None) -> str | None:
    """Deepest category prefix holding >= 60% of the top lexical matches' score (never a bare root level).

    Score-weighted so a weak fuzzy match can't outvote a strong exact one. Falls back to a single category
    the rules matched in the query when there are no lexical matches."""
    top = [h for h in lex_hits[:10] if (h.get("fields") or {}).get(path)]
    if top:
        counts: dict[str, float] = {}
        total = sum(h.get("_score") or 1.0 for h in top)
        for h in top:
            for p in h["fields"][path]:
                counts[p] = counts.get(p, 0.0) + (h.get("_score") or 1.0)
        ok = [p for p, c in counts.items() if c >= 0.6 * total and " > " in p]
        if ok:
            return max(ok, key=lambda p: (p.count(" > "), counts[p]))
        return None
    if plan is not None:
        cats = [b.value for b in plan.boosts if b.origin == "category" and isinstance(b.value, str)]
        if len(set(cats)) == 1 and " > " in cats[0]:
            return cats[0]
    return None


_WORD = __import__("re").compile(r"[a-z0-9]+")


def _coverage(keywords: list[str], hits: list[Hit], schema: Schema, expansions: list[str] | None = None,
              missing: list[str] | None = None) -> float:
    """Best fraction of query keywords found in one of the top results' text (titles, categories, values).

    A keyword also counts as found when one of the plan's synonym expansions is. Words missing from the best
    result are appended to `missing`."""
    from zerch.understand.dictionary import levenshtein
    from zerch.understand.lexicon import fold, singular

    words = [singular(w) for w in keywords if w.isalpha() and len(w) > 1]
    if not words:
        return 1.0
    alts = {singular(w) for w in expansions or []}
    text_fields = [f.name for f in schema.fields if f.searchable]
    best, best_missing = 0.0, list(words)
    for h in hits[:3]:
        doc_words = set()
        for name in text_fields:
            v = h.document.get(name)
            for x in v if isinstance(v, list) else [v]:
                if x is not None:
                    doc_words.update(singular(t) for t in _WORD.findall(fold(str(x))))
        hit, miss = 0, []
        alt_hit = bool(alts & doc_words)
        for w in words:
            if w in doc_words or (len(w) >= 5 and any(abs(len(d) - len(w)) <= 1 and levenshtein(w, d, 1) <= 1
                                                      for d in doc_words)):
                hit += 1
            elif alt_hit:
                hit += 1
                alt_hit = False  # one synonym match covers one word
            else:
                miss.append(w)
        if hit / len(words) > best:
            best, best_missing = hit / len(words), miss
    if missing is not None:
        missing.extend(best_missing)
    return best


def match_quality(schema: Schema, plan: QueryPlan, result: _Result, floor: float, dictionary: Any = None) -> str:
    """good | weak | none from planner signals, lexical overlap and the vector score.

    - catalog evidence: the rules recognised a value or category of this catalog in the query, or the
      LLM's category agrees with where the results are
    - lexical overlap: how many query words the top results actually contain
    """
    evidence = any(f.origin in ("facet", "quantity", "chat") for f in plan.filters) or any(
        b.origin in ("facet", "category") for b in plan.boosts)
    if not evidence and result.focus:
        evidence = any(b.origin == "llm" and isinstance(b.value, str) and
                       (result.focus == b.value or result.focus.startswith(b.value + " > ") or
                        b.value.startswith(result.focus)) for b in plan.boosts)
    if result.lexical_hits == 0:
        top = result.vector_top if result.vector_top is not None else 0.0
        return "weak" if evidence or top >= floor else "none"
    missing: list[str] = []
    cov = _coverage(plan.keywords, result.hits, schema, plan.expansions, missing)
    if cov < 0.6:
        # the results don't contain some query words; that's fine only if the catalog knows those words
        # (the query is just phrased differently) and the rules recognised something concrete in it
        known = dictionary is not None and all(dictionary.in_vocab(w) for w in missing)
        if evidence and known and cov >= 0.34:
            return "good"
        return "weak" if evidence or cov >= 0.34 else "none" if (result.vector_top or 0) < floor else "weak"
    if plan.unparsed_tokens and not evidence and plan.source == "rules":
        return "weak"  # words the catalog has never seen and nothing else to anchor them
    return "good"


async def _backfill(state: State, pid: str, schema: Schema, req: SearchRequest, plan: QueryPlan,
                    explicit: list[dict[str, Any]], aggs: dict[str, Any], result: _Result) -> list[str]:
    """Fill a short first page, never outside the query's category.

    1. inferred attribute filters ("red", "silk") left few matches: same query without them
    2. a hard price cap left few matches: same category, cheapest items just over budget
    Exact matches stay first; the added ids are returned as close matches."""
    need = req.size - len(result.hits)
    seen = {h.id for h in result.hits}
    added: list[Hit] = []
    cat_spec, cat_path = _category_path(schema)
    focus_filter = ([{"terms": {f"{cat_path}.norm": [Q._norm_path(result.focus)]}}]
                    if result.focus and cat_path else [])
    soft = [f for f in plan.filters if not f.strict]
    if soft and need > 0:
        loose = plan.model_copy(update={"filters": [f for f in plan.filters if f.strict]})
        wide = await _retrieve(state, pid, schema, req, loose, explicit + focus_filter, aggs, None, 0)
        for h in wide.hits:
            if h.id not in seen and len(added) < need:
                added.append(h)
                seen.add(h.id)
        for k, v in wide.timings.items():
            result.timings[f"backfill_{k}"] = v
    price = next((f for f in plan.filters if f.origin == "price" and isinstance(f.value, dict)), None)
    cap = price.value.get("lte", price.value.get("lt")) if price else None
    if cap is not None and focus_filter and len(added) < need and len(result.hits) < 3:
        spec = schema.get(price.field)
        others = [Q.plan_filter_clause(schema, f) for f in plan.filters if f is not price and f.strict]
        body = {"query": {"bool": {"filter": [*explicit, *focus_filter, *[c for c in others if c],
                                              {"range": {f"f.{spec.key}": {"gt": cap}}}]}},
                "size": need - len(added), "_source": _SRC, "sort": [{f"f.{spec.key}": {"order": "asc"}}]}
        t = time.perf_counter()
        r = await state.os.search(index=alias_name(state.settings.index_prefix, pid), body=body)
        result.timings["backfill_budget"] = round((time.perf_counter() - t) * 1000, 2)
        names = Q.key_to_name(schema)
        for h in r["hits"]["hits"]:
            if h["_id"] not in seen:
                added.append(_hit(h, 0.0, names))
                seen.add(h["_id"])
    if added:
        result.hits = result.hits + added
    return [h.id for h in added]


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
    _, cat_path = _category_path(schema)
    dv = sorted(set(rr.fields) | ({cat_path} if cat_path else set()))
    extra: dict[str, Any] = {"docvalue_fields": dv} if dv else {}
    lex_body = {"query": {"bool": {"filter": filters, "must": [lexical]}}, "size": window, "_source": False,
                "track_total_hits": False, **extra}
    t = time.perf_counter()
    lex_r, knn_r = await _msearch(state, index, [lex_body, {**knn_body, "_source": False, **extra}])
    timings["retrieve"] = round((time.perf_counter() - t) * 1000, 2)
    knn_hits = knn_r["hits"]["hits"]
    vec_hits = Q.accept_vector_hits(knn_hits, s.knn_min_score, s.knn_relative_cutoff)
    lex_hits = lex_r["hits"]["hits"]
    focus = focus_category(lex_hits, cat_path, plan) if cat_path and plan is not None else None
    if focus:
        # Vector neighbours from other categories are filler, not results ("saree under 1000" -> no tea).
        # Weak lexical matches from other categories (e.g. a description that mentions the word) go too.
        top_score = max((h.get("_score") or 0.0) for h in lex_hits) if lex_hits else 0.0
        lex_hits = [h for h in lex_hits if focus in (h.get("fields") or {}).get(cat_path, [])
                    or (h.get("_score") or 0.0) >= 0.5 * top_score]
        lex_ids = {h["_id"] for h in lex_hits}
        vec_hits = [h for h in vec_hits if h["_id"] in lex_ids or focus in (h.get("fields") or {}).get(cat_path, [])]
    fused = rrf([lex_hits, vec_hits], s.rrf_k)
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
                   lexical_hits=len(lex_hits), vector_top=knn_hits[0]["_score"] if knn_hits else None,
                   timings=timings, focus=focus)



async def fetch_documents(state: State, pid: str, ids: list[str]) -> dict[str, dict[str, Any]]:
    """Stored documents by id (missing ids are left out), in the order asked."""
    if not ids:
        return {}
    r = await state.os.search(index=alias_name(state.settings.index_prefix, pid),
                              body={"query": {"ids": {"values": ids}}, "size": len(ids), "_source": _SRC})
    found = {h["_id"]: h["_source"]["zz_raw"] for h in r["hits"]["hits"]}
    return {i: found[i] for i in ids if i in found}
