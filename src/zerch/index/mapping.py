"""Index layout derived from a Schema.

Document shape in OpenSearch:
    zz_id     keyword   document id
    zz_raw    object    original document, returned as-is (not indexed)
    zz_all    text      catch-all of searchable fields (+ .phon subfield)
    zz_vec    knn_vector
    zz_ehash  keyword   hash of the embedded text (lets reindex reuse vectors)
    zz_path.<key>       category prefixes ("A", "A > B", "A > B > C")
    f.<key>             normalised field values, typed by role
"""

from __future__ import annotations

from typing import Any

from zerch.index.analysis import analysis_settings
from zerch.schema.model import FieldSpec, Role, Schema

TEXT = {"type": "text", "analyzer": "zerch_text", "search_analyzer": "zerch_text_search"}


def field_mapping(f: FieldSpec) -> dict[str, Any] | None:
    copy = {"copy_to": ["zz_all"]} if f.searchable else {}
    match f.role:
        case Role.title | Role.description | Role.text:
            return {**TEXT, **copy}
        case Role.facet | Role.keyword | Role.currency | Role.id:
            m: dict[str, Any] = {
                "type": "keyword",
                "ignore_above": 512,
                "fields": {"norm": {"type": "keyword", "normalizer": "zerch_lower", "ignore_above": 512}},
                **copy,
            }
            if f.searchable:
                m["fields"]["text"] = dict(TEXT)
            return m
        case Role.category:
            return {"type": "keyword", "ignore_above": 1024,
                    "fields": {"text": dict(TEXT), "norm": {"type": "keyword", "normalizer": "zerch_lower"}}, **copy}
        case Role.numeric | Role.price:
            return {"type": "double"}
        case Role.boolean:
            return {"type": "boolean"}
        case _:
            return None


def properties(schema: Schema) -> dict[str, Any]:
    f_props = {}
    path_props = {}
    for f in schema.fields:
        m = field_mapping(f)
        if m is None:
            continue
        f_props[f.key] = m
        if f.role == Role.category:
            path_props[f.key] = {"type": "keyword",
                                 "fields": {"norm": {"type": "keyword", "normalizer": "zerch_lower"}}}
    return {"f": {"properties": f_props}, "zz_path": {"properties": path_props}}


def index_body(schema: Schema, dim: int, shards: int = 1) -> dict[str, Any]:
    props = properties(schema)
    return {
        "settings": {
            "index": {"number_of_shards": shards, "number_of_replicas": 0, "knn": True, "refresh_interval": "1s",
                      "max_result_window": 10_000},
            **analysis_settings(),
        },
        "mappings": {
            "dynamic": "strict",
            "properties": {
                "zz_id": {"type": "keyword"},
                "zz_raw": {"type": "object", "enabled": False},
                "zz_ehash": {"type": "keyword", "index": False},
                "zz_all": {
                    **TEXT,
                    "fields": {"phon": {"type": "text", "analyzer": "zerch_phonetic",
                                        "search_analyzer": "zerch_phonetic_search"}},
                },
                "zz_vec": {
                    "type": "knn_vector",
                    "dimension": dim,
                    "method": {"name": "hnsw", "engine": "lucene", "space_type": "cosinesimil",
                               "parameters": {"m": 16, "ef_construction": 128}},
                },
                **props,
            },
        },
    }
