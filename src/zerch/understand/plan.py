"""QueryPlan: the structured form of a query. Every field and value in it must exist in the project."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from zerch.schema.model import NUMBER_ROLES, Role, Schema


class PlanFilter(BaseModel):
    field: str
    op: Literal["eq", "in", "range", "not"]  # not = exclude these values
    value: Any  # str | list[str] | {"gte"/"lte"/...: number}
    # strict=False: documents that lack the field still pass; documents with a different value don't.
    # Used for inferred attribute filters, so "wireless earbuds" never drops earbuds that have no
    # connectivity field while still excluding wired ones.
    strict: bool = True
    confidence: float = 1.0
    origin: str = "rules"  # price | facet | quantity | category | llm
    text: str | None = None  # the query words this came from


class PlanBoost(BaseModel):
    field: str
    value: Any  # str | list[str]
    weight: float = 1.0
    origin: str = "rules"
    text: str | None = None


class PlanSort(BaseModel):
    field: str
    order: Literal["asc", "desc"]
    mode: Literal["soft", "hard"] = "soft"  # soft = re-rank toward cheaper/pricier, keep relevance
    text: str | None = None


class Relaxation(BaseModel):
    field: str
    value: Any
    reason: str


class QueryPlan(BaseModel):
    query: str
    semantic_text: str
    keywords: list[str] = Field(default_factory=list)
    expansions: list[str] = Field(default_factory=list)  # optional synonyms (lexical OR, added to vector text)
    filters: list[PlanFilter] = Field(default_factory=list)
    sort: PlanSort | None = None
    boosts: list[PlanBoost] = Field(default_factory=list)
    unparsed_tokens: list[str] = Field(default_factory=list)
    confidence: float = 1.0
    source: Literal["rules", "llm", "cache"] = "rules"
    relaxations: list[Relaxation] = Field(default_factory=list)


def _num(v: Any) -> float | None:
    if isinstance(v, bool):
        return None
    if isinstance(v, int | float):
        return float(v)
    try:
        return float(str(v).replace(",", ""))
    except ValueError:
        return None


def validate_plan(plan: QueryPlan, schema: Schema, dictionary: Any | None) -> QueryPlan:
    """Drop anything that does not exist in the project; canonicalise values to stored spellings."""

    def canon(field: str, value: Any) -> Any | None:
        spec = schema.get(field)
        if spec is None or not spec.filterable:
            return None
        if spec.role in NUMBER_ROLES:
            if isinstance(value, dict):
                rng = {k: _num(v) for k, v in value.items() if k in ("gte", "gt", "lte", "lt")}
                rng = {k: v for k, v in rng.items() if v is not None}
                return rng or None
            return _num(value)
        if spec.role == Role.boolean:
            return value if isinstance(value, bool) else None
        vals = value if isinstance(value, list) else [value]
        out = []
        for v in vals:
            c = dictionary.canonical_value(field, str(v)) if dictionary is not None else str(v)
            if c is not None and c not in out:
                out.append(c)
        if not out:
            return None
        return out if isinstance(value, list) else out[0]

    filters = []
    for f in plan.filters:
        spec = schema.get(f.field)
        if spec is None:
            continue
        v = canon(f.field, f.value)
        if v is None:
            continue
        if f.op == "range" and (spec.role not in NUMBER_ROLES or not isinstance(v, dict)):
            continue
        if f.op in ("eq", "in", "not") and isinstance(v, dict):
            continue
        op = f.op if f.op in ("range", "not") else ("in" if isinstance(v, list) else f.op)
        filters.append(f.model_copy(update={"value": v, "op": op}))
    boosts = []
    for b in plan.boosts:
        v = canon(b.field, b.value)
        if v is not None and not isinstance(v, dict):
            boosts.append(b.model_copy(update={"value": v}))
    sort = plan.sort
    if sort is not None:
        spec = schema.get(sort.field)
        if spec is None or spec.role not in NUMBER_ROLES:
            sort = None
    return plan.model_copy(update={"filters": filters, "boosts": boosts, "sort": sort})


def primary_price_field(schema: Schema) -> str | None:
    prices = schema.by_role(Role.price)
    if not prices:
        return None

    def rank(f) -> tuple[int, int]:
        n = f.name.lower()
        if any(w in n for w in ("mrp", "msrp", "list", "original", "compare", "was")):
            return (2, len(n))
        if any(w in n for w in ("sale", "selling", "offer", "final", "discount")):
            return (0, len(n))
        return (1 if n != "price" else 0, len(n))

    return sorted(prices, key=rank)[0].name
