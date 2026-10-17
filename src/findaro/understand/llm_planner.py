"""LLM path: only when the rules plan has words it cannot account for, or low confidence.

The LLM sees the query, a compact summary of this project's schema and values, and the rules output.
It returns a small JSON plan; every field and value is validated against the project before use.
"""

from __future__ import annotations

import json
from typing import Any

from findaro.llm.base import LLM, LLMError, parse_json
from findaro.schema.model import NUMBER_ROLES, Role, Schema
from findaro.understand.dictionary import Compiled, value_key
from findaro.understand.lexicon import default_lexicon
from findaro.understand.plan import PlanBoost, PlanFilter, QueryPlan, primary_price_field

SYSTEM = (
    "You turn search queries into a JSON search plan for one specific catalog. People write in "
    "English, in Hindi typed in Latin letters (Hinglish), or a mix. Use only field names and values that appear "
    "in the catalog summary, spelled exactly as listed. Never invent values. Reply with a single JSON object."
)

MAX_FACET_VALUES = 20
MAX_PATHS = 150


def schema_summary(schema: Schema, d: Compiled | None) -> str:
    lines = []
    for f in schema.fields:
        if not f.filterable:
            continue
        if f.role == Role.category and d is not None:
            paths = [p for p, _ in d.top_values.get(f.name, [])]
            leaves = [p for p in paths if not any(o != p and o.startswith(p + " > ") for o in paths)]
            lines.append(f"- {f.name} (category path): " + "; ".join(leaves[:MAX_PATHS]))
        elif f.role == Role.facet and d is not None:
            if d.coverage.get(f.name, 0) < 0.03:
                continue
            vals = [v for v, _ in d.top_values.get(f.name, [])[:MAX_FACET_VALUES]]
            lines.append(f"- {f.name}: " + ", ".join(vals))
        elif f.role in NUMBER_ROLES and f.role == Role.price:
            cur = f" ({d.currency})" if d is not None and d.currency else ""
            lines.append(f"- {f.name} (number{cur}, use op range)")
    return "\n".join(lines)


def build_prompt(query: str, schema: Schema, d: Compiled | None, rules: QueryPlan) -> str:
    rules_view = {
        "semantic_text": rules.semantic_text,
        "filters": [{"field": f.field, "op": f.op, "value": f.value} for f in rules.filters],
        "unknown_words": rules.unparsed_tokens,
    }
    price = primary_price_field(schema) or "price"
    return f"""Catalog summary (fields and allowed values):
{schema_summary(schema, d)}

Query: {json.dumps(query, ensure_ascii=False)}
A rule-based parser produced: {json.dumps(rules_view, ensure_ascii=False)}

Return JSON with exactly these keys:
{{"semantic_text": "<what the person is looking for, as a short plain-English description; no price words>",
  "category": "<the one category path from the list that fits best, or null if none fits>",
  "filters": [{{"field": "<field from the list>", "op": "eq", "value": "<value from that field's list>"}},
              {{"field": "{price}", "op": "range", "value": {{"lte": <the number the query gives>}}}}]}}
Only add a filter for something the query explicitly says (a colour, material, audience, price). Most queries
need no filters: use an empty list. If nothing in the catalog fits, set category to null."""


async def call_llm(llm: LLM, query: str, schema: Schema, d: Compiled | None, rules: QueryPlan) -> dict[str, Any]:
    raw = await llm.complete(build_prompt(query, schema, d, rules), system=SYSTEM, temperature=0.0, max_tokens=300,
                             json_mode=True)
    data = parse_json(raw)
    if not isinstance(data, dict):
        raise LLMError("planner returned a non-object")
    return {
        "semantic_text": str(data.get("semantic_text") or "")[:200],
        "category": data.get("category") if isinstance(data.get("category"), str) else None,
        "filters": [f for f in data.get("filters") or [] if isinstance(f, dict)][:8],
    }


def lexicon_for_grounding():
    return default_lexicon()


def merge(rules: QueryPlan, out: dict[str, Any], schema: Schema, d: Compiled | None, source: str) -> QueryPlan:
    """Rules stay authoritative for what they parsed (price, exact values, sort); the LLM fills the gaps.

    The LLM's main contribution is the English rewrite of words the rules could not read. Its attribute
    and category picks only boost ranking: small local models pick plausible-but-wrong values often
    enough that letting them filter does more harm than good."""
    plan = rules.model_copy(deep=True)
    if out.get("semantic_text"):
        plan.semantic_text = out["semantic_text"]
        plan.keywords = out["semantic_text"].split()
    have = {f.field for f in plan.filters}
    query_has_number = any(c.isdigit() for c in rules.query)
    grounded_text = value_key(f"{rules.query} {out.get('semantic_text', '')}", lexicon_for_grounding())
    for f in out.get("filters", []):
        fld, op, val = f.get("field"), f.get("op"), f.get("value")
        spec = schema.get(fld) if isinstance(fld, str) else None
        if spec is None or fld in have or op not in ("eq", "in", "range"):
            continue
        if spec.role in NUMBER_ROLES:
            # A price/number the query never mentioned is a hallucination (small models copy examples).
            if op == "range" and isinstance(val, dict) and query_has_number:
                plan.filters.append(PlanFilter(field=fld, op="range", value=val, strict=True, confidence=0.7,
                                               origin="llm"))
        elif spec.role == Role.category:
            plan.boosts.append(PlanBoost(field=fld, value=val, weight=1.0, origin="llm"))
        elif op in ("eq", "in"):
            vals = [v for v in (val if isinstance(val, list) else [val]) if isinstance(v, str)
                    and value_key(v, lexicon_for_grounding()) in grounded_text]  # only values the text mentions
            if vals:
                plan.boosts.append(PlanBoost(field=fld, value=vals if len(vals) > 1 else vals[0], weight=0.5,
                                             origin="llm"))
        have.add(fld)
    cat = out.get("category")
    if cat and str(cat).lower() not in ("null", "none"):
        for spec in schema.by_role(Role.category):
            plan.boosts.append(PlanBoost(field=spec.name, value=cat, weight=1.0, origin="llm"))
            break
    plan.source = source  # type: ignore[assignment]
    plan.confidence = max(plan.confidence, 0.8)
    return plan
