"""Plan patches: structured edits to a QueryPlan (remove a chip, set a price range, sort, add a filter).

Used by /v1/search and /v1/chat so a UI can change the plan without a new natural-language turn.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel

from zerch.schema.model import NUMBER_ROLES, Role, Schema
from zerch.understand.plan import PlanFilter, PlanSort, QueryPlan, primary_price_field, validate_plan


class PatchOp(BaseModel):
    """One edit. Examples:
    {"op": "add_filter", "field": "color", "value": "Black"}
    {"op": "remove_filter", "field": "color"}            (or with "value" to remove one value)
    {"op": "exclude", "field": "material", "value": "Plastic"}
    {"op": "set_price_range", "lte": 1500}               (no bounds = remove the price range)
    {"op": "set_sort", "field": "price", "order": "asc"} (no field = back to relevance)
    """

    op: Literal["add_filter", "remove_filter", "exclude", "set_price_range", "set_sort"]
    field: str | None = None
    value: Any = None
    gte: float | None = None
    lte: float | None = None
    order: Literal["asc", "desc"] | None = None


def _vals(v: Any) -> list[str]:
    return [str(x) for x in (v if isinstance(v, list) else [v])]


def _drop_words(plan: QueryPlan, words: set[str]) -> None:
    if words:
        kept = [w for w in plan.semantic_text.split() if w not in words]
        plan.semantic_text = " ".join(kept)
        plan.keywords = kept


def apply_patch(plan: QueryPlan, ops: list[PatchOp], schema: Schema, d: Any) -> QueryPlan:
    new = plan.model_copy(deep=True)
    price = primary_price_field(schema)
    for op in ops:
        spec = schema.get(op.field) if op.field else None
        if op.op in ("add_filter", "exclude"):
            if spec is None or op.value is None:
                continue
            if op.op == "add_filter":
                new.filters = [f for f in new.filters if not (f.field == spec.name and f.op != "not")]
                new.filters = [f for f in new.filters if not (f.field == spec.name and f.op == "not"
                                                              and set(_vals(f.value)) & set(_vals(op.value)))]
                new.filters.append(PlanFilter(field=spec.name, op="in" if isinstance(op.value, list) else "eq",
                                              value=op.value, strict=True, origin="patch", confidence=1.0))
                new.boosts = [b for b in new.boosts if b.field != spec.name]
            else:
                new.filters.append(PlanFilter(field=spec.name, op="not", value=op.value, origin="patch",
                                              confidence=1.0))
        elif op.op == "remove_filter":
            if spec is None:
                continue
            removed_words: set[str] = set()
            kept = []
            for f in new.filters:
                if f.field != spec.name:
                    kept.append(f)
                    continue
                if op.value is None:
                    removed_words |= set((f.text or "").split())
                    continue
                remaining = [v for v in _vals(f.value) if v not in set(_vals(op.value))]
                if not remaining:
                    removed_words |= set((f.text or "").split())
                    continue
                if f.op in ("eq", "in", "not") and isinstance(f.value, list):
                    kept.append(f.model_copy(update={"value": remaining}))
                else:
                    kept.append(f)
            new.filters = kept
            for b in new.boosts:
                if b.field == spec.name and (op.value is None or set(_vals(b.value)) & set(_vals(op.value))):
                    removed_words |= set((b.text or "").split())
            new.boosts = [b for b in new.boosts if not (b.field == spec.name and (
                op.value is None or set(_vals(b.value)) & set(_vals(op.value))))]
            if new.sort is not None and new.sort.field == spec.name and spec.role in NUMBER_ROLES:
                new.sort = None
            _drop_words(new, removed_words)
        elif op.op == "set_price_range":
            if price is None:
                continue
            removed = [f for f in new.filters if f.field == price and f.op == "range"]
            new.filters = [f for f in new.filters if not (f.field == price and f.op == "range")]
            rng = {k: v for k, v in (("gte", op.gte), ("lte", op.lte)) if v is not None}
            if rng:
                new.filters.append(PlanFilter(field=price, op="range", value=rng, strict=True, origin="price",
                                              confidence=1.0, text="price"))
            elif removed:
                _drop_words(new, {w for f in removed for w in (f.text or "").split()})
        elif op.op == "set_sort":
            if spec is None or op.order is None:
                new.sort = None
            elif spec.role in NUMBER_ROLES or spec.role in (Role.facet, Role.keyword, Role.id):
                new.sort = PlanSort(field=spec.name, order=op.order, mode="hard")
    new.relaxations = []
    return validate_plan(new, schema, d)


def remove_ops(kind: str, field: str, op: str, value: Any, schema: Schema) -> list[PatchOp]:
    """The patch that removes one understood chip."""
    if kind == "sort":
        return [PatchOp(op="set_sort")]
    spec = schema.get(field)
    if spec is not None and spec.role == Role.price and op == "range":
        return [PatchOp(op="set_price_range")]
    return [PatchOp(op="remove_filter", field=field, value=value if op in ("eq", "not") else None)]
