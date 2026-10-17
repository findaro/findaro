"""Short answers grounded in the returned documents' fields. Never invents specs, prices or stock."""

from __future__ import annotations

import json
import re
from typing import Any

from findaro.schema.model import Role, Schema

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
    return ("Reply in Hinglish (Hindi written in Latin letters mixed with English), the way the user writes, "
            "even if earlier replies were in English." if hinglish else "Reply in English.")


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


# greetings / thanks / acknowledgements get the instant template; other small talk ("who are you?") goes to the model
SIMPLE_TALK = re.compile(r"^\W*(hi+|hello|hey|namaste|namaskar|thanks?|thank ?you|thx|ty|shukriya|dhanyava?a?d|"
                         r"dhanyawad|ok|okay|cool|great|nice|bye|goodbye|good (morning|night|evening)|lol|hmm+|"
                         r"ji|bhai|sir|yaar)(\W+(hi+|hello|hey|there|ji|bhai|sir|yaar|so much|a lot|everyone))*\W*$",
                         re.I)
THANKS = re.compile(r"\b(thanks?|thank you|thx|ty|shukriya|dhanyavaad|dhanyavad|dhanyawad)\b", re.I)


def chitchat_reply(message: str, hinglish: bool, has_results: bool = False) -> str:
    """Instant reply to a greeting or thanks (no LLM); suggestion chips come with it when nothing is on screen."""
    if THANKS.search(message) and has_results:
        return ("Khushi hui! Inhe aur refine karein, ya kuch aur dhoondhein?" if hinglish else
                "Happy to help! Want to refine these, or look for something else?")
    if THANKS.search(message):
        return "Khushi hui! Aur kya dhoondh rahe hain?" if hinglish else "Happy to help! What else are you looking for?"
    if has_results:
        return ("Hi! Inhe refine karna hai ya kuch naya dhoondhna hai?" if hinglish else
                "Hi! Want to refine these results, or look for something new?")
    return ("Namaste! Aaj kya dhoondh rahe hain? Neeche se shuru karein, ya apne shabdon mein bataiye." if hinglish else
            "Hi! What are you shopping for today? Pick a category below, or just tell me what you need.")


SYSTEM_CONVERSE = (
    "You are the friendly shopping assistant of an online store. The shopper wrote something that isn't a plain "
    "product search: small talk, a situation, a question about you, or a need in their own words. Reply in 1 or "
    "2 short, warm sentences, like a helpful shop assistant, and steer the conversation towards what the store "
    "sells. Rules: you can't see any products in this step, so never name a specific product, brand, price, "
    "discount, stock or delivery promise, and don't write numbers. If the message points to a need one of the "
    "store's categories can meet, set \"search\" to a short search of 2 to 6 words in the store's own words "
    "(a category, plus an attribute the shopper gave), and say what you'll show. If they ask for something the "
    "store doesn't sell, say so kindly and mention what it does sell, with \"search\": null. For pure small talk, "
    "answer it briefly and ask what they're shopping for, with \"search\": null. Don't call yourself an AI model. "
    "Return only JSON: {\"reply\": \"...\", \"search\": \"...\" or null}"
)


def store_categories(schema: Schema, d: Any, limit: int = 60) -> list[str]:
    """Leaf category paths the catalog actually has, most common first (from the per-project dictionary)."""
    spec = next(iter(schema.by_role(Role.category)), None)
    if spec is None or d is None:
        return []
    paths = [p for p, _ in d.top_values.get(spec.name, [])]
    return [p for p in paths if not any(o != p and o.startswith(p + " > ") for o in paths)][:limit]


def top_categories(schema: Schema, d: Any, n: int = 6) -> list[str]:
    """First level of the category tree by product count: labels for suggestion chips."""
    spec = next(iter(schema.by_role(Role.category)), None)
    if spec is None or d is None:
        return []
    counts: dict[str, int] = {}
    for p, c in d.top_values.get(spec.name, []):
        head = p.split(" > ")[0].strip()
        if head:
            counts[head] = counts.get(head, 0) + c
    return [k for k, _ in sorted(counts.items(), key=lambda kv: -kv[1])[:n]]


# a conversational reply can't see products: no numbers, citations, prices, stock, offers or delivery promises
CONVERSE_BLOCK = re.compile(r"\d|\[|\{|#|\b(in stock|out of stock|stock|discount|offer|sale|deal|cheapest|"
                            r"lowest price|free delivery|delivery|deliver|ships?|shipping|sasta|sasti|sabse)\b", re.I)


def converse_sentences(reply: str) -> tuple[str, list[tuple[str, str]]]:
    """Keeps the reply's sentences that make no claim it can't back; returns (kept text, dropped)."""
    kept, dropped = [], []
    for sent in re.split(r"(?<=[.!?])\s+", reply.strip()):
        if not sent:
            continue
        if CONVERSE_BLOCK.search(sent):
            dropped.append((sent, "conversation reply makes a claim it can't see"))
        else:
            kept.append(sent)
    return " ".join(kept), dropped


def converse_prompt(message: str, categories: list[str], history: list[tuple[str, str]],
                    current: str | None, hinglish: bool) -> str:
    lines = ["The store's categories: " + ("; ".join(categories) if categories else "(not known)")]
    if current:
        lines.append(f"Current search on screen: {json.dumps(current, ensure_ascii=False)}")
    if history:
        lines.append("Conversation so far:")
        lines += [f"{'Shopper' if role == 'user' else 'Assistant'}: {text}" for role, text in history[-4:]]
    lines.append(f"Shopper's latest message: {json.dumps(message, ensure_ascii=False)}")
    lines.append("Reply to the latest message only; earlier turns are just context. If it names a product, "
                 "answer about that product. " + language_rule(hinglish) + " The search itself is always in English.")
    return "\n".join(lines)


def fallback_search_text(total: int, quality: str, docs: list[tuple[str, dict, bool]], hinglish: bool,
                         title_field: str | None) -> str:
    """Used when no chat LLM is configured, it fails, or every sentence it wrote was dropped.
    States only what the shown products' own fields say."""
    if not docs or quality == "none":
        return "Koi matching product nahi mila." if hinglish else "I couldn't find anything matching that."
    did = docs[0][0]
    # the UI renders [ID] as a product card, so the title isn't repeated in the text
    if quality == "weak":
        return (f"Exact match nahi mila. Sabse kareeb: [{did}]" if hinglish
                else f"No exact match. Closest: [{did}]")
    return (f"Sabse upar: [{did}]" if hinglish else f"Top result: [{did}]")


def fallback_product_text(focus: dict[str, dict[str, Any]], schema: Schema, hinglish: bool, symbol: str) -> str:
    """No chat LLM, a turn about specific products: say only what their own fields show (cheapest, by price)."""
    if not focus:
        return "Ye product ab nahi mila." if hinglish else "I couldn't find that product anymore."
    if len(focus) == 1:
        return ("Iski saari details upar hain." if hinglish else "Its full details are above.")
    from findaro.understand.plan import primary_price_field

    pf = primary_price_field(schema)
    priced = [(float(doc[pf]), pid) for pid, doc in focus.items()
              if pf and isinstance(doc.get(pf), int | float)]
    n = len(focus)
    head = f"Ye {n} products saath mein dekhiye." if hinglish else f"Here are the {n} products side by side."
    if len(priced) >= 2:
        price, pid = min(priced)
        amount = f"{symbol}{price:,.0f}" if price == int(price) else f"{symbol}{price:,.2f}"
        head += (f" Sabse sasta [{pid}] hai, {amount} mein." if hinglish
                 else f" The cheapest is [{pid}] at {amount}.")
    return head


# --- product conversation (M5) ------------------------------------------------------------------------------

GENERAL_MARKER = "General:"

SYSTEM_PRODUCT = (
    "You are a helpful shopping assistant talking with a shopper about specific products, like a friend who "
    "knows products well. First answer from the listing: 1 to 3 short sentences using ONLY the product fields "
    "given. If the listing doesn't say (for example the country of origin or a warranty isn't listed), say "
    "plainly that the seller hasn't listed it; never guess. For suitability questions (rain, gym, office, gifting...) "
    "quote what the listing states (for example its care instructions or description) instead of answering yes "
    "or no; put any general advice in the general line. Then, only if it genuinely helps, add one line "
    "starting with \"" + GENERAL_MARKER + "\" with one or two sentences of general know-how about this kind of "
    "product or material (care, suitability, what to check before buying). That general line must not state "
    "anything about this specific product, and must not mention brands, prices or numbers. Don't label the parts.\n"
    "No markdown, no lists. Copy names, numbers and values exactly as the listing gives them (a number that isn't "
    "in the listing is removed). Cite products as [ID] when more than one is shown."
)


def product_prompt(message: str, docs: list[tuple[str, dict]], hinglish: bool, history: list[tuple[str, str]],
                   facts: list[str] | None = None, schema: Schema | None = None) -> str:
    lines = ["Products the shopper is asking about (position. [ID] and every field the seller listed):"]
    id_fields = {f.name for f in schema.by_role(Role.id)} if schema is not None else set()
    for i, (did, view) in enumerate(docs, 1):
        view = {k: v for k, v in view.items() if k not in id_fields}
        lines.append(f"{i}. [{did}] {json.dumps(view, ensure_ascii=False)}")
    if facts:
        lines.append("Computed facts (the only comparisons you may make): " + "; ".join(facts))
    if history:
        lines.append("Conversation so far:")
        for role, text in history[-6:]:
            lines.append(f"{role}: {text[:300]}")
    lines.append(f"Shopper: {json.dumps(message, ensure_ascii=False)}")
    lines.append(language_rule(hinglish))
    return "\n".join(lines)


def missing_detail_text(hinglish: bool) -> str:
    return ("Main iska pakka jawab nahi de paaya; upar product details mein seller ki di hui saari jaankari hai."
            if hinglish else
            "I couldn't answer that reliably; the product details show everything the seller listed.")


def listed_text(fields: list[tuple[str, str]], hinglish: bool) -> str:
    """Fallback that quotes the listing word for word, e.g. after a reworded return policy was dropped."""
    shown = "; ".join(f"{k.replace('_', ' ').capitalize()}: {v}" for k, v in fields)
    return f"Seller ne ye likha hai — {shown}." if hinglish else f"The seller lists — {shown}."


def not_stated_text(hinglish: bool) -> str:
    """Fallback when the only answer would have been a suitability verdict the listing doesn't give."""
    return ("Seller ne ye nahi bataya ki ye iske liye theek hai ya nahi." if hinglish
            else "The seller doesn't say whether it suits that.")


def retry_hint(fields: list[str]) -> str:
    return ("\nNote: your previous answer said a detail was not listed, but the listing does include: "
            + ", ".join(fields) + ". Answer from those fields.")
