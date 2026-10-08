"""Clarifying questions. At most one per turn; chips come from the result set's own facet counts."""

from __future__ import annotations

import math
from typing import Any

from pydantic import BaseModel, Field

from zerch.schema.model import Role, Schema
from zerch.search.models import SearchResponse
from zerch.understand.plan import QueryPlan, primary_price_field

MIN_RESULTS = 8
MIN_ENTROPY = 0.75
MAX_TOP_SHARE = 0.6
MIN_COVERAGE = 0.7


class ClarifyChip(BaseModel):
    label: str
    count: int | None = None
    plan_patch: dict[str, Any]


class Clarify(BaseModel):
    question: str
    reason: str  # entropy | budget | weak_match
    field: str | None = None
    chips: list[ClarifyChip] = Field(default_factory=list)


def _entropy(counts: list[int]) -> float:
    total = sum(counts)
    if total == 0 or len(counts) < 2:
        return 0.0
    h = -sum((c / total) * math.log(c / total) for c in counts if c)
    return h / math.log(len(counts))


def _category_children(values: list[dict[str, Any]], total: int) -> tuple[str | None, list[dict[str, Any]]]:
    """Children of the deepest category that covers ~all results."""
    if not values or not total:
        return None, []
    covering = [v for v in values if v["count"] >= 0.9 * total]
    parent = max(covering, key=lambda v: v["value"].count(" > "))["value"] if covering else None
    depth = parent.count(" > ") + 1 if parent else 0
    kids = [v for v in values if v["value"].count(" > ") == depth and
            (parent is None or v["value"].startswith(parent + " > "))]
    return parent, kids


def _label(field: str) -> str:
    return field.replace("_", " ")


MIN_RESULTS_ATTRIBUTE = 30


def decide(plan: QueryPlan, resp: SearchResponse, schema: Schema, *, hinglish: bool, just_show: bool,
           answered_clarifier: bool, symbol: str, new_search: bool = True) -> Clarify | None:
    """Ask at most one question, and only when it helps:
    - budget: a hard price cap leaves fewer than 3 exact matches (any turn)
    - weak/no match on a new search: offer the categories the results fall in, or dropping a constraint
    - a new search whose results span several product categories: ask which one
    - a bare, unconstrained new search with many results spread over one attribute: ask about it
    """
    if just_show or answered_clarifier:
        return None
    und = resp.understood
    quality = und.match_quality if und else "good"
    close = set(und.close_matches) if und else set()
    exact = [h for h in resp.hits if h.id not in close]

    # 1. a hard price cap leaves fewer than 3 exact matches
    price_field = primary_price_field(schema)
    cap = None
    for f in plan.filters:
        if f.field == price_field and f.op == "range" and isinstance(f.value, dict):
            cap = f.value.get("lte", f.value.get("lt"))
    if cap is not None and len(exact) < 3:
        new_cap = float(math.ceil(cap * 1.3 / 100) * 100)
        n = len(exact)
        q = (f"₹{int(cap):,} ke andar sirf {n} mile. Thoda upar ke options dikhaun?" if hinglish and symbol == "₹"
             else f"Only {n} match{'es' if n != 1 else ''} under {symbol}{int(cap):,}. "
                  "Want to see options slightly over budget?")
        return Clarify(question=q, reason="budget", field=price_field, chips=[
            ClarifyChip(label="Show slightly over budget", plan_patch={"price": {"lte": new_cap}}),
            ClarifyChip(label=f"Keep under {symbol}{int(cap):,}", plan_patch={})])

    cat = next((f for f in schema.by_role(Role.category)), None)
    cat_facet = resp.facets.get(cat.name) if cat else None

    if not new_search:
        return None

    # 2. weak / no match: offer the categories the results actually fall in, or dropping a constraint
    if quality in ("weak", "none"):
        chips: list[ClarifyChip] = []
        if cat_facet and resp.total:
            _, kids = _category_children(cat_facet.get("values", []), resp.total)
            for v in sorted(kids, key=lambda v: -v["count"])[:4]:
                chips.append(ClarifyChip(label=v["value"].split(" > ")[-1], count=v["count"], plan_patch={
                    "add_filters": [{"field": cat.name, "op": "eq", "value": v["value"]}]}))
        if not chips:
            for f in plan.filters[:3]:
                if f.op == "not":
                    continue
                chips.append(ClarifyChip(label=f"Without {f.text or _label(f.field)}",
                                         plan_patch={"remove_fields": [f.field]}))
        if not chips:
            return None
        q = ("Exact match nahi mila. Inme se kuch chahiye?" if hinglish
             else "I couldn't find an exact match. Is one of these close?")
        return Clarify(question=q, reason="weak_match", field=cat.name if cat else None, chips=chips)

    # 3. results spread over several values of a discriminating attribute the query didn't pick
    if resp.total < MIN_RESULTS:
        return None
    constrained = {f.field for f in plan.filters} | {b.field for b in plan.boosts if b.origin != "category"}
    candidates: list[tuple[float, str, list[dict[str, Any]]]] = []
    named = [p for b in plan.boosts if cat is not None and b.field == cat.name and b.origin in ("category", "llm")
             for p in (b.value if isinstance(b.value, list) else [b.value])]
    filtered = cat is not None and cat.name in {f.field for f in plan.filters}
    if cat_facet and not filtered:
        parent, kids = _category_children(cat_facet.get("values", []), resp.total)
        depth = parent.count(" > ") + 1 if parent else 0
        # skip only if the query already named something at least as specific as the choices
        if any(str(p).count(" > ") >= depth for p in named):
            kids = []
        kids = sorted(kids, key=lambda v: -v["count"])[:8]
        counts = [v["count"] for v in kids]
        if len(kids) >= 2 and sum(counts) >= MIN_COVERAGE * resp.total and max(counts) <= MAX_TOP_SHARE * sum(counts):
            e = _entropy(counts)
            if e >= MIN_ENTROPY:
                candidates.append((e + 0.1, cat.name, kids))
    bare_query = not plan.filters and len(plan.semantic_text.split()) <= 2 and resp.total >= MIN_RESULTS_ATTRIBUTE
    for spec in schema.fields:
        if candidates or not bare_query:
            break  # a category question beats an attribute one; attributes only for bare, broad queries
        if spec.role != Role.facet or spec.multi or spec.name in constrained:
            continue
        fv = resp.facets.get(spec.name)
        if not fv or fv.get("type") != "terms":
            continue
        vals = [v for v in fv.get("values", []) if v["count"] > 0]
        counts = [v["count"] for v in vals]
        if not (3 <= len(vals) <= 10) or sum(counts) < MIN_COVERAGE * resp.total:
            continue
        if max(counts) > MAX_TOP_SHARE * sum(counts):
            continue
        e = _entropy(counts)
        if e >= MIN_ENTROPY:
            candidates.append((e * min(1.0, sum(counts) / resp.total), spec.name, vals))
    if not candidates:
        return None
    _, field, vals = max(candidates, key=lambda c: c[0])
    top = sorted(vals, key=lambda v: -v["count"])[:5]
    is_cat = cat is not None and field == cat.name
    chips = [ClarifyChip(label=(v["value"].split(" > ")[-1] if is_cat else str(v["value"])), count=v["count"],
                         plan_patch={"add_filters": [{"field": field, "op": "eq", "value": v["value"]}]})
             for v in top]
    if is_cat:
        q = "Kaunsa type chahiye?" if hinglish else "Which kind are you looking for?"
    else:
        q = f"{_label(field).capitalize()} ka koi preference?" if hinglish else f"Any preference for {_label(field)}?"
    return Clarify(question=q, reason="entropy", field=field, chips=chips)
