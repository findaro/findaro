"""Short answers grounded in the returned documents' fields. Never invents specs, prices or stock."""

from __future__ import annotations

import json
import re
from typing import Any

from zerch.schema.model import Role, Schema

SKIP_ROLES = {Role.url, Role.image_url, Role.ignore}

SLOT_RULES = (
    "Never write a digit yourself. Values shown as {field:ID} are slots: copy them exactly where the value "
    "should appear (e.g. {price:AB-001}) and the system fills them in; write {title:ID} for a product's full "
    "name. A # in the text stands for a number you can't see: never write #. Every sentence that mentions a "
    "product cites it as [ID], and a sentence that uses slots talks about one product only. Don't describe "
    "products as being for a purpose their fields don't state."
)
SYSTEM_SEARCH = (
    "You are the search assistant inside an online catalog. Write 1 to 3 short sentences about the search "
    "results given. Rules: state only facts that appear in the product fields given; never invent "
    "specifications, prices, stock, delivery or offers. Don't call a product available or in stock unless an "
    "in-stock field says so. For comparisons (cheapest, highest rated, biggest...) use only the computed facts "
    "given; never compare products yourself. Mention at most 3 products. The interface already shows the result "
    "cards, so don't list everything and don't use markdown. Don't ask the user a question. " + SLOT_RULES
)
SYSTEM_QUESTION = (
    "You answer a shopper's question about products currently shown to them, using only the product fields "
    "given. If the answer is not in the fields, say you don't have that detail; never guess. Reply in 1 to 3 "
    "short sentences, no markdown. " + SLOT_RULES
)


def language_rule(hinglish: bool) -> str:
    return ("Reply in Hinglish (Hindi written in Latin letters mixed with English), the way the user writes."
            if hinglish else "Reply in English.")


def doc_view(doc: dict[str, Any], schema: Schema, detailed: bool = False) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for f in schema.fields:
        if f.role in SKIP_ROLES:
            continue
        v = doc.get(f.name)
        if v is None or v == "" or v == []:
            continue
        if f.role in (Role.description, Role.text):
            if not detailed:
                continue
            v = str(v)[:300]
        out[f.name] = v
    return out


def compact_view(doc: dict[str, Any], schema: Schema, focus: set[str]) -> dict[str, Any]:
    """What a shopper sees on a card: title, price, stock, rating, plus the attributes the query is about."""
    out: dict[str, Any] = {}
    extra = 0
    for f in schema.fields:
        v = doc.get(f.name)
        if v is None or v == "" or v == [] or f.role in SKIP_ROLES or f.role in (Role.description, Role.text,
                                                                                Role.id, Role.keyword):
            continue
        if f.role == Role.title:
            out[f.name] = str(v)[:90]
        elif f.role in (Role.price, Role.boolean, Role.category) or f.name in focus:
            out[f.name] = v
        elif f.role == Role.numeric and "rating" in f.name and "count" not in f.name:
            out[f.name] = v
        elif f.role == Role.facet and extra < 3:
            out[f.name] = v
            extra += 1
    return out


_NUM = re.compile(r"\d[\d,]*(?:\.\d+)?")


def slotted(did: str, view: dict[str, Any], schema: Schema | None = None) -> dict[str, Any]:
    """Prompt view of a product in which the model never sees a number it could copy.

    Free text (title, description) keeps its words with each number masked as "#"; any other value that
    contains a digit is replaced by its slot {field:ID}, which the server fills."""
    text_roles = {Role.title, Role.description, Role.text}
    out: dict[str, Any] = {}
    for k, v in view.items():
        spec = schema.get(k) if schema is not None else None
        text = ", ".join(map(str, v)) if isinstance(v, list) else str(v)
        if isinstance(v, bool) or not any(c.isdigit() for c in text):
            out[k] = v
        elif spec is not None and spec.role in text_roles:
            out[k] = _NUM.sub("#", text)
        else:
            out[k] = f"{{{k}:{did}}}"
    return out


def _quantity(v: Any) -> tuple[float, str] | None:
    m = re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s*([A-Za-z]+)\s*", str(v)) if not isinstance(v, bool) else None
    return (float(m.group(1)), m.group(2).lower()) if m else None


def computed_facts(docs: list[tuple[str, dict[str, Any]]], schema: Schema) -> tuple[list[str], dict[str, str]]:
    """Comparisons computed in code over everything shown, so the model never has to compare.

    Only when every shown product has the field and the extreme is unique. Returns (prompt lines,
    {"low_price"|"high_price"|"top_rating"|"max_size"|"min_size": product id})."""
    lines: list[str] = []
    ids: dict[str, str] = {}
    if len(docs) < 2:
        return lines, ids

    def add(key: str, label: str, fld: str, vals: list[tuple[float, str]], pick) -> None:
        best = pick(vals)
        if sum(1 for x, _ in vals if x == best[0]) == 1:
            ids[key] = best[1]
            lines.append(f"{label}: [{best[1]}] ({{{fld}:{best[1]}}})")

    price = next((f.name for f in schema.by_role(Role.price)), None)
    rating = next((f.name for f in schema.by_role(Role.numeric) if "rating" in f.name and "count" not in f.name),
                  None)
    for fld in (price, rating):
        if not fld:
            continue
        vals = [(float(v[fld]), did) for did, v in docs if isinstance(v.get(fld), int | float)]
        if len(vals) != len(docs):
            continue
        if fld == price:
            add("low_price", "lowest price", fld, vals, min)
            add("high_price", "highest price", fld, vals, max)
        else:
            add("top_rating", "highest rating", fld, vals, max)
    # sizes: a facet whose values are all "<number> <unit>" with one unit (capacity, weight, volume...)
    for f in schema.fields:
        if f.role != Role.facet or f.multi:
            continue
        qs = [(_quantity(v.get(f.name)), did) for did, v in docs]
        if any(q is None for q, _ in qs) or len({q[1] for q, _ in qs}) != 1:
            continue
        vals = [(q[0], did) for q, did in qs]
        add("max_size", f"largest {f.name}", f.name, vals, max)
        add("min_size", f"smallest {f.name}", f.name, vals, min)
        break
    return lines, ids


def search_prompt(message: str, chips: list[str], quality: str, total: int, docs: list[tuple[str, dict, bool]],
                  suggestions: list[str], hinglish: bool, facts: list[str] | None = None,
                  schema: Schema | None = None) -> str:
    lines = [f"User message: {json.dumps(message, ensure_ascii=False)}",
             f"Understood: {', '.join(chips) or '(nothing specific)'}",
             f"Match quality: {quality}"]
    if docs:
        lines.append("Results in the order shown:")
        for i, (did, view, close) in enumerate(docs, 1):
            tag = " (close match: does not meet every constraint)" if close else ""
            lines.append(f"{i}. [{did}]{tag} {json.dumps(slotted(did, view, schema), ensure_ascii=False)}")
    else:
        lines.append("No results.")
    if facts:
        lines.append("Computed facts (over all products shown; the only comparisons you may make): "
                     + "; ".join(facts))
    if quality == "none" or not docs:
        lines.append("Nothing matched. Say so plainly" + (
            f" and suggest one of: {', '.join(suggestions)}." if suggestions else "."))
    elif quality == "weak":
        lines.append("These are not exact matches; say that honestly.")
    lines.append(language_rule(hinglish))
    return "\n".join(lines)


def question_prompt(message: str, docs: list[tuple[str, dict]], hinglish: bool,
                    facts: list[str] | None = None, schema: Schema | None = None) -> str:
    lines = ["Products currently shown (position. [ID] fields):"]
    for i, (did, view) in enumerate(docs, 1):
        lines.append(f"{i}. [{did}] {json.dumps(slotted(did, view, schema), ensure_ascii=False)}")
    if facts:
        lines.append("Computed facts (the only comparisons you may make): " + "; ".join(facts))
    lines.append(f"Question: {json.dumps(message, ensure_ascii=False)}")
    lines.append(language_rule(hinglish))
    return "\n".join(lines)


def chitchat_reply(message: str, hinglish: bool) -> str:
    if hinglish:
        return "Main products dhoondhne mein madad karta hoon. Jaise likhiye: 'black running shoes sasta wala'."
    return "I can help you find products. Try something like 'black running shoes for men'."


def fallback_search_text(total: int, quality: str, docs: list[tuple[str, dict, bool]], hinglish: bool,
                         title_field: str | None) -> str:
    """Used when no chat LLM is configured, it fails, or every sentence it wrote was dropped.
    States only what the shown products' own fields say."""
    if not docs or quality == "none":
        return "Koi matching product nahi mila." if hinglish else "I couldn't find anything matching that."
    did, view, _ = docs[0]
    title = view.get(title_field, did) if title_field else did
    if quality == "weak":
        return (f"Exact match nahi mila; sabse kareeb: {title} [{did}]." if hinglish
                else f"No exact match; the closest is {title} [{did}].")
    return (f"Pehla result: {title} [{did}]." if hinglish else f"First result: {title} [{did}].")
