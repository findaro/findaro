from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from zerch.understand.patch import PatchOp


class SortItem(BaseModel):
    field: str
    order: Literal["asc", "desc"] = "asc"


class SearchRequest(BaseModel):
    """POST /v1/search. M2 will add query understanding that compiles into these same filters/sort."""

    query: str = Field("", max_length=512)
    filters: dict[str, Any] = Field(default_factory=dict)
    sort: list[SortItem] | None = None
    page: int = Field(1, ge=1)
    size: int = Field(20, ge=1, le=100)
    facets: list[str] | None = None  # None = every facet-enabled field
    facet_size: int = Field(20, ge=1, le=200)
    highlight: bool = True
    understand: bool = True  # parse the query into filters/sort/boosts (M2); false = plain M1 retrieval
    # structured edits applied to the understood plan (remove a chip, set price range, sort, add a filter)
    patch: list[PatchOp] = Field(default_factory=list)
    debug: bool = False  # include the full plan, per-stage timings and retrieval signals

    @field_validator("sort", mode="before")
    @classmethod
    def _parse_sort(cls, v: Any) -> Any:
        """Accept "price:asc", "-price", ["price:asc", ...] or [{"field": ..., "order": ...}]."""
        if v is None or v == "":
            return None
        items = v if isinstance(v, list) else [v]
        out = []
        for it in items:
            if isinstance(it, str):
                s = it.strip()
                if s.startswith("-"):
                    out.append({"field": s[1:], "order": "desc"})
                elif ":" in s:
                    f, o = s.rsplit(":", 1)
                    out.append({"field": f, "order": o.lower()})
                else:
                    out.append({"field": s, "order": "asc"})
            else:
                out.append(it)
        return out


class Hit(BaseModel):
    id: str
    score: float
    document: dict[str, Any]
    highlights: dict[str, str] | None = None


class Chip(BaseModel):
    """One thing the engine understood, ready to show (and let the user remove) in a search UI."""

    label: str  # e.g. "Under ₹500", "Black", "Men", "Pressure Cookers", "Lower prices first"
    kind: Literal["filter", "boost", "sort"]
    field: str
    op: str  # eq | in | range | asc | desc
    value: Any = None
    source: str  # words in the query it came from, when known
    confidence: float
    remove: list[PatchOp] = Field(default_factory=list)  # send as `patch` to drop this chip


class PillValue(BaseModel):
    value: Any
    label: str
    count: int
    patch: list[PatchOp]  # send as `patch` to apply this value


class Pill(BaseModel):
    """Passive refinement choices for one attribute of the current results (a UI renders them as pills)."""

    field: str
    label: str
    values: list[PillValue]


class Display(BaseModel):
    """Which document fields a UI should use for a product card (from the schema's inferred roles)."""

    id: str | None = None
    title: str | None = None
    price: str | None = None
    compare_at_price: str | None = None  # e.g. MRP, when the catalog has a second price field
    currency: str | None = None  # ISO code, e.g. INR
    image: str | None = None
    url: str | None = None
    rating: str | None = None
    rating_count: str | None = None
    in_stock: str | None = None


class RelaxedFilter(BaseModel):
    field: str
    value: Any
    label: str
    reason: str


class Understood(BaseModel):
    query: str
    semantic_text: str
    chips: list[Chip] = Field(default_factory=list)
    relaxations: list[RelaxedFilter] = Field(default_factory=list)
    match_quality: Literal["good", "weak", "none"] = "good"
    source: Literal["rules", "llm", "cache", "off"] = "off"
    # Results on this page that match the query but not every inferred attribute (shown after exact matches
    # when exact matches don't fill the page). Their ids are listed so a UI can label them.
    close_matches: list[str] = Field(default_factory=list)


class SearchResponse(BaseModel):
    query: str
    total: int
    page: int
    size: int
    hits: list[Hit]
    facets: dict[str, Any]
    took_ms: float
    understood: Understood | None = None
    pills: list[Pill] = Field(default_factory=list)
    display: Display | None = None
    debug: dict[str, Any] | None = None
    cached: bool = False
