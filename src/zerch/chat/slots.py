"""Numbers never come from the LLM.

The answer model writes slots such as {price:GR-00182}, {rating:EL-00128} or {capacity:HK-00087}; the server
fills them from that product's fields. The model's text is checked one sentence at a time before it is
streamed, and a sentence that fails any check is dropped whole (dropping half a sentence changes its meaning):

- a slot naming an unknown product, an unknown field, or a field the product doesn't have
- a slot for a product the sentence doesn't cite as [ID] (values attributed to the wrong product)
- a citation [ID] for a product that isn't on screen
- any digit the model wrote itself (outside a slot or citation)
- a comparison ("cheapest", "highest rated", "sabse sasta"...) about a product other than the one the
  server computed for that comparison
- an uncited sentence that asserts an attribute value, product type or stock status (unverifiable)
- "all / sabhi / both / dono" claims that don't hold for every product they cover
- a product-type name that doesn't fit the cited product ("bluetooth earbuds" for a neckband)
"""

from __future__ import annotations

import re
from collections.abc import AsyncIterator, Iterable
from typing import Any

from zerch.schema.model import Role, Schema

SLOT = re.compile(r"\{\s*([A-Za-z_][\w.]*)\s*:\s*([^{}\s]+)\s*\}")
CITE = re.compile(r"\[([^\[\]\s]+)\]")
SENTENCE_END = re.compile(r"[.!?।](?=\s)|\n")
DIGIT = re.compile(r"\d")

# comparison words -> which computed fact may back them
LOW_PRICE = ("cheapest", "cheaper", "lowest price", "least expensive", "most affordable", "more affordable",
             "budget-friendly", "sabse sasta", "sabse sasti", "sabse saste", "sabse kam", "kam price", "kam daam")
HIGH_PRICE = ("most expensive", "costliest", "priciest", "highest price", "more expensive", "premium",
              "sabse mehenga", "sabse mehnga", "sabse mehengi", "sabse mahanga", "sabse mahangi", "mahanga",
              "mehenga", "mehnga", "zyada price", "zyada daam")
MAX_SIZE = ("largest", "biggest", "heaviest", "longest", "most capacity", "sabse bada", "sabse badi",
            "sabse bade", "sabse zyada capacity")
MIN_SIZE = ("smallest", "lightest", "shortest", "least capacity", "sabse chhota", "sabse chhoti", "sabse chota",
            "sabse choti", "sabse halka", "sabse halki")
TOP_RATING = ("highest rated", "highest rating", "best rated", "top rated", "top-rated", "best rating",
              "most popular", "best", "sabse accha", "sabse achha", "sabse acchi", "sabse badhiya", "better")


def _has_any(text: str, words: tuple[str, ...]) -> bool:
    return any(re.search(rf"(?<![a-z]){re.escape(w)}(?![a-z])", text) for w in words)


GENERIC_LOW = re.compile(r"\b(lowest|cheapest|least expensive)\b")
GENERIC_HIGH = re.compile(r"\b(highest|costliest|priciest|most expensive)\b")
RATING_WORDS = re.compile(r"\b(rating|rated|ratings|review|reviews)\b")
SIZE_WORDS = re.compile(r"\b(capacity|size|weight|length|volume|wattage|largest|smallest|biggest)\b")
# yes/no suitability verdicts ("you can wear it in the rain", "pehen sakti hai", "waterproof"): never a listing fact
SUITABILITY = re.compile(r"\b(can|could|may|should) (safely |easily |still )?(be )?(wear|worn|use|used)\b|"
                         r"\b(suitable|ideal|perfect|good|great|fine|okay|ok|safe) "
                         r"(for|to (wear|use|be worn|be used))\b|"
                         r"\bwaterproof\b|\bke liye (to |toh )?(theek|thik|sahi|accha|achha|acha|perfect|badhiya)\b|"
                         r"\bwater[- ]?(resistant|proof)\b|\b(pehen|pahen|use kar|istemaal kar|istemal kar|"
                         r"le ja)\s*(sakt[aie]|sakte)\b|\bchal (jayega|jaayega|jayegi|jaayegi)\b")
# return / refund / replacement / exchange: each one the sentence names must be one the listing names
# ("10-day replacement" doesn't mean "you can return it")
AFTER_SALE = re.compile(r"\b(return|refund|replac|exchang)\w*")
IDIOMS = re.compile(r"\b(it'?s |it is )?best (to|if|way|practice)\b|\ball the best\b|\bat best\b")
DEICTIC = re.compile(r"\b(this|these|that one|it is|it's|its|yeh|ye|iska|iski|iske|isme|ise|isse|the product)\b")
UNIVERSAL = re.compile(r"\b(all|every|each|sabhi|sab|saare|saari|sare|sari)\b")
DUAL = re.compile(r"\b(both|dono)\b")
IN_STOCK = re.compile(r"\bin stock\b|\bstock (mein|me|main) (hai|hain|available)\b|\bavailable\b|\buplabdh\b")
# Hindi superlatives: "sabse adhik/zyada rating", "sabse kam daam"
HI_MOST = re.compile(r"\bsabse (adhik|zyada|jyada|ziada|uncha|unchi|ooncha|badhiya)\b")
HI_LEAST = re.compile(r"\bsabse (kam|neeche|nicha)\b")
PRICE_WORDS = re.compile(r"\b(price|priced|daam|dam|keemat|kimat|cost|costs|rupaye|rs)\b")
STOCK_ANY = re.compile(r"\bstock\b")
NUMBER_WORDS = re.compile(r"\b(two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|dozen|teen|chaar|char|"
                          r"paanch|panch|chhe|saat|aath|nau|das)\b")
ORDINALS = {"first": 0, "1st": 0, "pehla": 0, "pehli": 0, "pehle": 0, "second": 1, "2nd": 1, "dusra": 1,
            "dusri": 1, "doosra": 1, "dusre": 1, "third": 2, "3rd": 2, "teesra": 2, "teesri": 2, "tisra": 2,
            "fourth": 3, "4th": 3, "chautha": 3, "fifth": 4, "5th": 4}
NOT_AVAILABLE = re.compile(r"\b(not (shown|listed|available|mentioned|given|provided|specified|stated)|unknown|"
                           r"(hasn't|has not|haven't|have not|isn't|is not|doesn't|does not|didn't|did not) "
                           r"(explicitly |specifically |clearly |actually )?(been )?"
                           r"(list|listed|mention|mentioned|say|said|specify|specified|state|stated|provide|"
                           r"provided|include|included)|no (information|mention|details?)|"
                           r"nahi (diya|di|hai|mila|mili|bataya|likha)|pata nahi)\b")


def _key(text: str) -> str:
    from zerch.understand.lexicon import match_key

    return match_key(text)


class SlotFiller:
    def __init__(self, docs: dict[str, dict[str, Any]], schema: Schema, currency_symbol: str = "",
                 facts: dict[str, str] | None = None, order: list[str] | None = None,
                 focus: list[str] | None = None, known_values: dict[str, set[str]] | None = None):
        """`facts`: {"low_price": id, "high_price": id, "top_rating": id} computed in code.
        `order`: product ids in the order the user sees them, so "the second one" counts as citing it."""
        self.order = order or list(docs)
        # product conversation: with one product in focus, a sentence without [ID] is about that product
        self.focus = [f for f in (focus or []) if f in docs]
        # value key -> fields, for every value this catalog uses (so "made in India" is recognised as an origin
        # claim even when no product on screen is from India)
        self.known_values = known_values or {}
        self.docs = docs
        self.schema = schema
        self.symbol = currency_symbol
        self.facts = facts or {}
        self.dropped: list[tuple[str, str]] = []  # (sentence, reason), for debugging/eval
        self.filled = 0
        self._index_values()

    def _index_values(self) -> None:
        """Attribute values and product-type names of the shown products, for checking model-written claims."""
        facets = [f.name for f in self.schema.fields if f.role == Role.facet]
        cat = next(iter(self.schema.by_role(Role.category)), None)
        title = next(iter(self.schema.by_role(Role.title)), None)
        self._stock = next((f.name for f in self.schema.by_role(Role.boolean) if "stock" in f.name.lower()), None)
        self._doc_vals: dict[str, dict[str, set[str]]] = {}
        self._title_key: dict[str, str] = {}
        self.value_fields: dict[str, set[str]] = {}  # value key -> fields ("__type__" = category leaf)
        for did, doc in self.docs.items():
            vals: dict[str, set[str]] = {}
            for f in facets:
                v = doc.get(f)
                keys = {_key(str(x)) for x in (v if isinstance(v, list) else [v]) if x not in (None, "")}
                vals[f] = {k for k in keys if len(k) >= 3 and not k.replace(" ", "").isdigit()}
            if cat is not None and doc.get(cat.name):
                vals["__type__"] = {_key(str(doc[cat.name]).split(">")[-1])}
            self._doc_vals[did] = vals
            self._title_key[did] = " " + _key(str(doc.get(title.name, ""))) + " " if title else " "
            for f, keys in vals.items():
                for k in keys:
                    self.value_fields.setdefault(k, set()).add(f)
        # leading title word of each product, usually its brand ("Kosmo Copper Water Bottle" -> "kosmo")
        self._brand = {did: (t.split() or [""])[0] for did, t in self._title_key.items()}

    _NUM = re.compile(r"\d[\d,]*(?:\.\d+)?")

    def _numbers_listed(self, text: str, cited: list[str]) -> bool:
        """Every number in `text` appears in a cited product's own fields (e.g. "6 months" from its warranty)."""
        if not cited:
            return False
        listed: set[str] = set()
        for did in cited:
            for v in self.docs.get(did, {}).values():
                for x in v if isinstance(v, list) else [v]:
                    if isinstance(x, bool) or x is None:
                        continue
                    for n in self._NUM.findall(str(x)):
                        n = n.replace(",", "")
                        listed.add(n.rstrip("0").rstrip(".") if "." in n else n)
        for n in self._NUM.findall(text):
            n = n.replace(",", "").rstrip(".,")
            if (n.rstrip("0").rstrip(".") if "." in n else n) not in listed:
                return False
        return True

    def _text_key(self, did: str) -> str:
        """All of a product's text (title, description, care, Q&A...) as one match key, cached."""
        cache = self.__dict__.setdefault("_text_cache", {})
        if did not in cache:
            cache[did] = " " + _key(" ".join(str(v) for v in self.docs.get(did, {}).values()
                                             if isinstance(v, str))) + " "
        return cache[did]

    def _mentions(self, text: str) -> set[tuple[str, str]]:
        t = " " + _key(text) + " "
        return {(f, k) for k, fields in self.value_fields.items() if f" {k} " in t for f in fields}

    def _claims_ok(self, low: str, cited: list[str]) -> str:
        """'' if the model's own words make only checkable, true claims; else the reason to drop."""
        mentions = self._mentions(low)
        stock_claim = bool(IN_STOCK.search(low))
        if cited and (na := NOT_AVAILABLE.search(low)):  # "rating is not shown" when the product has a rating
            # "the description doesn't mention rain" talks about the field's content, it doesn't call it missing
            active = re.match(r"(doesn't|does not|didn't|did not|no) ", na.group(0)) is not None
            for f in self.schema.fields:
                if not any(self.docs.get(d, {}).get(f.name) not in (None, "", []) for d in cited):
                    continue
                for m in re.finditer(rf"\b{re.escape(f.name.replace('_', ' ').lower())}s?\b", low.replace("_", " ")):
                    if m.start() > na.start() or not active:
                        return f"says {f.name} is missing but it is shown"
        t = " " + _key(low) + " "
        cited_brands = {self._brand.get(d, "") for d in cited}
        words = t.split()
        for did, brand in self._brand.items():  # another product's name used for the cited one
            if len(brand) < 4 or brand in cited_brands or did in cited or \
                    any(f" {brand} " in self._title_key.get(c, "") for c in cited):
                continue
            if any(w == brand or (w.startswith(brand) and len(w) - len(brand) <= 4) for w in words):
                return "names a product the sentence doesn't cite"
        if not cited:
            if mentions or STOCK_ANY.search(low):
                return "uncited claim about products"
            return ""
        types = {k for f, k in mentions if f == "__type__"}
        if types:  # every cited product must be one of the named types (by category or title)
            for did in cited:
                own = self._doc_vals.get(did, {}).get("__type__", set())
                if not any(k in own or f" {k} " in self._title_key.get(did, "") for k in types):
                    return "product type doesn't match the cited product"
        universal, dual = UNIVERSAL.search(low), DUAL.search(low)
        if universal or dual:
            scope = cited if dual and not universal and len(set(cited)) >= 2 else list(self.docs)
            for f, k in mentions:
                if not all(k in self._doc_vals.get(d, {}).get(f, set()) for d in scope):
                    return f"'all' claim not true for every product ({k})"
            if stock_claim and self._stock and not all(self.docs[d].get(self._stock) is True for d in scope):
                return "'all in stock' not true for every product"
        else:
            if stock_claim and self._stock and not all(self.docs[d].get(self._stock) is True for d in cited):
                return "stock claim not supported"
            for f, k in mentions:  # each attribute value named must belong to a cited product
                if f != "__type__" and not any(k in self._doc_vals.get(d, {}).get(f, set()) or
                                               f" {k} " in self._title_key.get(d, "") for d in cited):
                    return f"attribute '{k}' doesn't belong to the cited product"
            # values the catalog uses for some field (an origin, colour, material...), named for a product that
            # neither lists that value nor uses it anywhere in its own text
            t = " " + _key(low) + " "
            for k, fields in self.known_values.items():
                if f" {k} " in t and not any(
                        any(k in vals for vals in self._doc_vals.get(d, {}).values()) or f" {k} " in self._text_key(d)
                        for d in cited):
                    return f"names a {sorted(fields)[0]} value the listing doesn't give ({k})"
        return ""

    def _field(self, name: str):
        name = name.lower()
        for f in self.schema.fields:
            if f.name.lower() == name:
                return f
        if name in ("name", "product"):
            return next(iter(self.schema.by_role(Role.title)), None)
        return None

    def _format(self, spec, value: Any) -> str | None:
        if value is None or value == "" or value == []:
            return None
        if isinstance(value, list):
            return ", ".join(str(v) for v in value)
        if spec.role == Role.price:
            n = float(value) if isinstance(value, int | float) and not isinstance(value, bool) else None
            if n is None:
                from zerch.schema.infer import parse_number

                n = parse_number(value)
            if n is None:
                return None
            return f"{self.symbol}{n:,.0f}" if n == int(n) else f"{self.symbol}{n:,.2f}"
        if isinstance(value, bool):
            return "yes" if value else "no"
        if isinstance(value, float):
            return f"{value:g}"
        return str(value)

    def check(self, sentence: str) -> tuple[str | None, str]:
        """Return (filled sentence, "") or (None, reason it was dropped)."""
        cited = CITE.findall(sentence)
        if not cited and len(self.focus) == 1:
            cited = list(self.focus)
        for word, pos in ORDINALS.items():  # "the second one" refers to a shown product
            if re.search(rf"\b{word}\b", sentence.lower()) and pos < len(self.order):
                cited.append(self.order[pos])
        if not cited:  # a product named by its full title instead of [ID]
            s_key = " " + _key(sentence) + " "
            cited = [did for did, tk in self._title_key.items() if len(tk.strip()) >= 12 and tk in s_key]
        for cid in cited:
            if cid not in self.docs:
                return None, f"cites unknown product {cid}"
        stripped = SLOT.sub(" ", CITE.sub(" ", sentence))
        if DIGIT.search(stripped) and not self._numbers_listed(stripped, cited):
            return None, "number written by the model"
        if "{" in stripped or "}" in stripped:
            return None, "malformed slot"
        slot_ids = {m.group(2) for m in SLOT.finditer(sentence)}
        if slot_ids - set(cited):
            return None, "slot for a product the sentence doesn't cite"
        low = stripped.lower()
        if "#" in stripped:
            return None, "masked number copied"
        if NUMBER_WORDS.search(low):
            return None, "count written by the model"
        low = IDIOMS.sub(" ", low)  # "it's best to check" is advice, not a ranking
        kinds = {fact for words, fact in ((LOW_PRICE, "low_price"), (HIGH_PRICE, "high_price"),
                                          (TOP_RATING, "top_rating"), (MAX_SIZE, "max_size"), (MIN_SIZE, "min_size"))
                 if _has_any(low, words)}
        if RATING_WORDS.search(low) and (GENERIC_HIGH.search(low) or HI_MOST.search(low)):
            kinds.add("top_rating")
        elif PRICE_WORDS.search(low) and HI_MOST.search(low):
            kinds.add("high_price")
        if PRICE_WORDS.search(low) and HI_LEAST.search(low):
            kinds.add("low_price")
        elif not SIZE_WORDS.search(low):
            if GENERIC_LOW.search(low):
                kinds.add("low_price")
            if GENERIC_HIGH.search(low):
                kinds.add("high_price")
        if kinds:
            ids = {self.facts.get(k) for k in kinds}
            if None in ids or not cited or set(cited) - ids or ids - set(cited):
                return None, f"comparison not backed by computed facts {sorted(kinds)}"
        reason = self._claims_ok(low, cited)
        if reason:
            return None, reason
        if self.focus and SUITABILITY.search(low) and not self._quotes_listing(low, cited):
            return None, "suitability verdict the listing doesn't give"
        if cited and not NOT_AVAILABLE.search(low):
            said = {m.group(1) for m in AFTER_SALE.finditer(re.sub(r"\breturn polic(y|ies)\b", " ", low))}
            listed = " ".join(self._text_key(d) for d in cited)
            if missing := sorted(w for w in said if not re.search(rf"\b{w}", listed)):
                return None, f"after-sale promise the listing doesn't give ({missing[0]})"
        bad = False

        def sub(m: re.Match) -> str:
            nonlocal bad
            spec, did = self._field(m.group(1)), m.group(2)
            doc = self.docs.get(did)
            text = self._format(spec, doc.get(spec.name)) if spec is not None and doc is not None else None
            if text is None:
                bad = True
                return ""
            self.filled += 1
            return text

        filled: list[str] = []

        def sub_and_record(m: re.Match) -> str:
            text = sub(m)
            filled.append(text)
            return text

        out = SLOT.sub(sub_and_record, sentence)
        if bad:
            return None, "slot value missing"
        # the model often repeats what the slot already contains: "₹{price:X}" -> "₹₹499", "{volume:X} L" -> "5 L L"
        if self.symbol:
            out = out.replace(self.symbol + self.symbol, self.symbol)
        for v in filled:
            last = v.split()[-1] if v.split() else ""
            if last.isalpha():
                out = re.sub(rf"{re.escape(v)}\s+{re.escape(last)}\b", v, out)
        return out, ""

    def _quotes_listing(self, low: str, cited: list[str]) -> bool:
        """True when the verdict is the listing's own words (e.g. "perfect for daily wear" from the description)."""
        for did in cited:
            listing = " ".join(re.findall(r"[a-z]+", " ".join(
                str(v) for v in self.docs.get(did, {}).values() if isinstance(v, str)).lower()))
            for m in SUITABILITY.finditer(low):
                phrase = re.findall(r"[a-z]+", low[m.start():m.end() + 25])[:5]
                if len(phrase) >= 3 and " ".join(phrase) in listing:
                    return True
        return False

    def check_general(self, sentence: str) -> tuple[str | None, str]:
        """General know-how ("suede doesn't like water"): no numbers, slots, citations or product names, and any
        claim about "this one" must hold for the focused product."""
        if CITE.search(sentence) or SLOT.search(sentence) or "{" in sentence:
            return None, "general part refers to a product"
        if DIGIT.search(sentence) or "#" in sentence or NUMBER_WORDS.search(sentence.lower()):
            return None, "number in general part"
        low = sentence.lower()
        t = " " + _key(low) + " "
        if any(len(b) >= 4 and (f" {b} " in t) for b in self._brand.values()):
            return None, "general part names a product"
        if _has_any(low, LOW_PRICE + HIGH_PRICE + TOP_RATING + MAX_SIZE + MIN_SIZE) or GENERIC_LOW.search(low) \
                or GENERIC_HIGH.search(low):
            return None, "comparison in general part"
        if DEICTIC.search(low):  # "this one is leather", "yeh India mein bana hai": must be true of the focus
            reason = self._claims_ok(low, list(self.focus)) if self.focus else "general part refers to a product"
            if reason:
                return None, reason
        return sentence, ""

    async def stream_parts(self, chunks: AsyncIterator[str] | Iterable[str],
                           marker: str = "General:") -> AsyncIterator[tuple[str, str]]:
        """Like stream(), but splits the answer at `marker`: yields ("answer", text) then ("general", text)."""
        mode, buf, mk = "answer", "", marker.lower()

        async def source():
            if hasattr(chunks, "__aiter__"):
                async for c in chunks:  # type: ignore[union-attr]
                    yield c
            else:
                for c in chunks:  # type: ignore[union-attr]
                    yield c

        def emit(sentence: str, part: str) -> str | None:
            if not sentence.strip():
                return sentence
            out, reason = self.check(sentence) if part == "answer" else self.check_general(sentence)
            if out is None:
                self.dropped.append((sentence.strip(), reason))
            return out

        label = re.compile(r"\bpart\s*[12]\s*[:.)-]\s*", re.I)
        async for chunk in source():
            buf += chunk
            # small models sometimes label the parts themselves: "Part 1: …", "Part 2: …"
            buf = re.sub(r"\bpart\s*2\s*[:.)-]", marker, buf, flags=re.I)
            buf = label.sub("", buf) if not re.search(r"part\s*\d?\s*$", buf, re.I) else buf
            if mode == "answer" and (idx := buf.lower().find(mk)) >= 0:
                head, buf, mode = buf[:idx], buf[idx + len(mk):], "general"
                while (cut := self._boundary(head)) is not None:
                    sentence, head = head[:cut], head[cut:]
                    if (out := emit(sentence, "answer")):
                        yield "answer", out
                if (out := emit(head, "answer")):
                    yield "answer", out
            while (cut := self._boundary(buf)) is not None:
                sentence, buf = buf[:cut], buf[cut:]
                if (out := emit(sentence, mode)):
                    yield mode, out
        if buf and (out := emit(buf, mode)):
            yield mode, out

    async def stream(self, chunks: AsyncIterator[str] | Iterable[str]) -> AsyncIterator[str]:
        buf = ""

        async def source():
            if hasattr(chunks, "__aiter__"):
                async for c in chunks:  # type: ignore[union-attr]
                    yield c
            else:
                for c in chunks:  # type: ignore[union-attr]
                    yield c

        async for chunk in source():
            buf += chunk
            while (cut := self._boundary(buf)) is not None:
                sentence, buf = buf[:cut], buf[cut:]
                out = self._emit(sentence)
                if out:
                    yield out
        if buf:
            out = self._emit(buf)
            if out:
                yield out

    @staticmethod
    def _boundary(buf: str) -> int | None:
        depth = 0
        for i, ch in enumerate(buf):
            if ch in "{[":
                depth += 1
            elif ch in "}]":
                depth = max(0, depth - 1)
            elif depth == 0 and SENTENCE_END.match(buf, i) and i + 1 < len(buf):
                return i + 1
        return None

    def _emit(self, sentence: str) -> str | None:
        if not sentence.strip():
            return sentence
        out, reason = self.check(sentence)
        if out is None:
            self.dropped.append((sentence.strip(), reason))
            return None
        return out
