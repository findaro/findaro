"""Typed payloads of the /v1/chat Server-Sent Events, published in the OpenAPI spec for SDK generation."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from zerch.search.models import Display, Hit, Pill, Understood
from zerch.understand.patch import PatchOp


class SessionEvent(BaseModel):
    session_id: str
    turn: int


class PlanDeltaView(BaseModel):
    turn_type: Literal["new", "refine", "question", "product", "chitchat"]
    added: list[str] = Field(default_factory=list)
    removed: list[str] = Field(default_factory=list)
    semantic_text: dict[str, str | None] | None = None


class PlanEvent(BaseModel):
    understood: Understood | None
    delta: PlanDeltaView


class ResultsEvent(BaseModel):
    items: list[Hit]
    total: int
    facets: dict[str, Any] = Field(default_factory=dict)
    pills: list[Pill] = Field(default_factory=list)
    match_quality: Literal["good", "weak", "none"] | None
    close_matches: list[str] = Field(default_factory=list)
    unchanged: bool = False  # question / chit-chat turns: the results on screen didn't change
    display: Display | None = None


class ClarifyChipView(BaseModel):
    label: str
    count: int | None = None
    patch: list[PatchOp]  # send as `patch` on the next /v1/chat request
    plan_patch: dict[str, Any]  # M3 shape, kept for compatibility


class ClarifyEvent(BaseModel):
    question: str
    reason: Literal["budget", "weak_match", "entropy", "suggest"]  # suggest: chips with an empty patch, send label
    field: str | None = None
    chips: list[ClarifyChipView]


class TextEvent(BaseModel):
    delta: str
    part: Literal["answer", "general"] = "answer"  # "general": labeled general know-how, not a product claim


class DoneEvent(BaseModel):
    timings: dict[str, float]
    turn_type: Literal["new", "refine", "question", "product", "chitchat"]
    reason: str = ""
    answer_source: Literal["model", "fallback", "error", "template"] = "template"


CHAT_EVENTS: dict[str, type[BaseModel]] = {
    "session": SessionEvent, "plan": PlanEvent, "results": ResultsEvent, "clarify": ClarifyEvent,
    "text": TextEvent, "done": DoneEvent,
}
