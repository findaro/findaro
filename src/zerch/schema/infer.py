"""Infer field roles from sample documents (name hints + value statistics). Domain-agnostic."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from zerch.schema.model import FieldSpec, Role, Schema, SchemaError, flatten

ID_NAMES = {"id", "_id", "sku", "productid", "itemid", "objectid", "uid", "uuid", "docid", "documentid", "handle"}
TITLE_NAMES = {"title", "name", "productname", "itemname", "heading", "headline", "displayname"}
DESC_NAMES = {"description", "desc", "details", "body", "summary", "about", "overview", "content",
              "longdescription", "shortdescription", "abstract"}
PRICE_TOKENS = {"price", "mrp", "msrp", "cost", "amount", "saleprice", "sellingprice", "listprice", "offerprice"}
CURRENCY_TOKENS = {"currency", "curr", "currencycode"}
CATEGORY_TOKENS = {"category", "categories", "breadcrumb", "breadcrumbs", "taxonomy", "department",
                   "categorypath", "producttype"}
IMAGE_TOKENS = {"image", "images", "img", "thumbnail", "thumb", "photo", "picture", "pic", "imageurl", "imagelink"}
IMAGE_EXT = re.compile(r"\.(jpe?g|png|webp|gif|avif|svg)(\?.*)?$", re.I)
PATH_SEPARATORS = [" > ", " >> ", " / ", " | ", " » ", ">", "/"]
LIST_SEPARATORS = [";", "|"]
ISO_CURRENCIES = {"INR", "USD", "EUR", "GBP", "JPY", "AUD", "CAD", "SGD", "AED", "CNY", "CHF", "SEK", "NZD",
                  "HKD", "ZAR", "BRL", "MXN", "IDR", "THB", "MYR", "PHP", "KRW", "SAR", "BDT", "PKR", "LKR",
                  "NPR"}
# Plain numbers, optionally with a currency symbol/code prefix: "1299", "₹1,299", "Rs. 499", "$12.50".
# Unit suffixes ("5 L", "UK 8") are deliberately not numbers: those are better as facets.
_NUM = re.compile(
    r"^\s*(?:[^\w\s+.-]{1,2}|rs\.?|inr|usd|eur|gbp)?\s*([-+]?(?:\d{1,3}(?:,\d{2,3})+|\d+)(?:\.\d+)?)\s*%?\s*$",
    re.I,
)
_BOOL_TRUE = {"true", "yes", "y", "1", "t"}
_BOOL_FALSE = {"false", "no", "n", "0", "f"}


def parse_number(v: Any) -> float | None:
    if isinstance(v, bool):
        return None
    if isinstance(v, int | float):
        return float(v)
    if isinstance(v, str):
        m = _NUM.match(v)
        if m:
            try:
                return float(m.group(1).replace(",", ""))
            except ValueError:
                return None
    return None


def parse_bool(v: Any) -> bool | None:
    if isinstance(v, bool):
        return v
    if isinstance(v, str):
        s = v.strip().lower()
        if s in _BOOL_TRUE:
            return True
        if s in _BOOL_FALSE:
            return False
    return None


def name_tokens(name: str) -> set[str]:
    """'product_name' -> {'product', 'name', 'productname'}; 'imageURL' -> {'image', 'url', 'imageurl'}."""
    last = name.split(".")[-1]
    parts = re.sub(r"([a-z])([A-Z])", r"\1 \2", last)
    toks = [t.lower() for t in re.split(r"[^A-Za-z0-9]+", parts) if t]
    return set(toks) | {"".join(toks)}


@dataclass
class Stats:
    name: str
    n_docs: int
    values: list[Any] = field(default_factory=list)

    @property
    def presence(self) -> float:
        return len(self.values) / max(1, self.n_docs)


def _strings(values: list[Any]) -> list[str]:
    out = []
    for v in values:
        if isinstance(v, list):
            out.extend(str(x) for x in v if x is not None and not isinstance(x, dict | list))
        elif isinstance(v, str):
            out.append(v)
        elif isinstance(v, int | float) and not isinstance(v, bool):
            out.append(str(v))
    return out


def _is_low_cardinality(strings: list[str], n_values: int) -> bool:
    if not strings:
        return False
    distinct = len(set(s.strip().lower() for s in strings))
    avg_len = sum(len(s) for s in strings) / len(strings)
    if avg_len > 40:
        return False
    if distinct <= 1:
        return n_values >= 2
    if distinct <= 30 and distinct <= 0.6 * len(strings):
        return True
    return distinct <= 0.2 * len(strings) and distinct <= 1000


def _list_separator(strings: list[str]) -> str | None:
    """Detect string-encoded lists like 'S;M;L' (typical in CSV exports)."""
    for sep in LIST_SEPARATORS:
        with_sep = [s for s in strings if sep in s]
        if len(with_sep) >= 0.3 * len(strings):
            parts = [p.strip() for s in strings for p in s.split(sep) if p.strip()]
            if parts and sum(len(p) for p in parts) / len(parts) <= 30 and _is_low_cardinality(parts, len(strings)):
                return sep
    return None


def _path_separator(strings: list[str]) -> str | None:
    for sep in PATH_SEPARATORS:
        hits = sum(1 for s in strings if sep in s and not s.startswith("http"))
        if strings and hits >= 0.5 * len(strings):
            return sep
    return None


def _classify(st: Stats) -> FieldSpec:
    toks = name_tokens(st.name)
    vals = st.values
    name = st.name
    if not vals:
        return FieldSpec(name=name, role=Role.ignore)
    if all(isinstance(v, dict) for v in vals) or any(
        isinstance(v, list) and any(isinstance(x, dict | list) for x in v) for v in vals
    ):
        return FieldSpec(name=name, role=Role.ignore)

    is_list = any(isinstance(v, list) for v in vals)
    strings = _strings(vals)

    # URLs
    if strings and sum(s.startswith(("http://", "https://", "//")) for s in strings) >= 0.9 * len(strings):
        if toks & IMAGE_TOKENS or sum(bool(IMAGE_EXT.search(s)) for s in strings) >= 0.5 * len(strings):
            return FieldSpec(name=name, role=Role.image_url, multi=is_list)
        return FieldSpec(name=name, role=Role.url, multi=is_list)

    scalars = [v for v in vals if not isinstance(v, list)]
    if scalars and not is_list:
        bools = [parse_bool(v) for v in scalars]
        if all(isinstance(v, bool) for v in scalars) or (
            all(b is not None for b in bools) and {str(v).strip().lower() for v in scalars} - {"0", "1"}
        ):
            return FieldSpec(name=name, role=Role.boolean)
        nums = [parse_number(v) for v in scalars]
        if sum(n is not None for n in nums) >= 0.95 * len(scalars):
            if toks & PRICE_TOKENS:
                return FieldSpec(name=name, role=Role.price)
            return FieldSpec(name=name, role=Role.numeric)

    if toks & CURRENCY_TOKENS or (
        strings and all(s.strip().upper() in ISO_CURRENCIES for s in strings) and len(set(strings)) <= 5
    ):
        return FieldSpec(name=name, role=Role.currency)

    if strings:
        sep = _path_separator(strings)
        if toks & CATEGORY_TOKENS:
            return FieldSpec(name=name, role=Role.category, multi=is_list, separator=sep or " > ")
        if sep in (" > ", " >> ", " » ") or (sep == ">" and _is_low_cardinality(strings, len(vals))):
            return FieldSpec(name=name, role=Role.category, multi=is_list, separator=sep)

    if is_list:
        if _is_low_cardinality(strings, len(vals)):
            return FieldSpec(name=name, role=Role.facet, multi=True)
        avg = sum(len(s) for s in strings) / max(1, len(strings))
        return FieldSpec(name=name, role=Role.text if avg > 40 else Role.keyword, multi=True)

    if not strings:
        return FieldSpec(name=name, role=Role.ignore)
    list_sep = _list_separator(strings)
    if list_sep:
        return FieldSpec(name=name, role=Role.facet, multi=True, separator=list_sep)
    if _is_low_cardinality(strings, len(vals)):
        return FieldSpec(name=name, role=Role.facet)
    avg_len = sum(len(s) for s in strings) / len(strings)
    if avg_len > 60:
        return FieldSpec(name=name, role=Role.text)
    return FieldSpec(name=name, role=Role.keyword)


def _collect(docs: list[dict[str, Any]], only: set[str] | None = None) -> dict[str, Stats]:
    stats: dict[str, Stats] = {}
    flat_docs = [flatten(d) for d in docs]
    for d in flat_docs:
        for k, v in d.items():
            if only is not None and k not in only:
                continue
            st = stats.setdefault(k, Stats(name=k, n_docs=len(flat_docs)))
            if v is None or v == "" or v == []:
                continue
            st.values.append(v)
    return stats


def _avg_len(st: Stats) -> float:
    s = _strings(st.values)
    return sum(len(x) for x in s) / max(1, len(s))


def _uniqueness(st: Stats) -> float:
    s = [str(v) for v in st.values if not isinstance(v, list)]
    return len(set(s)) / max(1, len(s))


def _pick_id(stats: dict[str, Stats]) -> str:
    def ok(st: Stats) -> bool:
        scalars = [v for v in st.values if not isinstance(v, list | dict)]
        return st.presence == 1.0 and len(scalars) == len(st.values) and _uniqueness(st) == 1.0

    named = [st for st in stats.values() if name_tokens(st.name) & ID_NAMES or st.name.lower().endswith("_id")]
    named.sort(key=lambda st: (st.name.lower() not in ("id", "_id"), "." in st.name, len(st.name)))
    for st in named:
        if ok(st):
            return st.name
    for st in stats.values():
        if ok(st) and _avg_len(st) <= 40 and "id" in st.name.lower():
            return st.name
    raise SchemaError(
        "could not infer the id field: no field is present and unique in every document. "
        "Add an 'id' field or set the schema with PUT /v1/projects/{id}/schema"
    )


def _assign_text_roles(specs: dict[str, FieldSpec], stats: dict[str, Stats]) -> None:
    """Exactly one title (if any candidate) and at most one description."""
    text_like = [n for n, s in specs.items() if s.role in (Role.keyword, Role.text, Role.facet) and not s.multi]

    def take(n: str, role: Role) -> None:
        specs[n] = FieldSpec(name=n, role=role)

    title = next((n for n in text_like if name_tokens(n) & {"title"}), None) or next(
        (n for n in text_like if name_tokens(n) & TITLE_NAMES and specs[n].role != Role.facet), None
    )
    if title is None:
        cands = [n for n in text_like if specs[n].role in (Role.keyword, Role.text)
                 and 10 <= _avg_len(stats[n]) <= 150 and _uniqueness(stats[n]) >= 0.5]
        cands.sort(key=lambda n: (-stats[n].presence, -_uniqueness(stats[n]), _avg_len(stats[n])))
        title = cands[0] if cands else None
    if title:
        take(title, Role.title)

    desc = next((n for n in text_like if n != title and name_tokens(n) & DESC_NAMES), None)
    if desc is None:
        longs = [n for n in text_like if n != title and specs[n].role == Role.text]
        longs.sort(key=lambda n: -_avg_len(stats[n]))
        desc = longs[0] if longs else None
    if desc:
        take(desc, Role.description)
    for n in text_like:
        if n not in (title, desc) and name_tokens(n) & DESC_NAMES and specs[n].role == Role.keyword:
            take(n, Role.text)


def infer_schema(docs: list[dict[str, Any]], sample_limit: int = 5000) -> Schema:
    if not docs:
        raise SchemaError("cannot infer a schema from zero documents")
    sample = docs[:sample_limit]
    stats = _collect(sample)
    id_name = _pick_id(stats)
    specs: dict[str, FieldSpec] = {}
    for name, st in stats.items():
        specs[name] = FieldSpec(name=name, role=Role.id) if name == id_name else _classify(st)
    _assign_text_roles(specs, stats)
    return Schema.build(list(specs.values()), inferred=True, sample_size=len(sample))


def infer_fields(docs: list[dict[str, Any]], names: set[str]) -> list[FieldSpec]:
    """Roles for fields first seen after the schema exists (additive schema evolution)."""
    stats = _collect(docs, only=names)
    return [_classify(st) for st in stats.values()]
