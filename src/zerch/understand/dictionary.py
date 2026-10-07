"""Per-project value dictionary: facet values, category path segments, and the corpus vocabulary.

Built from the indexed documents after each ingest job (and lazily on first use), stored in Postgres,
compiled in memory per data_version. This is what lets the query parser recognise "black", "men",
"5 L" or "pressure cooker" without knowing anything about the catalog in advance.
"""

from __future__ import annotations

import time
import zlib
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Any

import orjson
from opensearchpy import AsyncOpenSearch, NotFoundError

from zerch.schema.model import Role, Schema
from zerch.understand.lexicon import Lexicon, singular, tokenize

MAX_VALUES_PER_FIELD = 2000
MAX_VOCAB = 100_000
SCAN_LIMIT = 200_000


def value_key(text: str, lex: Lexicon) -> str:
    """Canonical matching key shared by query n-grams and catalog values.

    '5 L' / '5 litre' / '5l' -> '5 l'; 'USB-C' -> 'usb c'; 'Pressure Cookers' -> 'pressure cooker'."""
    out = []
    for t in tokenize(text.replace("-", " ")):
        if not any(c.isalnum() for c in t):
            continue
        t = t.replace("'", "")
        unit = lex.units.get(t)
        out.append(unit if unit and out and out[-1].replace(".", "").isdigit() else singular(t))
    return " ".join(out)


@dataclass
class Compiled:
    data_version: int
    n_docs: int
    coverage: dict[str, float]
    # key -> [(field, stored value, count)]
    values: dict[str, list[tuple[str, str, int]]]
    # key -> [(field, path prefix, count)]
    segments: dict[str, list[tuple[str, str, int]]]
    vocab: dict[str, int]
    # field -> {lowercased value -> stored value}
    canon: dict[str, dict[str, str]]
    top_values: dict[str, list[tuple[str, int]]]
    single_word_keys: dict[str, list[str]] = field(default_factory=dict)  # first letter -> keys (fuzzy)
    currency: str | None = None
    _buckets: dict[tuple[str, int], list[str]] | None = None

    def vocab_buckets(self) -> dict[tuple[str, int], list[str]]:
        if self._buckets is None:
            b: dict[tuple[str, int], list[str]] = defaultdict(list)
            for v in self.vocab:
                if v:
                    b[(v[0], len(v))].append(v)
            self._buckets = dict(b)
        return self._buckets

    def canonical_value(self, fld: str, value: str) -> str | None:
        table = self.canon.get(fld)
        if table is None:
            return None
        v = table.get(value.strip().lower())
        if v is not None:
            return v
        # category prefixes are stored with " > "; accept other spacing
        return table.get(" > ".join(p.strip() for p in value.lower().split(">")))

    def in_vocab(self, tok: str) -> bool:
        return singular(tok) in self.vocab or tok in self.vocab


async def build_payload(os: AsyncOpenSearch, index: str, schema: Schema, data_version: int) -> dict[str, Any]:
    """Scan the index once and collect value counts, coverage and vocabulary."""
    t0 = time.perf_counter()
    facet_fields = [f for f in schema.fields if f.role in (Role.facet, Role.keyword, Role.currency) and f.filterable]
    cat_fields = schema.by_role(Role.category)
    text_fields = [f for f in schema.fields if f.searchable]
    values: dict[str, Counter] = {f.name: Counter() for f in facet_fields}
    paths: dict[str, Counter] = {f.name: Counter() for f in cat_fields}
    present: Counter = Counter()
    vocab: Counter = Counter()
    n = 0
    try:
        resp = await os.search(index=index, scroll="1m", size=1000,
                               body={"query": {"match_all": {}}, "_source": ["f", "zz_path"]})
    except NotFoundError:
        resp = {"hits": {"hits": []}}
    scroll_id = resp.get("_scroll_id")
    try:
        while (hits := resp["hits"]["hits"]) and n < SCAN_LIMIT:
            for h in hits:
                n += 1
                src = h["_source"]
                f = src.get("f", {})
                toks: set[str] = set()
                for spec in schema.fields:
                    v = f.get(spec.key)
                    if v is None:
                        continue
                    present[spec.name] += 1
                    vals = v if isinstance(v, list) else [v]
                    if spec.name in values:
                        values[spec.name].update(str(x) for x in vals)
                    if spec in text_fields:
                        for x in vals:
                            toks.update(singular(t) for t in tokenize(str(x)) if any(c.isalpha() for c in t))
                for spec in cat_fields:
                    pv = src.get("zz_path", {}).get(spec.key)
                    if pv:
                        paths[spec.name].update(pv if isinstance(pv, list) else [pv])
                vocab.update(toks)
            if not scroll_id:
                break
            resp = await os.scroll(scroll_id=scroll_id, scroll="1m")
            scroll_id = resp.get("_scroll_id", scroll_id)
    finally:
        if scroll_id:
            await os.clear_scroll(scroll_id=scroll_id, ignore=(404,))
    return {
        "data_version": data_version,
        "n_docs": n,
        "coverage": {k: c / n for k, c in present.items()} if n else {},
        "values": {k: c.most_common(MAX_VALUES_PER_FIELD) for k, c in values.items()},
        "paths": {k: c.most_common(MAX_VALUES_PER_FIELD) for k, c in paths.items()},
        "vocab": dict(vocab.most_common(MAX_VOCAB)),
        "build_ms": round((time.perf_counter() - t0) * 1000, 1),
    }


def pack(payload: dict[str, Any]) -> bytes:
    return zlib.compress(orjson.dumps(payload), 6)


def unpack(blob: bytes) -> dict[str, Any]:
    return orjson.loads(zlib.decompress(blob))


def compile_payload(payload: dict[str, Any], schema: Schema, lex: Lexicon) -> Compiled:
    values: dict[str, list[tuple[str, str, int]]] = defaultdict(list)
    canon: dict[str, dict[str, str]] = defaultdict(dict)
    top: dict[str, list[tuple[str, int]]] = {}
    currency = None
    for fname, pairs in payload.get("values", {}).items():
        spec = schema.get(fname)
        if spec is None:
            continue
        top[fname] = [(v, c) for v, c in pairs]
        for v, c in pairs:
            canon[fname].setdefault(v.lower(), v)
            if spec.role == Role.currency:
                currency = currency or v
                continue
            if spec.role == Role.keyword:
                continue  # high-cardinality: lookup only, not matched against queries
            k = value_key(v, lex)
            if len(k) < 2 or k.replace(" ", "").replace(".", "").isdigit() or k in lex.function_words:
                continue
            values[k].append((fname, v, c))
    segments: dict[str, list[tuple[str, str, int]]] = defaultdict(list)
    for fname, pairs in payload.get("paths", {}).items():
        top[fname] = [(p, c) for p, c in pairs]
        for p, c in pairs:
            canon[fname].setdefault(p.lower(), p)
            seg = p.split(" > ")[-1]
            k = value_key(seg, lex)
            if len(k) >= 3 and k not in lex.function_words:
                segments[k].append((fname, p, c))
    single: dict[str, list[str]] = defaultdict(list)
    for k in values:
        if " " not in k and len(k) >= 5 and k.isalpha():
            single[k[0]].append(k)
    return Compiled(
        data_version=payload.get("data_version", 0), n_docs=payload.get("n_docs", 0),
        coverage=payload.get("coverage", {}), values=dict(values), segments=dict(segments),
        vocab=payload.get("vocab", {}), canon=dict(canon), top_values=top, single_word_keys=dict(single),
        currency=currency,
    )


def levenshtein(a: str, b: str, limit: int) -> int:
    """Edit distance with adjacent transpositions (optimal string alignment); stops early past `limit`."""
    if abs(len(a) - len(b)) > limit:
        return limit + 1
    prev2: list[int] = []
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            v = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb))
            if i > 1 and j > 1 and ca == b[j - 2] and a[i - 2] == cb:
                v = min(v, prev2[j - 2] + 1)
            cur.append(v)
        if min(cur) > limit:
            return limit + 1
        prev2, prev = prev, cur
    return prev[-1]


# --- storage -------------------------------------------------------------------------------------------

async def refresh(state: Any, pid: str) -> dict[str, Any] | None:
    """Rebuild and store the dictionary for a project from its live index."""
    from sqlalchemy.dialects.postgresql import insert as pg_insert

    from zerch import store
    from zerch.db import project_dicts
    from zerch.index.ops import alias_name

    project = await store.get_project(state.db, pid)
    schema = store.load_schema(project["schema"]) if project else None
    if schema is None:
        return None
    payload = await build_payload(state.os, alias_name(state.settings.index_prefix, pid), schema,
                                  project["data_version"])
    blob = pack(payload)
    stmt = pg_insert(project_dicts).values(project_id=pid, data_version=project["data_version"], payload=blob)
    stmt = stmt.on_conflict_do_update(index_elements=["project_id"],
                                      set_={"data_version": stmt.excluded.data_version,
                                            "payload": stmt.excluded.payload, "built_at": store.now()})
    async with state.db.begin() as conn:
        await conn.execute(stmt)
    return payload


async def load_row(state: Any, pid: str) -> tuple[int, dict[str, Any]] | None:
    from sqlalchemy import select

    from zerch.db import project_dicts

    async with state.db.connect() as conn:
        row = (await conn.execute(select(project_dicts.c.data_version, project_dicts.c.payload)
                                  .where(project_dicts.c.project_id == pid))).first()
    return (row[0], unpack(row[1])) if row else None
