"""Turn classification and plan refinement (rules first; the LLM only when the rules can't tell).

Turn types: new (search), refine (change the current plan), question (about shown products), chitchat.
"""

from __future__ import annotations

import re
import statistics
from typing import Any, Literal

from pydantic import BaseModel, Field

from findaro.schema.model import NUMBER_ROLES, Role, Schema
from findaro.understand.dictionary import Compiled
from findaro.understand.lexicon import Lexicon, fold, tokenize
from findaro.understand.plan import PlanFilter, PlanSort, QueryPlan, primary_price_field, validate_plan
from findaro.understand.rules import RulesParser

TurnType = Literal["new", "refine", "question", "chitchat"]

CHITCHAT = {
    "hi", "hello", "hey", "hii", "namaste", "namaskar", "thanks", "thank you", "thankyou", "thx", "shukriya",
    "dhanyavad", "dhanyawad", "ok", "okay", "cool", "great", "nice", "bye", "goodbye", "how are you",
    "kaise ho", "kya haal hai", "who are you", "what can you do", "good morning", "good night", "lol", "hmm",
}
# small talk inside a longer message ("hi, how is it going?"); counts only when the message names nothing in the
# catalog, so "how are these shoes" stays a product turn
SMALL_TALK = re.compile(r"\b(how (are|r) (you|u)|how('s| is) it going|how('s| is) your day|what'?s up|wassup|"
                        r"kaise ho|kya haal|who are you|what can you do|what do you do|are you (a )?(bot|human|ai)|"
                        r"good (morning|afternoon|evening|night))\b", re.I)
# words that show the user is asking about results already on screen
ORDINALS = {"first": 1, "1st": 1, "pehla": 1, "pehle": 1, "pehli": 1, "second": 2, "2nd": 2, "dusra": 2,
            "doosra": 2, "dusre": 2, "dusri": 2, "third": 3, "3rd": 3, "teesra": 3, "tisra": 3, "teesri": 3,
            "fourth": 4, "4th": 4, "chautha": 4, "fifth": 5, "5th": 5, "last": -1, "aakhri": -1, "akhri": -1}
QUESTION_WORDS = {"which", "what", "does", "do", "is", "are", "can", "kya", "kaunsa", "konsa", "kaunsi", "konsi",
                  "kaun", "kitna", "kitni", "kitne", "how", "compare", "difference", "fark", "batao", "bataiye"}
DEICTIC = {"this", "that", "these", "those", "it", "ye", "yeh", "wo", "woh", "isme", "usme", "iska", "uska",
           "inme", "unme", "iski", "uski", "inka", "unka"}
REFINE_START = {"only", "sirf", "just", "bas", "and", "aur", "but", "in", "with", "without", "not", "no", "under",
                "below", "above", "over", "less", "more", "cheaper", "costlier", "koi", "kuch", "same", "also",
                "ab", "phir", "chahiye", "wala", "wali", "wale", "me", "mein", "for", "ke", "liye", "bigger",
                "smaller", "larger", "bada", "badi", "chhota", "chota", "chhoti", "choti", "thoda"}
NEG_BEFORE = {"not", "no", "without", "except", "excluding", "bina", "na", "non"}
NEG_AFTER = {"nahi", "nahin", "nai", "mat", "nahi chahiye", "na", "alawa", "alava", "siwa", "siva"}
# negators: before the value they negate ("not black", "bina leather") or after it ("black nahi",
# "black ke alawa", "leather ke bina")
NEG_PRE_PHRASES = [("not",), ("no",), ("without",), ("except",), ("excluding",), ("bina",), ("non",)]
NEG_POST_PHRASES = [("ke", "alawa"), ("ke", "alava"), ("ke", "siwa"), ("ke", "siva"), ("ke", "bina"),
                    ("chhod", "ke"), ("chhodkar",), ("nahi",), ("nahin",), ("nai",), ("mat",)]
CLAUSE_SPLIT = re.compile(r"[,;]|\b(?:and|aur|but|par|lekin|magar|also)\b", re.I)
ONLY = {"only", "sirf", "just", "bas", "keval", "sirph"}
CHEAPER = [("aur", "sasta"), ("aur", "sasti"), ("aur", "saste"), ("thoda", "sasta"), ("kam", "price"),
           ("kam", "daam"), ("lower", "price"), ("less", "expensive"), ("cheaper",), ("cheap",), ("sasta",),
           ("sasti",), ("saste",), ("budget",)]
COSTLIER = [("costlier",), ("pricier",), ("more", "expensive"), ("premium",), ("mehenga",), ("mehnga",),
            ("mehengi",), ("better", "quality"), ("acchi", "quality")]
BIGGER = {"bigger", "larger", "bada", "badi", "bade", "zyada", "more capacity", "big", "large", "badaa"}
SMALLER = {"smaller", "chhota", "chota", "chhoti", "choti", "compact", "small", "mini", "less capacity"}
RESET = [("start", "over"), ("new", "search"), ("kuch", "aur"), ("something", "else"), ("naya",), ("reset",)]
JUST_SHOW = [("just", "show"), ("bas", "dikha"), ("bas", "dikhao"), ("show", "all"), ("sab", "dikhao"),
             ("koi", "bhi"), ("any",), ("doesn't", "matter"), ("dont", "care"), ("koi", "farak", "nahi")]


class PlanDelta(BaseModel):
    """A change to the current plan. Also the shape of a clarifier chip's plan_patch."""

    add_filters: list[PlanFilter] = Field(default_factory=list)  # replace any filter on the same field
    exclude: list[PlanFilter] = Field(default_factory=list)  # op "not"
    remove_fields: list[str] = Field(default_factory=list)
    price: dict[str, float] | None = None  # {"lte": ..} / {"gte": ..}: replaces the price range
    sort: PlanSort | None = None
    semantic_text: str | None = None  # replace the search text
    add_keywords: list[str] = Field(default_factory=list)  # append to the search text

    def empty(self) -> bool:
        return not (self.add_filters or self.exclude or self.remove_fields or self.price or self.sort
                    or self.semantic_text or self.add_keywords)


def _has(toks: list[str], phrases: list[tuple[str, ...]]) -> bool:
    for p in phrases:
        n = len(p)
        if any(tuple(toks[i:i + n]) == p for i in range(len(toks) - n + 1)):
            return True
    return False


def wants_just_show(message: str) -> bool:
    return _has(tokenize(message), JUST_SHOW)


_AMBIGUOUS = {"do", "main", "me", "best", "pls", "plz", "ye", "na", "par", "pe"}


def is_hinglish(message: str) -> bool:
    """True when the message uses romanised-Hindi words (function words or translated vocabulary)."""
    from findaro.understand.lexicon import default_lexicon

    hi, en = default_lexicon(("hi-en",)), default_lexicon(("en",))
    for t in tokenize(message):
        if t in _AMBIGUOUS or t in en.function_words:
            continue
        if t in hi.function_words:
            return True
        trans = hi.phrases.get((t,))
        if trans and t not in trans:  # "joote" -> shoes counts; "car" -> car doesn't
            return True
    return _has(tokenize(message), list(hi.cheap) + list(hi.max_after))


# "increase it for 2000", "make it 1500", "2000 tak", "budget badha do 3000": a new price cap for the current search
PRICE_MOVE = {"increase", "raise", "extend", "stretch", "upto", "till", "around", "budget", "badha", "badhao",
              "badhaa", "badhado", "make", "for", "to", "tak", "max", "limit", "within", "under", "below"}


def bare_price(toks: list[str], parsed: QueryPlan) -> float | None:
    """A lone number (no unit) in a refinement, with a price-moving word or on its own: the new price cap."""
    nums = [t for t in toks if re.fullmatch(r"\d{2,7}", t)]
    if len(nums) != 1 or float(nums[0]) < 50:
        return None
    for f in parsed.filters:  # already read as something else ("size 10", "2000 mah")
        if f.origin != "price" and nums[0] in str(f.value):
            return None
    if any(nums[0] in (b.text or "") for b in parsed.boosts):
        return None
    if len(toks) == 1 or any(t in PRICE_MOVE for t in toks):
        return float(nums[0])
    return None


def shown_category(schema: Schema, docs: list[dict[str, Any]]) -> str | None:
    """Deepest category path shared by all shown products (None when they share nothing)."""
    from findaro.index.normalize import category_paths

    spec = next(iter(schema.by_role(Role.category)), None)
    if spec is None or not docs:
        return None
    common: list[str] | None = None
    for doc in docs:
        full, _ = category_paths(doc.get(spec.name), spec.separator)
        if not full:
            return None
        parts = full[0].split(" > ")
        if common is None:
            common = parts
            continue
        shared: list[str] = []
        for a, b in zip(common, parts, strict=False):
            if a != b:
                break
            shared.append(a)
        common = shared
        if not common:
            return None
    return " > ".join(common) if common else None


def classify(message: str, has_plan: bool, has_results: bool, parsed: QueryPlan,
             d: Compiled | None, context_category: str | None = None) -> tuple[TurnType | None, str]:
    """Rules. Returns (type, reason); type None means 'unclear, ask the LLM'."""
    toks = tokenize(message)
    norm = " ".join(toks)
    if not toks or norm in CHITCHAT or (len(toks) <= 3 and all(t in CHITCHAT or t in {"ji", "bhai", "sir"}
                                                               for t in toks)):
        return "chitchat", "greeting/thanks"
    if SMALL_TALK.search(message) and not parsed.filters and not parsed.boosts and not parsed.sort:
        return "chitchat", "small talk"
    if _has(toks, RESET):
        return "new", "reset words"
    if has_results:
        ordinal = any(t in ORDINALS for t in toks) or bool(re.search(r"(#|no\.?|number|option)\s*\d", norm))
        asks = any(t in QUESTION_WORDS for t in toks) or message.strip().endswith("?")
        deictic = any(t in DEICTIC for t in toks)
        if (ordinal and (asks or deictic or len(toks) <= 6)) or (asks and deictic) or (
                asks and toks[0] in QUESTION_WORDS and not parsed.filters and _superlative(toks)):
            return "question", "asks about shown results"
        if asks and _superlative(toks) and not _category_mentioned(parsed):
            return "question", "superlative question about shown results"
    if not has_plan:
        return "new", "no current search"
    if bare_price(toks, parsed) is not None and not _category_mentioned(parsed):
        return "refine", "new price cap"
    constraint = bool(parsed.filters or parsed.sort or parsed.boosts) or any(
        t in BIGGER or t in SMALLER for t in toks) or _has(toks, CHEAPER + COSTLIER) or any(
        t in NEG_BEFORE or t in NEG_AFTER or t in ONLY for t in toks)
    leftover = _leftover_words(parsed, d)
    if _category_mentioned(parsed) and not (toks[0] in REFINE_START or toks[0] in ONLY):
        named = [p for b in parsed.boosts if b.origin == "category"
                 for p in (b.value if isinstance(b.value, list) else [b.value])]
        if context_category and named and all(str(p).lower().startswith(context_category.lower()) for p in named):
            return "refine", "names a category inside the current results"
        return "new", "names a product category"
    if constraint and not leftover:
        return "refine", "only constraints"
    if constraint and len(leftover) <= 2:
        return "refine", "constraints plus a word or two"
    known = d is None or all(d.in_vocab(w) for w in leftover)
    if toks[0] in REFINE_START and len(leftover) <= 3 and known:
        return "refine", "starts like a refinement"
    if parsed.unparsed_tokens and not constraint:
        return "new", "unknown product words"
    if parsed.unparsed_tokens:
        return None, "unknown words with a search in progress"
    if leftover and not constraint:
        return "new", "new product words"
    return None, "mixed constraints and new words"


def _superlative(toks: list[str]) -> bool:
    return any(t.endswith("est") and len(t) > 4 for t in toks) or "sabse" in toks or "most" in toks


def _category_mentioned(parsed: QueryPlan) -> bool:
    return any(b.origin == "category" for b in parsed.boosts)


def _leftover_words(parsed: QueryPlan, d: Compiled | None) -> list[str]:
    """Content words of the message that aren't catalog values, refinement words or numbers."""
    matched = " ".join(str(f.text or "") for f in parsed.filters) + " " + " ".join(
        str(b.text or "") for b in parsed.boosts)
    matched_words = set(matched.split())
    skip = matched_words | ONLY | NEG_BEFORE | NEG_AFTER | BIGGER | SMALLER | REFINE_START | {
        w for p in CHEAPER + COSTLIER for w in p}
    return [w for w in parsed.keywords if w not in skip and not w[0].isdigit()]


# --- refinement ---------------------------------------------------------------------------------------

def _value_spans(toks: list[str], lex: Lexicon, d: Compiled) -> list[tuple[int, int]]:
    """Token spans that name a catalog value or category (longest match first)."""
    from findaro.understand.dictionary import value_key

    spans, i = [], 0
    while i < len(toks):
        for n in range(min(4, len(toks) - i), 0, -1):
            key = value_key(" ".join(toks[i:i + n]), lex)
            if key and (key in d.values or key in d.segments):
                spans.append((i, i + n))
                i += n
                break
        else:
            i += 1
    return spans


def split_negations(message: str, lex: Lexicon, d: Compiled | None) -> tuple[list[str], str]:
    """Returns (negated value phrases, the message without them or their negators).

    A negator applies only to the nearest value in its own clause: "slim fit, black nahi" negates black only."""
    if d is None:
        return [], message
    negated: list[str] = []
    kept: list[str] = []
    for clause in CLAUSE_SPLIT.split(message):
        toks = tokenize(clause)
        spans = _value_spans(toks, lex, d)
        drop: set[int] = set()
        for i in range(len(toks)):
            for phrases, pre in ((NEG_POST_PHRASES, False), (NEG_PRE_PHRASES, True)):
                n = next((len(p) for p in phrases if tuple(toks[i:i + len(p)]) == p), 0)
                if not n or i in drop:
                    continue
                if pre:
                    cands = [sp for sp in spans if sp[0] >= i + n]
                    target = min(cands, default=None)
                else:
                    cands = [sp for sp in spans if sp[1] <= i]
                    target = max(cands, key=lambda sp: sp[1], default=None)
                if target is None:
                    continue
                drop.update(range(i, i + n))
                drop.update(range(*target))
                negated.append(" ".join(toks[target[0]:target[1]]))
                break
        kept.append(" ".join(t for j, t in enumerate(toks) if j not in drop))
    return negated, " ".join(k for k in kept if k)


def quantity_of(value: str, lex: Lexicon) -> tuple[float, str] | None:
    t = tokenize(value)
    if len(t) == 2 and re.fullmatch(r"\d+(\.\d+)?", t[0]) and t[1] in lex.units:
        return float(t[0]), lex.units[t[1]]
    return None


def refine(message: str, plan: QueryPlan, parsed: QueryPlan, schema: Schema, lex: Lexicon, d: Compiled | None,
           last_docs: list[dict[str, Any]]) -> PlanDelta:
    """Rules for the common refinements. Reuses the M2 parse of the message."""
    toks = tokenize(message)
    delta = PlanDelta()
    price_field = primary_price_field(schema)

    # negations: "not black", "black nahi", "black ke alawa", "bina leather" (scoped to the nearest value)
    negated_phrases, positive = split_negations(message, lex, d)
    negated_words: set[str] = set()
    for phrase in negated_phrases:
        sub = validate_plan(RulesParser(schema, lex, d).parse(phrase), schema, d)
        for f in sub.filters:
            if f.op in ("eq", "in"):
                delta.exclude.append(PlanFilter(field=f.field, op="not", value=f.value, origin="chat",
                                                text=f.text, confidence=0.95))
        for b in sub.boosts:
            if b.origin in ("facet", "facet_head", "category", "fuzzy") and not isinstance(b.value, list):
                delta.exclude.append(PlanFilter(field=b.field, op="not", value=b.value, origin="chat",
                                                text=b.text, confidence=0.9))
        negated_words.update(phrase.split())
    if negated_phrases:
        parsed = validate_plan(RulesParser(schema, lex, d).parse(positive), schema, d) if positive.strip() \
            else QueryPlan(query="", semantic_text="")

    # explicit values in the message: "only black", "cotton wala", "men ke liye" -> strict filters
    for f in parsed.filters:
        if f.origin == "price":
            delta.price = dict(f.value)
        elif f.op in ("eq", "in") and not (set((f.text or "").split()) & negated_words):
            delta.add_filters.append(f.model_copy(update={"strict": True, "origin": "chat", "confidence": 0.95}))
    shown_fields = {k for doc in last_docs for k, v in doc.items() if v not in (None, "", [])}
    by_text: dict[str, list] = {}
    for b in parsed.boosts:
        by_text.setdefault(b.text or "", []).append(b)
    for b in parsed.boosts:
        # facet_head ("steel" for "Stainless Steel") only ranks in a search, but "only steel" is explicit
        if b.origin in ("facet", "facet_head", "category") and not (set((b.text or "").split()) & negated_words):
            if b.origin == "category" and isinstance(b.value, list):
                continue
            same = [x for x in by_text.get(b.text or "", []) if x.origin in ("facet", "facet_head")]
            if len(same) > 1 and b.origin in ("facet", "facet_head"):
                # "copper" is both a colour and a material, "5 L" both capacity and volume: keep the one field
                # where the value is most common among the products on screen
                def hits(x) -> int:
                    vals = {str(v).lower() for v in (x.value if isinstance(x.value, list) else [x.value])}
                    return sum(1 for doc in last_docs if str(doc.get(x.field, "")).lower() in vals)
                best = max(same, key=lambda x: (hits(x), x.field in shown_fields, -same.index(x)))
                if b is not best:
                    continue
            delta.add_filters.append(PlanFilter(field=b.field, op="in" if isinstance(b.value, list) else "eq",
                                                value=b.value, strict=True, origin="chat", text=b.text,
                                                confidence=0.9))

    # cheaper / costlier
    shown_prices = [float(p) for p in (doc.get(price_field) for doc in last_docs) if price_field and
                    isinstance(p, int | float)]
    if price_field and not delta.price and (cap := bare_price(toks, parsed)) is not None:
        delta.price = {"lte": cap}
    if price_field and not delta.price:
        if _has(toks, CHEAPER) or (parsed.sort and parsed.sort.order == "asc"):
            cur = _price_cap(plan, price_field)
            if shown_prices:
                new_cap = statistics.median(shown_prices)
                if cur is not None:
                    new_cap = min(new_cap, cur * 0.85)
                delta.price = {"lte": float(int(new_cap))}
            delta.sort = PlanSort(field=price_field, order="asc", mode="soft", text="cheaper")
        elif _has(toks, COSTLIER) or (parsed.sort and parsed.sort.order == "desc"):
            if shown_prices:
                delta.price = {"gte": float(int(statistics.median(shown_prices)))}
            delta.sort = PlanSort(field=price_field, order="desc", mode="soft", text="costlier")

    # bigger / smaller on a quantity-valued attribute of the shown results
    direction = 1 if any(t in BIGGER for t in toks) else -1 if any(t in SMALLER for t in toks) else 0
    if direction and d is not None and last_docs:
        shift = _size_shift(direction, schema, lex, d, last_docs)
        if shift is not None:
            delta.add_filters.append(shift)

    # leftover content words become part of the search text ("for running", "with zip")
    if not delta.add_filters and not delta.exclude and not delta.price and not delta.sort:
        words = [w for w in _leftover_words(parsed, d) if w not in negated_words]
        delta.add_keywords = words
    return delta


def _price_cap(plan: QueryPlan, price_field: str) -> float | None:
    for f in plan.filters:
        if f.field == price_field and f.op == "range" and isinstance(f.value, dict):
            return f.value.get("lte", f.value.get("lt"))
    return None


def _size_shift(direction: int, schema: Schema, lex: Lexicon, d: Compiled, docs: list[dict[str, Any]]):
    best = None
    for spec in schema.fields:
        if spec.role not in (Role.facet,) and spec.role not in NUMBER_ROLES:
            continue
        if spec.role in NUMBER_ROLES and spec.role == Role.price:
            continue
        vals = [doc.get(spec.name) for doc in docs if doc.get(spec.name) is not None]
        if len(vals) < max(2, len(docs) // 2):
            continue
        if spec.role == Role.facet:
            qs = [quantity_of(str(v), lex) for v in vals if not isinstance(v, list)]
            qs = [q for q in qs if q]
            if len(qs) < len(vals) * 0.8 or len({u for _, u in qs}) != 1:
                continue
            unit = qs[0][1]
            med = statistics.median(n for n, _ in qs)
            cands = [(v, quantity_of(v, lex)) for v, _ in d.top_values.get(spec.name, [])]
            keep = [v for v, q in cands if q and q[1] == unit and (q[0] > med if direction > 0 else q[0] < med)]
            if keep and (best is None or len(qs) > best[0]):
                best = (len(qs), PlanFilter(field=spec.name, op="in", value=keep, strict=True, origin="chat",
                                            text="bigger" if direction > 0 else "smaller", confidence=0.8))
    return best[1] if best else None


def apply_delta(plan: QueryPlan, delta: PlanDelta, schema: Schema, d: Compiled | None) -> QueryPlan:
    new = plan.model_copy(deep=True)
    new.relaxations = []
    touched = {f.field for f in delta.add_filters} | set(delta.remove_fields)
    new.filters = [f for f in new.filters if not (f.field in touched and f.op != "not")]
    # a value the user now asks for is no longer excluded, and vice versa
    for f in delta.add_filters:
        vals = set(map(str, f.value if isinstance(f.value, list) else [f.value]))
        new.filters = [x for x in new.filters if not (x.op == "not" and x.field == f.field and
                                                       set(map(str, x.value if isinstance(x.value, list)
                                                               else [x.value])) <= vals)]
    # what the shopper asks for in this turn is the last thing a zero-result search may loosen
    new.filters += [f.model_copy(update={"confidence": max(f.confidence, 0.98)}) for f in delta.add_filters]
    for ex in delta.exclude:
        new.filters = [x for x in new.filters if not (x.field == ex.field and x.op in ("eq", "in") and
                                                       str(x.value) == str(ex.value))]
        new.filters.append(ex)
    if delta.price:
        price_field = primary_price_field(schema)
        if price_field:
            new.filters = [f for f in new.filters if f.field != price_field]
            new.filters.append(PlanFilter(field=price_field, op="range", value=delta.price, strict=True,
                                          origin="price", confidence=0.95, text="price"))
    if delta.sort:
        new.sort = delta.sort
    if delta.semantic_text:
        new.semantic_text = delta.semantic_text
        new.keywords = delta.semantic_text.split()
    if delta.add_keywords:
        new.keywords = [*new.keywords, *[w for w in delta.add_keywords if w not in new.keywords]]
        new.semantic_text = " ".join(new.keywords)
    # boosts for fields now filtered explicitly are redundant
    filtered = {f.field for f in new.filters if f.op != "not" and f.origin != "category_anchor"}
    new.boosts = [b for b in new.boosts if b.field not in filtered]
    return validate_plan(new, schema, d)


def anchor_category(plan: QueryPlan) -> QueryPlan:
    """Once a conversation refines a search, a category the shopper named ("shoes") is a constraint, not just a
    ranking hint: otherwise "only leather" after "black shoes under 1000" ranks leather phone covers first.
    The filter is non-strict, is never loosened by a zero-result search (budget first, then inferred attributes,
    then what was just asked), and stays under the category's own chip (removing that chip removes both)."""
    have = {f.field for f in plan.filters if f.op != "not"}
    # in a conversation the budget is the most flexible constraint (the budget clarifier offers to lift it), so a
    # zero-result search loosens it before any attribute
    plan.filters = [f.model_copy(update={"confidence": min(f.confidence, 0.8)}) if f.origin == "price" else f
                    for f in plan.filters]
    for b in plan.boosts:
        if b.origin == "category" and b.text and b.field not in have:
            plan.filters.append(PlanFilter(field=b.field, op="in" if isinstance(b.value, list) else "eq",
                                           value=b.value, strict=False, confidence=0.97, origin="category_anchor",
                                           text=b.text))
            have.add(b.field)
    return plan


def chip_label(text: str) -> str:
    return re.sub(r"\s*\(\d+\)$", "", fold(text).strip())
