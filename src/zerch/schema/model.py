"""Project schema: one role per field. The index mapping, normalisation and query building are all
derived from it, so the engine never needs to know what kind of catalog it is serving."""

from __future__ import annotations

import hashlib
import re
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field, ValidationError, model_validator


class SchemaError(ValueError):
    pass


class Role(StrEnum):
    id = "id"
    title = "title"
    description = "description"
    text = "text"  # other long free text
    facet = "facet"  # low-cardinality string(s): filterable, faceted, searchable
    keyword = "keyword"  # high-cardinality short string(s): filterable, searchable, not faceted
    numeric = "numeric"
    price = "price"
    currency = "currency"
    category = "category"  # hierarchical path, e.g. "A > B > C"
    boolean = "boolean"
    image_url = "image_url"
    url = "url"
    ignore = "ignore"  # stored and returned, not indexed


# role -> (searchable, filterable, facet, sortable, default weight)
ROLE_DEFAULTS: dict[Role, tuple[bool, bool, bool, bool, float]] = {
    Role.id: (False, True, False, True, 0.0),
    Role.title: (True, False, False, False, 3.0),
    Role.description: (True, False, False, False, 1.0),
    Role.text: (True, False, False, False, 0.5),
    Role.facet: (True, True, True, True, 1.5),
    Role.keyword: (True, True, False, True, 1.0),
    Role.numeric: (False, True, False, True, 0.0),
    Role.price: (False, True, True, True, 0.0),
    Role.currency: (False, True, False, False, 0.0),
    Role.category: (True, True, True, False, 2.0),
    Role.boolean: (False, True, True, False, 0.0),
    Role.image_url: (False, False, False, False, 0.0),
    Role.url: (False, False, False, False, 0.0),
    Role.ignore: (False, False, False, False, 0.0),
}

TEXT_ROLES = {Role.title, Role.description, Role.text}
STRING_VALUE_ROLES = {Role.facet, Role.keyword, Role.currency, Role.id}
NUMBER_ROLES = {Role.numeric, Role.price}
INDEXED_ROLES = set(Role) - {Role.image_url, Role.url, Role.ignore}

_SAFE = re.compile(r"[^A-Za-z0-9_]")


def index_key(name: str) -> str:
    """Stable OpenSearch-safe property name for a user field name."""
    safe = _SAFE.sub("_", name)[:60] or "f"
    if safe != name:
        safe = f"{safe}_{hashlib.sha1(name.encode()).hexdigest()[:6]}"
    return safe


class FieldSpec(BaseModel):
    name: str
    role: Role
    multi: bool = False  # values may be lists
    separator: str | None = None  # category path separator, or list separator for string-encoded lists
    searchable: bool | None = None
    filterable: bool | None = None
    facet: bool | None = None
    sortable: bool | None = None
    weight: float | None = None

    @model_validator(mode="after")
    def _apply_defaults(self) -> FieldSpec:
        s, f, fa, so, w = ROLE_DEFAULTS[self.role]
        if self.searchable is None:
            self.searchable = s
        if self.filterable is None:
            self.filterable = f
        if self.facet is None:
            self.facet = fa
        if self.sortable is None:
            self.sortable = so and not self.multi
        if self.weight is None:
            self.weight = w
        if self.role not in INDEXED_ROLES:
            self.searchable = self.filterable = self.facet = self.sortable = False
        if self.role in TEXT_ROLES:
            self.filterable = self.facet = self.sortable = False
        return self

    @property
    def key(self) -> str:
        return index_key(self.name)


class Schema(BaseModel):
    fields: list[FieldSpec]
    inferred: bool = True
    sample_size: int | None = None

    @model_validator(mode="after")
    def _validate(self) -> Schema:
        names = [f.name for f in self.fields]
        if len(names) != len(set(names)):
            raise SchemaError("duplicate field names in schema")
        ids = [f for f in self.fields if f.role == Role.id]
        if len(ids) != 1:
            raise SchemaError(f"schema needs exactly one field with role 'id' (found {len(ids)})")
        if ids[0].multi:
            raise SchemaError("the id field cannot be multi-valued")
        keys = [f.key for f in self.fields]
        if len(keys) != len(set(keys)):
            raise SchemaError("field names collide after sanitisation")
        return self

    @classmethod
    def build(cls, fields: list[FieldSpec], **kw: Any) -> Schema:
        """Construct, turning validation failures into a readable SchemaError."""
        try:
            return cls(fields=fields, **kw)
        except ValidationError as e:
            msgs = "; ".join(str(x["msg"]).removeprefix("Value error, ") for x in e.errors())
            raise SchemaError(msgs) from e

    @property
    def id_field(self) -> FieldSpec:
        return next(f for f in self.fields if f.role == Role.id)

    def get(self, name: str) -> FieldSpec | None:
        return next((f for f in self.fields if f.name == name), None)

    def by_role(self, *roles: Role) -> list[FieldSpec]:
        return [f for f in self.fields if f.role in roles]

    def with_fields(self, extra: list[FieldSpec]) -> Schema:
        return Schema.build([*self.fields, *extra], inferred=self.inferred, sample_size=self.sample_size)

    def public(self) -> dict[str, Any]:
        return self.model_dump(mode="json")


class SchemaUpdate(BaseModel):
    """Body of PUT /schema: full field list (roles/flags), same shape GET returns."""

    fields: list[FieldSpec] = Field(min_length=1)


def flatten(doc: dict[str, Any], prefix: str = "", out: dict[str, Any] | None = None) -> dict[str, Any]:
    """Flatten nested objects to dotted keys. Lists are kept as values."""
    out = {} if out is None else out
    for k, v in doc.items():
        name = f"{prefix}{k}"
        if isinstance(v, dict):
            flatten(v, f"{name}.", out)
        else:
            out[name] = v
    return out
