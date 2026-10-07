from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


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


class SearchResponse(BaseModel):
    query: str
    total: int
    page: int
    size: int
    hits: list[Hit]
    facets: dict[str, Any]
    took_ms: float
    cached: bool = False
