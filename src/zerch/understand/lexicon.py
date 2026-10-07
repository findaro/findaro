"""Locale packs (packs/locales/*.yaml): function words, price/sort phrases, units, word translations.

Packs are language resources. Nothing here knows about a particular catalog.
"""

from __future__ import annotations

import os
import re
import unicodedata
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import yaml

_DEFAULT_DIRS = [
    Path(__file__).resolve().parents[3] / "packs" / "locales",  # repo checkout
    Path("/app/packs/locales"),  # docker image
]

Phrase = tuple[str, ...]


def fold(text: str) -> str:
    """Lowercase + strip accents; keep ₹ as a currency word."""
    text = text.replace("₹", " rs ")
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    return text.lower()


# numbers (1,299 / 1.5 / 2k), words with inner hyphens/apostrophes (usb-c, men's), lone '+' and '-'
_TOKEN = re.compile(r"\d[\d,]*(?:\.\d+)?(?:k(?![a-z]))?|[a-z0-9]+(?:['’-][a-z0-9]+)*|[+\-\"]|/-")
_GLUED = re.compile(r"^(\d+(?:\.\d+)?)([a-z]+)$")  # 5kg, 65w, 1.5l, 20000mah, 500rs


def tokenize(text: str) -> list[str]:
    out: list[str] = []
    for t in _TOKEN.findall(fold(text)):
        t = t.replace("’", "'")
        if t.endswith("'s"):
            t = t[:-2]
        cur = re.fullmatch(r"(rs|inr)(\d+(?:\.\d+)?)", t)
        if cur:
            out.extend([cur.group(1), cur.group(2)])
            continue
        m = _GLUED.match(t)
        if m and not re.fullmatch(r"\d+(?:\.\d+)?k", t):  # keep "2k"/"4k" whole
            out.extend([m.group(1), m.group(2)])
        else:
            out.append(t.replace(",", "") if t[0].isdigit() else t)
    return out


def singular(tok: str) -> str:
    """Very light English plural folding, used only for matching keys."""
    if len(tok) <= 3 or tok[-1] != "s" or tok.endswith(("ss", "us", "is")):
        return tok
    if tok.endswith("ies") and len(tok) > 4:
        return tok[:-3] + "y"
    if tok.endswith(("ches", "shes", "xes", "zes", "ses")):
        return tok[:-2]
    return tok[:-1]


def match_key(text: str) -> str:
    """Canonical key for comparing query n-grams with catalog values: folded, alnum only, singular."""
    toks = [singular(t) for t in re.findall(r"[a-z0-9]+", fold(text))]
    return " ".join(toks)


@dataclass
class Lexicon:
    function_words: set[str] = field(default_factory=set)
    currency: set[Phrase] = field(default_factory=set)
    max_before: set[Phrase] = field(default_factory=set)
    max_after: set[Phrase] = field(default_factory=set)
    min_before: set[Phrase] = field(default_factory=set)
    min_after: set[Phrase] = field(default_factory=set)
    range_open: set[Phrase] = field(default_factory=set)
    range_join: set[Phrase] = field(default_factory=set)
    cheap: set[Phrase] = field(default_factory=set)
    expensive: set[Phrase] = field(default_factory=set)
    units: dict[str, str] = field(default_factory=dict)  # alias -> canonical unit
    unit_field_hints: dict[str, set[str]] = field(default_factory=dict)
    phrases: dict[Phrase, list[str]] = field(default_factory=dict)  # source phrase -> english tokens
    max_phrase_len: int = 1
    packs: list[str] = field(default_factory=list)

    def known(self, tok: str) -> bool:
        return tok in self.function_words or (tok,) in self.phrases or tok in self.units


def _phr(s: str) -> Phrase:
    return tuple(tokenize(str(s))) or (str(s),)


def load_lexicon(names: list[str], dirs: list[Path] | None = None) -> Lexicon:
    lex = Lexicon()
    search = list(dirs or [])
    env = os.environ.get("ZERCH_PACKS_DIR")
    if env:
        search.append(Path(env) / "locales")
    search += _DEFAULT_DIRS
    for name in names:
        path = next((d / f"{name}.yaml" for d in search if (d / f"{name}.yaml").exists()), None)
        if path is None:
            raise FileNotFoundError(f"locale pack {name!r} not found in {[str(d) for d in search]}")
        data = yaml.safe_load(path.read_text()) or {}
        lex.packs.append(name)
        lex.function_words |= {str(w).lower() for w in data.get("function_words", [])}
        price = data.get("price", {}) or {}
        for key in ("currency", "max_before", "max_after", "min_before", "min_after", "range_open", "range_join"):
            getattr(lex, key).update(_phr(p) for p in price.get(key, []))
        lex.cheap |= {_phr(p) for p in data.get("cheap", [])}
        lex.expensive |= {_phr(p) for p in data.get("expensive", [])}
        for canon, aliases in (data.get("units") or {}).items():
            for a in aliases:
                lex.units[str(a).lower()] = str(canon)
        for canon, hints in (data.get("unit_field_hints") or {}).items():
            lex.unit_field_hints.setdefault(str(canon), set()).update(str(h).lower() for h in hints)
        for src, dst in (data.get("phrases") or {}).items():
            lex.phrases[_phr(src)] = str(dst).split()
    all_phrases = [*lex.phrases, *lex.cheap, *lex.expensive, *lex.max_after, *lex.max_before, *lex.min_after,
                   *lex.min_before]
    lex.max_phrase_len = max((len(p) for p in all_phrases), default=1)
    return lex


@lru_cache
def default_lexicon(names: tuple[str, ...] = ("en", "hi-en")) -> Lexicon:
    return load_lexicon(list(names))
