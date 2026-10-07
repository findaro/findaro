"""Rules path: fast, deterministic query parsing. Always runs.

Order: price constraints -> sort intent -> locale phrase translation -> function words -> catalog value
matching (facets, quantities, category segments) -> unparsed-token detection.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from zerch.schema.model import Role, Schema
from zerch.understand.dictionary import Compiled, levenshtein, value_key
from zerch.understand.lexicon import Lexicon, Phrase, fold, singular, tokenize
from zerch.understand.plan import PlanBoost, PlanFilter, PlanSort, QueryPlan, primary_price_field

_NUM = re.compile(r"^\d+(?:\.\d+)?k?$")
# An inferred attribute becomes a (non-strict) filter only when the field is common in the catalog;
# on rare fields it is a boost.
MIN_FILTER_COVERAGE = 0.25


@dataclass
class Tok:
    text: str
    role: str | None = None  # price | sort | func | currency | unit
    translated: list[str] | None = None  # English words standing in for this token (or phrase)
    expansions: list[str] | None = None  # extra synonyms: optional for lexical, added to the vector text
    matched: bool = False  # recognised as a catalog value / category
    quantity: tuple[float, str] | None = None


def _is_num(t: str) -> bool:
    return bool(_NUM.match(t))


def _num(t: str) -> float:
    return float(t[:-1]) * 1000 if t.endswith("k") else float(t)


def _match(texts: list[str], i: int, phrases: set[Phrase], maxlen: int) -> int:
    """Length of the longest phrase in `phrases` starting at i (0 if none)."""
    for n in range(min(maxlen, len(texts) - i), 0, -1):
        if tuple(texts[i : i + n]) in phrases:
            return n
    return 0


class RulesParser:
    def __init__(self, schema: Schema, lex: Lexicon, dictionary: Compiled | None):
        self.schema, self.lex, self.d = schema, lex, dictionary
        self.price_field = primary_price_field(schema)
        self.maxlen = lex.max_phrase_len

    # ---------------------------------------------------------------- price
    def _skip_currency(self, texts: list[str], k: int, toks: list[Tok]) -> int:
        n = _match(texts, k, self.lex.currency, 2)
        for j in range(k, k + n):
            toks[j].role = "currency"
        return k + n

    def _prices(self, toks: list[Tok], filters: list[PlanFilter]) -> None:
        texts = [t.text for t in toks]
        lex = self.lex

        def free(j: int) -> bool:
            return 0 <= j < len(toks) and toks[j].role is None

        def price_num(j: int) -> bool:
            return free(j) and _is_num(texts[j]) and toks[j].quantity is None

        def cur(j: int) -> int:
            """Skip currency words at j; returns the next index."""
            n = _match(texts, j, lex.currency, 2) if free(j) else 0
            for k in range(j, j + n):
                toks[k].role = "currency"
            return j + n

        def currency_near(j: int) -> bool:
            if _match(texts, j + 1, lex.currency, 2):
                return True
            return any(_match(texts, s, lex.currency, 2) == j - s for s in range(max(0, j - 2), j))

        def emit(lo: float | None, hi: float | None, start: int, end: int, conf: float) -> int:
            while start > 0 and toks[start - 1].role is None and _match(texts, start - 1, lex.currency, 1):
                start -= 1
            for k in range(start, end):
                if toks[k].role in (None, "currency"):
                    toks[k].role = "price"
            if self.price_field is not None:
                rng = {k: v for k, v in (("gte", lo), ("lte", hi)) if v is not None}
                filters.append(PlanFilter(field=self.price_field, op="range", value=rng, strict=True,
                                          confidence=conf, origin="price", text=" ".join(texts[start:end])))
            return end

        def tail(j: int) -> int:
            j = cur(j)
            return j + _match(texts, j, {("tak",)}, 1)

        def range_open(i: int) -> int | None:  # between X and Y / from X to Y
            n = _match(texts, i, lex.range_open, 2) if free(i) else 0
            if not n:
                return None
            a = cur(i + n)
            if not price_num(a):
                return None
            j = cur(a + 1)
            m = _match(texts, j, lex.range_join, 2)
            b = cur(j + m) if m else -1
            if not (m and price_num(b)):
                return None
            lo, hi = sorted((_num(texts[a]), _num(texts[b])))
            return emit(lo, hi, i, tail(b + 1), 0.95)

        def range_bare(i: int) -> int | None:  # X to Y / X - Y / X se Y
            if not price_num(i):
                return None
            j = cur(i + 1)
            m = _match(texts, j, lex.range_join, 2)
            b = cur(j + m) if m else -1
            if not (m and price_num(b)):
                return None
            if texts[j] == "se" and _match(texts, b + 1, lex.max_after, self.maxlen):
                return None
            x, y = _num(texts[i]), _num(texts[b])
            evidence = currency_near(i) or currency_near(b) or texts[i].endswith("k") or (
                texts[j] in ("to", "se") and min(x, y) >= 100)
            if not evidence or x == y:
                return None
            return emit(min(x, y), max(x, y), i, tail(b + 1), 0.9)

        def before(i: int) -> int | None:  # under X / above X
            if not free(i):
                return None
            for phrases, is_max in ((lex.max_before, True), (lex.min_before, False)):
                n = _match(texts, i, phrases, self.maxlen)
                if n:
                    j = cur(i + n)
                    if price_num(j):
                        v = _num(texts[j])
                        return emit(None if is_max else v, v if is_max else None, i, cur(j + 1), 0.95)
            return None

        def after(i: int) -> int | None:  # X and below / X ke andar / X se zyada
            if not price_num(i):
                return None
            j = cur(i + 1)
            for phrases, is_max in ((lex.max_after, True), (lex.min_after, False)):
                n = _match(texts, j, phrases, self.maxlen)
                if n:
                    v = _num(texts[i])
                    return emit(None if is_max else v, v if is_max else None, i, j + n, 0.95)
            return None

        def bare(i: int) -> int | None:  # "rs 500 shoes", "2k earbuds" -> upper bound
            if not price_num(i) or not (currency_near(i) or texts[i].endswith("k")):
                return None
            start = i
            while start > 0 and _match(texts, start - 1, lex.currency, 1):
                start -= 1
            return emit(None, _num(texts[i]), start, cur(i + 1), 0.75)

        i = 0
        while i < len(toks):
            end = range_open(i) or range_bare(i) or before(i) or after(i) or bare(i)
            i = end if end else i + 1

    # ---------------------------------------------------------------- parse
    def parse(self, query: str) -> QueryPlan:
        lex, d = self.lex, self.d
        toks = [Tok(t) for t in tokenize(query)]
        texts = [t.text for t in toks]
        filters: list[PlanFilter] = []
        boosts: list[PlanBoost] = []
        sort: PlanSort | None = None

        # 1. quantities: number + unit is never a price
        for i in range(len(toks) - 1):
            if _is_num(texts[i]) and not texts[i].endswith("k") and texts[i + 1] in lex.units:
                toks[i].quantity = (float(texts[i]), lex.units[texts[i + 1]])
                toks[i + 1].role = "unit"

        # 2. price constraints
        self._prices(toks, filters)

        # 3. sort intent (cheap / premium)
        texts = [t.text for t in toks]
        for i in range(len(toks)):
            if toks[i].role is not None:
                continue
            for phrases, order in ((lex.cheap, "asc"), (lex.expensive, "desc")):
                n = _match(texts, i, phrases, self.maxlen)
                if n and all(toks[j].role is None for j in range(i, i + n)):
                    for j in range(i, i + n):
                        toks[j].role = "sort"
                    if sort is None and self.price_field:
                        sort = PlanSort(field=self.price_field, order=order, mode="soft", text=" ".join(texts[i:i + n]))
                    break

        # 4. locale phrase translation (longest phrase first). A single word the catalog itself uses
        #    ("garam" in "Garam Masala") is left alone unless its entry is a synonym expansion.
        i = 0
        while i < len(toks):
            if toks[i].role is not None:
                i += 1
                continue
            n = 0
            for m in range(min(self.maxlen, len(toks) - i), 0, -1):
                if all(toks[j].role is None for j in range(i, i + m)) and tuple(texts[i : i + m]) in lex.phrases:
                    n = m
                    break
            if not n:
                i += 1
                continue
            words = lex.phrases[tuple(texts[i : i + n])]
            if n == 1:
                orig = texts[i]
                if orig in words:  # expansion: keep the word, add synonyms
                    toks[i].translated = [orig]
                    toks[i].expansions = [w for w in words if w != orig]
                elif d is not None and d.in_vocab(orig):
                    i += 1
                    continue
                else:
                    # main word: the translation the catalog actually uses (a facet value, else a corpus word)
                    def rank(w: str) -> int:
                        if d is None:
                            return 2
                        k = value_key(w, lex)
                        return 0 if k in d.values or k in d.segments else 1 if d.in_vocab(w) else 2
                    main = min(words, key=lambda w: (rank(w), words.index(w)))
                    toks[i].translated = [main]
                    toks[i].expansions = [w for w in words if w != main]
            else:
                toks[i].translated = list(words)
                for j in range(i + 1, i + n):
                    toks[j].role = "merged"
            i += n

        # 5. function words
        for t in toks:
            if t.role is None and t.translated is None and t.text in lex.function_words:
                t.role = "func"
            if t.role is None and not any(c.isalnum() for c in t.text):
                t.role = "func"

        # content terms: (text, source token index)
        terms: list[tuple[str, int]] = []
        expansions: list[str] = []
        for idx, t in enumerate(toks):
            if t.role in ("price", "sort", "func", "currency", "merged", "unit"):
                continue
            if t.translated is not None:
                terms.extend((w, idx) for w in t.translated)
                expansions.extend(w for w in t.expansions or [] if w not in expansions)
            elif t.quantity is not None:
                terms.append((f"{texts[idx]} {texts[idx + 1]}", idx))
            else:
                terms.append((t.text, idx))

        # 6. catalog matching: longest n-gram first, across facet values and category path segments.
        #    On a tie the facet value wins ("men" -> gender, not every "... > Men" category).
        matched_terms: set[int] = set()
        if d is not None:
            filters_by_field: dict[str, PlanFilter] = {}
            j = 0
            while j < len(terms):
                hit = None
                for n in range(min(4, len(terms) - j), 0, -1):
                    key = value_key(" ".join(w for w, _ in terms[j : j + n]), lex)
                    if key in d.values or key in d.segments:
                        hit = (n, key)
                        break
                if hit is None:
                    j += 1
                    continue
                n, key = hit
                words = " ".join(w for w, _ in terms[j : j + n])
                if key in d.values:
                    by_field: dict[str, tuple[str, int]] = {}
                    for fld, val, cnt in d.values[key]:
                        if fld not in by_field or cnt > by_field[fld][1]:
                            by_field[fld] = (val, cnt)
                    if len(by_field) == 1:
                        (fld, (val, _)), = by_field.items()
                        if d.coverage.get(fld, 0.0) >= MIN_FILTER_COVERAGE:
                            prev = filters_by_field.get(fld)
                            if prev is None:
                                filters_by_field[fld] = PlanFilter(field=fld, op="eq", value=val, strict=False,
                                                                   confidence=0.85, origin="facet", text=words)
                            elif val not in (prev.value if isinstance(prev.value, list) else [prev.value]):
                                vals = prev.value if isinstance(prev.value, list) else [prev.value]
                                prev.value, prev.op = [*vals, val], "in"
                        else:
                            boosts.append(PlanBoost(field=fld, value=val, weight=1.0, origin="facet", text=words))
                    else:
                        for fld, (val, _) in by_field.items():
                            boosts.append(PlanBoost(field=fld, value=val, weight=0.6, origin="facet", text=words))
                else:
                    paths_by_field: dict[str, list[str]] = {}
                    for fld, path, _ in d.segments[key]:
                        paths_by_field.setdefault(fld, []).append(path)
                    for fld, paths in paths_by_field.items():
                        boosts.append(PlanBoost(field=fld, value=paths[0] if len(paths) == 1 else paths,
                                                weight=1.5, origin="category", text=words))
                matched_terms.update(range(j, j + n))
                j += n
            filters.extend(filters_by_field.values())

            # fuzzy single-word value matches -> boosts (typos like "wirless")
            for j, (w, _) in enumerate(terms):
                if j in matched_terms or len(w) < 5 or not w.isalpha():
                    continue
                key = singular(w)
                if key in d.values or d.in_vocab(w):
                    continue
                lim = 1 if len(key) < 8 else 2
                for cand in d.single_word_keys.get(key[0], []):
                    if levenshtein(key, cand, lim) <= lim:
                        for fld, val, _ in d.values[cand][:1]:
                            boosts.append(PlanBoost(field=fld, value=val, weight=0.5, origin="fuzzy", text=w))
                        matched_terms.add(j)
                        break

        # 7. unit quantities that matched no value: bind to a numeric field named for the unit
        for j, (w, idx) in enumerate(terms):
            q = toks[idx].quantity
            if q is None or j in matched_terms:
                continue
            hints = lex.unit_field_hints.get(q[1], set())
            for spec in self.schema.by_role(Role.numeric):
                name_toks = set(re.split(r"[^a-z0-9]+", spec.name.lower()))
                if spec.filterable and name_toks & hints:
                    filters.append(PlanFilter(field=spec.name, op="range", value={"gte": q[0], "lte": q[0]},
                                              strict=False, confidence=0.7, origin="quantity", text=w))
                    matched_terms.add(j)
                    break

        # 8. unparsed: words we can't account for (not a translation, value, number or corpus word)
        unparsed = []
        for j, (w, idx) in enumerate(terms):
            t = toks[idx]
            if j in matched_terms or t.translated is not None or t.quantity is not None or _is_num(w):
                continue
            if lex.known(w) or (d is not None and d.in_vocab(w)):
                continue
            if d is not None and len(w) >= 5 and self._fuzzy_vocab(w):
                continue
            if d is None:
                continue
            unparsed.append(w)

        content = [w for w, _ in terms]
        # Words in other scripts (e.g. Devanagari) aren't parsed here; pass them through untouched so the
        # analyzer's transliteration and the multilingual vector model still see them.
        content += [w for w in query.split() if any(c.isalpha() and not c.isascii() for c in w)
                    and not any(c.isascii() and c.isalpha() for c in fold(w))]
        n_content = len({idx for _, idx in terms}) or 1
        confidence = round(1.0 - len(unparsed) / n_content, 3)
        return QueryPlan(query=query, semantic_text=" ".join(content), keywords=content, expansions=expansions,
                         filters=filters, sort=sort, boosts=boosts, unparsed_tokens=unparsed, confidence=confidence,
                         source="rules")

    def _fuzzy_vocab(self, w: str) -> bool:
        key = singular(w)
        lim = 1 if len(key) < 8 else 2
        buckets = self.d.vocab_buckets()
        for n in range(len(key) - lim, len(key) + lim + 1):
            for v in buckets.get((key[0], n), ()):
                if levenshtein(key, v, lim) <= lim:
                    return True
        return False


def describe_price(f: PlanFilter, symbol: str) -> str:
    v = f.value
    lo, hi = v.get("gte", v.get("gt")), v.get("lte", v.get("lt"))

    def money(x: float) -> str:
        return f"{symbol}{int(x):,}" if x == int(x) else f"{symbol}{x:,.2f}"

    if lo is not None and hi is not None:
        return money(lo) if lo == hi else f"{money(lo)} – {money(hi)}"
    if hi is not None:
        return f"Under {money(hi)}"
    return f"Over {money(lo)}"


__all__ = ["RulesParser", "describe_price"]
