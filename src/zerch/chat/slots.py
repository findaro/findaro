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
              "sabse mehenga", "sabse mehnga", "sabse mehengi", "zyada price", "zyada daam")
MAX_SIZE = ("largest", "biggest", "heaviest", "longest", "most capacity", "sabse bada", "sabse badi",
            "sabse bade", "sabse zyada capacity")
MIN_SIZE = ("smallest", "lightest", "shortest", "least capacity", "sabse chhota", "sabse chhoti", "sabse chota",
            "sabse choti", "sabse halka", "sabse halki")
TOP_RATING = ("highest rated", "highest rating", "best rated", "top rated", "top-rated", "best rating",
              "most popular", "best", "sabse accha", "sabse achha", "sabse acchi", "sabse badhiya", "better")


def _has_any(text: str, words: tuple[str, ...]) -> bool:
    return any(re.search(rf"(?<![a-z]){re.escape(w)}(?![a-z])", text) for w in words)


class SlotFiller:
    def __init__(self, docs: dict[str, dict[str, Any]], schema: Schema, currency_symbol: str = "",
                 facts: dict[str, str] | None = None):
        """`facts`: {"low_price": id, "high_price": id, "top_rating": id} computed in code."""
        self.docs = docs
        self.schema = schema
        self.symbol = currency_symbol
        self.facts = facts or {}
        self.dropped: list[tuple[str, str]] = []  # (sentence, reason), for debugging/eval
        self.filled = 0

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
        for cid in cited:
            if cid not in self.docs:
                return None, f"cites unknown product {cid}"
        stripped = SLOT.sub(" ", CITE.sub(" ", sentence))
        if DIGIT.search(stripped):
            return None, "number written by the model"
        if "{" in stripped or "}" in stripped:
            return None, "malformed slot"
        slot_ids = {m.group(2) for m in SLOT.finditer(sentence)}
        if slot_ids - set(cited):
            return None, "slot for a product the sentence doesn't cite"
        low = stripped.lower()
        if "#" in stripped:
            return None, "masked number copied"
        for words, fact in ((LOW_PRICE, "low_price"), (HIGH_PRICE, "high_price"), (TOP_RATING, "top_rating"),
                            (MAX_SIZE, "max_size"), (MIN_SIZE, "min_size")):
            if _has_any(low, words) and (fact not in self.facts or set(cited) != {self.facts[fact]}):
                return None, f"comparison not backed by computed fact {fact}"
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

        out = SLOT.sub(sub, sentence)
        return (None, "slot value missing") if bad else (out, "")

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
