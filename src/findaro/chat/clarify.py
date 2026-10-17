"""Clarifying questions. At most one per turn; chips come from the result set's own facet counts."""

from __future__ import annotations

import math
from typing import Any

from pydantic import BaseModel, Field

from findaro.schema.model import Role, Schema
from findaro.search.models import SearchResponse
from findaro.understand.plan import QueryPlan, primary_price_field

MIN_RESULTS = 8
MIN_ENTROPY = 0.75
MAX_TOP_SHARE = 0.6
MIN_COVERAGE = 0.7


class ClarifyChip(BaseModel):
    label: str
    count: int | None = None
    plan_patch: dict[str, Any]  # M3 shape (PlanDelta), kept for compatibility
    patch: list[dict[str, Any]] = Field(default_factory=list)  # M4 patch ops; send as `patch`


class Clarify(BaseModel):
    question: str
    reason: str  # entropy | budget | weak_match | suggest | next
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


def decide(plan: QueryPlan, resp: SearchResponse, schema: Schema, *, hinglish: bool, just_show: bool,
           answered_clarifier: bool, symbol: str, new_search: bool = True) -> Clarify | None:
    """Ask at most one question, and only for:
    - budget: a hard price cap leaves fewer than 3 exact matches (any turn)
    - weak/no match on a new search: offer the categories the results fall in, or dropping a constraint
    - category ambiguity: a new search whose results span several product categories
    Attribute choices (colour, size...) are not questions; they're passive facet pills on the results.
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
            ClarifyChip(label="Show slightly over budget", plan_patch={"price": {"lte": new_cap}},
                        patch=[{"op": "set_price_range", "lte": new_cap}]),
            ClarifyChip(label=f"Keep under {symbol}{int(cap):,}", plan_patch={}, patch=[])])
    if cap is not None and quality in ("weak", "none"):
        # nothing really fits under the budget: the budget is the likeliest reason, so offer to lift it
        new_cap = float(math.ceil(cap * 1.5 / 100) * 100)
        q = (f"₹{int(cap):,} ke andar sahi match nahi mila. Budget badhaun?" if hinglish and symbol == "₹"
             else f"Nothing matches well under {symbol}{int(cap):,}. Raise the budget?")
        return Clarify(question=q, reason="budget", field=price_field, chips=[
            ClarifyChip(label=f"Up to {symbol}{int(new_cap):,}", plan_patch={"price": {"lte": new_cap}},
                        patch=[{"op": "set_price_range", "lte": new_cap}]),
            ClarifyChip(label="Any price", plan_patch={"remove_fields": [price_field]},
                        patch=[{"op": "set_price_range"}])])

    cat = next((f for f in schema.by_role(Role.category)), None)
    cat_facet = resp.facets.get(cat.name) if cat else None

    if not new_search:
        return None

    # 2. weak / no match: offer the categories the results actually fall in, or dropping a constraint
    if quality in ("weak", "none"):
        chips: list[ClarifyChip] = []
        if cat is not None and resp.hits:
            # the categories of the closest results themselves (not of the long tail a weak query also matches)
            seen: dict[str, int] = {}
            for h in resp.hits[:10]:
                path = h.document.get(cat.name)
                path = path[0] if isinstance(path, list) and path else path
                if isinstance(path, str) and path:
                    seen[path] = seen.get(path, 0) + 1
            for path, _ in sorted(seen.items(), key=lambda kv: -kv[1])[:4]:
                if len(seen) < 2:
                    break
                chips.append(ClarifyChip(label=path.split(cat.separator or " > ")[-1].strip(), plan_patch={
                    "add_filters": [{"field": cat.name, "op": "eq", "value": path}]},
                    patch=[{"op": "add_filter", "field": cat.name, "value": path}]))
        if not chips:
            for f in plan.filters[:3]:
                if f.op == "not":
                    continue
                chips.append(ClarifyChip(label=f"Without {f.text or _label(f.field)}",
                                         plan_patch={"remove_fields": [f.field]},
                                         patch=[{"op": "remove_filter", "field": f.field}]))
        if not chips:
            return None
        q = ("Exact match nahi mila. Inme se kuch chahiye?" if hinglish
             else "I couldn't find an exact match. Is one of these close?")
        return Clarify(question=q, reason="weak_match", field=cat.name if cat else None, chips=chips)

    # 3. results spread over several values of a discriminating attribute the query didn't pick
    if resp.total < MIN_RESULTS:
        return None
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
    if not candidates:
        return None
    _, field, vals = max(candidates, key=lambda c: c[0])
    top = sorted(vals, key=lambda v: -v["count"])[:5]
    is_cat = cat is not None and field == cat.name
    chips = [ClarifyChip(label=(v["value"].split(" > ")[-1] if is_cat else str(v["value"])), count=v["count"],
                         plan_patch={"add_filters": [{"field": field, "op": "eq", "value": v["value"]}]},
                         patch=[{"op": "add_filter", "field": field, "value": v["value"]}])
             for v in top]
    if is_cat:
        q = "Kaunsa type chahiye?" if hinglish else "Which kind are you looking for?"
    else:
        q = f"{_label(field).capitalize()} ka koi preference?" if hinglish else f"Any preference for {_label(field)}?"
    return Clarify(question=q, reason="entropy", field=field, chips=chips)


def _round_budget(x: float) -> float:
    """A price a person would say: 799 -> 700, 2340 -> 2000, 1500 -> 1500, 45 -> 40."""
    if x < 10:
        return float(math.floor(x))
    step = 10 ** int(math.log10(x))  # 100 for 799, 1000 for 2340
    if x < 2 * step:  # 1500: flooring to 1000 would cut too much, use the next digit
        step //= 10
    return float(math.floor(x / step) * step)


def next_steps(plan: QueryPlan | None, resp: SearchResponse, schema: Schema, *, hinglish: bool,
               symbol: str) -> Clarify | None:
    """Up to three one-click ways to narrow the results on screen, each a real refinement of them:
    the top value of the most useful attributes, a budget below the median price, cheapest first."""
    if len(resp.hits) < 4:
        return None
    chips: list[ClarifyChip] = []
    for pill in resp.pills[:2]:
        top = max(pill.values, key=lambda v: v.count, default=None)
        if top is None or top.count >= resp.total:
            continue
        chips.append(ClarifyChip(label=(f"Sirf {top.label}" if hinglish else f"Only {top.label}"), count=top.count,
                                 patch=[p.model_dump(exclude_none=True) for p in top.patch], plan_patch={}))
    price_field = primary_price_field(schema)
    has_cap = plan is not None and any(f.field == price_field and f.op == "range" for f in plan.filters)
    if price_field and not has_cap:
        prices = sorted(float(p) for h in resp.hits
                        if isinstance(p := h.document.get(price_field), int | float) and p > 0)
        if len(prices) >= 4:
            cap = _round_budget(prices[len(prices) // 2])
            if prices[0] <= cap < prices[-1]:
                label = f"{symbol}{int(cap):,} ke andar" if hinglish else f"Under {symbol}{int(cap):,}"
                chips.append(ClarifyChip(label=label, patch=[{"op": "set_price_range", "lte": cap}], plan_patch={}))
    if price_field and (plan is None or plan.sort is None) and len(chips) < 3:
        chips.append(ClarifyChip(label="Sabse sasta pehle" if hinglish else "Cheapest first",
                                 patch=[{"op": "set_sort", "field": price_field, "order": "asc"}], plan_patch={}))
    if not chips:
        return None
    return Clarify(question="Aur chhota karein:" if hinglish else "Narrow it down:", reason="next",
                   field=None, chips=chips[:3])
