"""Short answers grounded in the returned documents' fields. Never invents specs, prices or stock."""

from __future__ import annotations

import json
from typing import Any

from zerch.schema.model import Role, Schema

SKIP_ROLES = {Role.url, Role.image_url, Role.ignore}

SYSTEM_SEARCH = (
    "You are the search assistant inside an online catalog. Write 1 to 3 short sentences about the search "
    "results given. Rules: state only facts that appear in the product fields given (title, price, attributes); "
    "never invent specifications, prices, stock, delivery or offers. Don't call a product available or in stock "
    "unless an in-stock field says so. For comparisons (cheapest, highest rated, biggest...) use only the computed "
    "facts given; never compare products yourself. Mention at most 3 products and cite each "
    "as [ID] using its exact id. The interface already shows the result cards, so don't list everything and "
    "don't use markdown. Don't ask the user a question."
)
SYSTEM_QUESTION = (
    "You answer a shopper's question about products currently shown to them, using only the product fields "
    "given. If the answer is not in the fields, say you don't have that detail; never guess. Reply in 1 to 3 "
    "short sentences, cite products as [ID] using their exact ids, no markdown."
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


def computed_facts(docs: list[tuple[str, dict, bool]], schema: Schema) -> list[str]:
    """Comparisons computed in code over everything shown, so the model never has to compare."""
    facts = []
    price = next((f.name for f in schema.by_role(Role.price)), None)
    rating = next((f.name for f in schema.by_role(Role.numeric) if "rating" in f.name and "count" not in f.name),
                  None)
    for fld, label_lo, label_hi in ((price, "lowest price", "highest price"), (rating, None, "highest rating")):
        vals = [(v[fld], did) for did, v, _ in docs if isinstance(v.get(fld), int | float)]
        if len(vals) < 2:
            continue
        lo, hi = min(vals), max(vals)
        if label_lo:
            facts.append(f"{label_lo} among shown: [{lo[1]}] ({lo[0]:g})")
        facts.append(f"{label_hi} among shown: [{hi[1]}] ({hi[0]:g})")
    return facts


def search_prompt(message: str, chips: list[str], quality: str, total: int, docs: list[tuple[str, dict, bool]],
                  suggestions: list[str], hinglish: bool, facts: list[str] | None = None) -> str:
    lines = [f"User message: {json.dumps(message, ensure_ascii=False)}",
             f"Understood: {', '.join(chips) or '(nothing specific)'}",
             f"Match quality: {quality} · total matches: {total}"]
    if docs:
        lines.append("Results in the order shown:")
        for i, (did, view, close) in enumerate(docs, 1):
            tag = " (close match: does not meet every constraint)" if close else ""
            lines.append(f"{i}. [{did}]{tag} {json.dumps(view, ensure_ascii=False)}")
    else:
        lines.append("No results.")
    if facts:
        lines.append("Computed facts (over all products shown): " + "; ".join(facts))
    if quality == "none" or not docs:
        lines.append("Nothing matched. Say so plainly" + (
            f" and suggest one of: {', '.join(suggestions)}." if suggestions else "."))
    elif quality == "weak":
        lines.append("These are not exact matches; say that honestly.")
    lines.append(language_rule(hinglish))
    return "\n".join(lines)


def question_prompt(message: str, docs: list[tuple[str, dict]], hinglish: bool) -> str:
    lines = ["Products currently shown (position. [ID] fields):"]
    for i, (did, view) in enumerate(docs, 1):
        lines.append(f"{i}. [{did}] {json.dumps(view, ensure_ascii=False)}")
    lines.append(f"Question: {json.dumps(message, ensure_ascii=False)}")
    lines.append(language_rule(hinglish))
    return "\n".join(lines)


def chitchat_reply(message: str, hinglish: bool) -> str:
    if hinglish:
        return "Main products dhoondhne mein madad karta hoon. Jaise likhiye: 'black running shoes 1500 ke andar'."
    return "I can help you find products. Try something like 'black running shoes under 1500'."


def fallback_search_text(total: int, quality: str, docs: list[tuple[str, dict, bool]], hinglish: bool,
                         title_field: str | None) -> str:
    """Used when no chat LLM is configured or it fails: still grounded, just plain."""
    if not docs or quality == "none":
        return "Koi matching product nahi mila." if hinglish else "I couldn't find anything matching that."
    did, view, _ = docs[0]
    title = view.get(title_field, did) if title_field else did
    return (f"{total} results mile. Sabse upar: {title} [{did}]." if hinglish
            else f"Found {total} results. Top match: {title} [{did}].")
