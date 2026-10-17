"""Chat session state in Redis (TTL 30 min): current plan, last results, short history."""

from __future__ import annotations

import secrets
from typing import Any

from pydantic import BaseModel, Field

from findaro.understand.plan import QueryPlan

TTL_S = 30 * 60
MAX_HISTORY = 8
MAX_DOCS = 10


class Turn(BaseModel):
    role: str  # user | assistant
    text: str
    type: str | None = None


class Session(BaseModel):
    session_id: str
    turn: int = 0
    plan: QueryPlan | None = None
    last_ids: list[str] = Field(default_factory=list)
    last_docs: list[dict[str, Any]] = Field(default_factory=list)  # shown results, for questions about them
    history: list[Turn] = Field(default_factory=list)
    last_chips: list[str] = Field(default_factory=list)  # understood chip labels of the last search
    last_quality: str | None = None  # match_quality of the last search
    clarified: bool = False  # did the previous turn ask a clarifying question
    clarify_chips: list[dict[str, Any]] = Field(default_factory=list)  # last clarifier's chips (label -> patch)
    focus_ids: list[str] = Field(default_factory=list)  # products the conversation is about (product drawer)

    def remember(self, role: str, text: str, type_: str | None = None) -> None:
        self.history.append(Turn(role=role, text=text[:500], type=type_))
        self.history = self.history[-MAX_HISTORY:]


def _key(pid: str, sid: str) -> str:
    return f"chat:{pid}:{sid}"


def new_session_id() -> str:
    return "chs_" + secrets.token_urlsafe(12)


async def load(redis: Any, pid: str, sid: str | None) -> Session:
    if sid:
        raw = await redis.get(_key(pid, sid))
        if raw:
            return Session.model_validate_json(raw)
    return Session(session_id=sid if sid and len(sid) <= 64 else new_session_id())


async def save(redis: Any, pid: str, session: Session) -> None:
    await redis.set(_key(pid, session.session_id), session.model_dump_json(), ex=TTL_S)
