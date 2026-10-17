"""Per-result requirement match: which of the things the query asked for each result actually has.

The requirements are the understood filter and boost chips plus any filters relaxed to find results. Each one is
checked against the document with the same semantics the engine filters with (category paths match their
subtree, text values case-insensitively, numbers by range), so "Matches 2/2" is computed, never guessed.
A document that lacks the field is `unknown`, not met.
"""

from __future__ import annotations

from typing import Any

from findaro.schema.model import NUMBER_ROLES, Role, Schema, flatten
from findaro.search.models import Hit, RequirementMatch, Understood


def _norm_path(v: str) -> str:
    return " > ".join(p.strip() for p in v.replace(">>", ">").split(">") if p.strip()).lower()


def _as_list(v: Any) -> list[Any]:
    return v if isinstance(v, list) else [v]


def _num(v: Any) -> float | None:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _in_range(x: float, rng: dict[str, Any]) -> bool:
    checks = {"gte": lambda b: x >= b, "gt": lambda b: x > b, "lte": lambda b: x <= b, "lt": lambda b: x < b}
    return all(checks[k](float(b)) for k, b in rng.items() if k in checks and _num(b) is not None)


def check(schema: Schema, flat: dict[str, Any], field: str, op: str, value: Any) -> bool | None:
    """True/False when the document has the field, None when it doesn't."""
    spec = schema.get(field)
    have = flat.get(field)
    if spec is None or have is None or have == "" or have == []:
        return None
    if op == "range" and isinstance(value, dict):
        nums = [n for n in (_num(v) for v in _as_list(have)) if n is not None]
        return any(_in_range(n, value) for n in nums) if nums else None
    wanted = _as_list(value)
    if spec.role in NUMBER_ROLES:
        hits = {_num(v) for v in _as_list(have)} & {_num(v) for v in wanted}
        found = bool(hits - {None})
    elif spec.role == Role.boolean:
        found = any(bool(h) == bool(w) for h in _as_list(have) for w in wanted)
    elif spec.role == Role.category:
        paths = [_norm_path(str(h)) for h in _as_list(have)]
        found = any(p == w or p.startswith(w + " > ") for p in paths for w in (_norm_path(str(x)) for x in wanted))
    else:
        found = bool({str(h).lower() for h in _as_list(have)} & {str(w).lower() for w in wanted})
    return not found if op == "not" else found


def annotate(schema: Schema, hits: list[Hit], understood: Understood | None) -> None:
    """Set `hit.requirements` on every hit when the query asked for anything checkable."""
    if understood is None:
        return
    reqs: list[tuple[str, str, str, Any]] = [(c.label, c.field, c.op, c.value) for c in understood.chips
                                             if c.kind in ("filter", "boost") and c.value is not None]
    reqs += [(r.label, r.field, "range" if isinstance(r.value, dict) else "eq", r.value)
             for r in understood.relaxations]
    seen: set[str] = set()
    reqs = [r for r in reqs if not (r[0] in seen or seen.add(r[0]))]
    if not reqs:
        return
    for hit in hits:
        flat = flatten(hit.document)
        m = RequirementMatch(total=len(reqs))
        for label, field, op, value in reqs:
            ok = check(schema, flat, field, op, value)
            (m.unknown if ok is None else m.met if ok else m.unmet).append(label)
        hit.requirements = m
