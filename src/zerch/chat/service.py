"""One chat turn as a stream of Server-Sent Events.

Order: session -> plan -> results -> clarify (optional) -> text (streamed) -> done.
The results event is sent as soon as the search returns; answer text never delays it.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import AsyncIterator
from typing import Any

from pydantic import BaseModel, Field, ValidationError

from zerch.chat import answer, clarify
from zerch.chat import session as sess_mod
from zerch.chat.slots import SlotFiller
from zerch.chat.turns import (
    PlanDelta,
    apply_delta,
    chip_label,
    classify,
    is_hinglish,
    refine,
    shown_category,
    wants_just_show,
)
from zerch.llm.base import LLMError, parse_json
from zerch.schema.model import Role, Schema
from zerch.search.models import SearchRequest, SearchResponse
from zerch.search.service import CURRENCY_SYMBOLS, search
from zerch.understand.llm_planner import schema_summary
from zerch.understand.patch import PatchOp, apply_patch
from zerch.understand.plan import QueryPlan, validate_plan
from zerch.understand.rules import RulesParser
from zerch.understand.service import get_dictionary, lexicon, understand

log = logging.getLogger("zerch.chat")


class ChatRequest(BaseModel):
    session_id: str | None = Field(None, max_length=64)
    message: str = Field("", max_length=500)
    apply: dict[str, Any] | None = None  # M3: a clarifier chip's plan_patch (PlanDelta shape)
    patch: list[PatchOp] | None = None  # M4: structured edits (remove a chip, set price range...), no message needed
    size: int = Field(10, ge=1, le=50)


def sse(event: str, data: Any) -> bytes:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False, default=str)}\n\n".encode()


def _chips(resp: SearchResponse | None) -> list[str]:
    return [c.label for c in (resp.understood.chips if resp and resp.understood else [])]


def _delta_view(old: list[str], new: list[str], old_text: str | None, new_text: str | None, turn: str) -> dict:
    out: dict[str, Any] = {"turn_type": turn, "added": [c for c in new if c not in old],
                           "removed": [c for c in old if c not in new]}
    if (old_text or "") != (new_text or ""):
        out["semantic_text"] = {"from": old_text, "to": new_text}
    return out


CLASSIFY_PROMPT = """You help an online catalog's chat search decide what the user's latest message means.

Catalog fields and values:
{summary}

Current search: {current}
Products on screen: {shown}
User's new message: {message}

Return JSON:
{{"type": "new" | "refine" | "question" | "chitchat",
  "semantic_text": "<new: what to search for, in plain English; refine: null unless the product changed>",
  "add_filters": [{{"field": "<field>", "op": "eq", "value": "<listed value>"}}],
  "exclude": [{{"field": "<field>", "value": "<listed value>"}}],
  "price": null or {{"lte": <number>}} or {{"gte": <number>}},
  "sort": null or "price_asc" or "price_desc"}}
"refine" = narrow or change the current search; "question" = asks about products on screen; "new" = a different
product. Use only listed fields and values."""


async def _llm_classify(llm: Any, message: str, plan: QueryPlan | None, docs: list[dict], schema: Schema,
                        d: Any, timeout_s: float) -> dict[str, Any] | None:
    title = next((f.name for f in schema.by_role(Role.title)), None)
    shown = [str(doc.get(title, ""))[:60] for doc in docs[:3]] if title else []
    current = {"text": plan.semantic_text, "filters": [f"{f.field} {f.op} {f.value}" for f in plan.filters]} \
        if plan else None
    prompt = CLASSIFY_PROMPT.format(summary=schema_summary(schema, d), current=json.dumps(current, ensure_ascii=False),
                                    shown=json.dumps(shown, ensure_ascii=False),
                                    message=json.dumps(message, ensure_ascii=False))
    try:
        raw = await asyncio.wait_for(llm.complete(prompt, temperature=0.0, max_tokens=250, json_mode=True),
                                     timeout=timeout_s)
        out = parse_json(raw)
        return out if isinstance(out, dict) and out.get("type") in ("new", "refine", "question", "chitchat") else None
    except (TimeoutError, LLMError, ValueError) as e:
        log.info("chat classify fallback: %s", e)
        return None


def _delta_from_llm(out: dict[str, Any], schema: Schema) -> PlanDelta:
    from zerch.understand.plan import PlanFilter, PlanSort, primary_price_field

    delta = PlanDelta()
    for f in out.get("add_filters") or []:
        if isinstance(f, dict) and schema.get(str(f.get("field"))) is not None and f.get("value") is not None:
            delta.add_filters.append(PlanFilter(field=f["field"], op="eq", value=f["value"], strict=True,
                                                origin="llm", confidence=0.7))
    for f in out.get("exclude") or []:
        if isinstance(f, dict) and schema.get(str(f.get("field"))) is not None and f.get("value") is not None:
            delta.exclude.append(PlanFilter(field=f["field"], op="not", value=f["value"], origin="llm",
                                            confidence=0.7))
    if isinstance(out.get("price"), dict):
        delta.price = {k: float(v) for k, v in out["price"].items() if k in ("lte", "gte") and
                       isinstance(v, int | float)} or None
    price = primary_price_field(schema)
    if out.get("sort") in ("price_asc", "price_desc") and price:
        delta.sort = PlanSort(field=price, order="asc" if out["sort"] == "price_asc" else "desc", mode="soft")
    if out.get("semantic_text") and isinstance(out["semantic_text"], str):
        delta.semantic_text = out["semantic_text"][:200]
    return delta


async def _stream_text(llm: Any, prompt: str, system: str) -> AsyncIterator[str]:
    if hasattr(llm, "stream"):
        async for chunk in llm.stream(prompt, system=system, max_tokens=180):
            yield chunk
    else:
        yield await llm.complete(prompt, system=system, temperature=0.3, max_tokens=180)


async def chat_turn(state: Any, pid: str, project: dict[str, Any], schema: Schema | None,
                    req: ChatRequest) -> AsyncIterator[bytes]:
    t0 = time.perf_counter()
    timings: dict[str, float] = {}

    def mark(name: str) -> None:
        timings[name] = round((time.perf_counter() - t0) * 1000, 1)

    s = state.settings
    sess = await sess_mod.load(state.redis, pid, req.session_id)
    sess.turn += 1
    yield sse("session", {"session_id": sess.session_id, "turn": sess.turn})
    msg = req.message.strip()
    if schema is None:
        yield sse("plan", {"understood": None, "delta": {"turn_type": "new"}})
        yield sse("results", {"items": [], "total": 0, "facets": {}, "match_quality": "none", "close_matches": []})
        yield sse("text", {"delta": "This catalog has no products yet."})
        yield sse("done", {"timings": timings, "turn_type": "new"})
        return

    d = await get_dictionary(state, pid, project, schema)
    lex = lexicon(state)
    hinglish = is_hinglish(msg)
    old_plan = sess.plan
    old_resp_chips = list(sess.last_chips)
    old_text = old_plan.semantic_text if old_plan else None
    reason = ""
    delta: PlanDelta | None = None
    turn: str | None = None

    # structured patch (chip removal, pill, clarifier chip): no classification needed
    if req.patch is not None and old_plan is not None:
        turn, reason = "refine", "patch"

    # a clarifier chip, sent as an M3 plan_patch or typed as its label
    patch = req.apply
    if turn is None and patch is None and msg and sess.clarify_chips:
        hit = next((c for c in sess.clarify_chips if chip_label(c["label"]) == chip_label(msg)), None)
        patch = hit["plan_patch"] if hit else None
    if turn is None and patch is not None:
        try:
            delta = PlanDelta.model_validate(patch)
            turn, reason = "refine", "clarifier chip"
        except ValidationError:
            delta = None

    parsed = validate_plan(RulesParser(schema, lex, d).parse(msg), schema, d) if msg else \
        QueryPlan(query="", semantic_text="")
    llm_out = None
    if turn is None:
        # products on screen only anchor a refinement if they were a good match for what was asked
        context = shown_category(schema, sess.last_docs) if sess.last_quality == "good" else None
        turn, reason = classify(msg, old_plan is not None, bool(sess.last_docs), parsed, d, context)
        if turn is None:
            if state.chat_llm is not None:
                llm_out = await _llm_classify(state.chat_llm, msg, old_plan, sess.last_docs, schema, d,
                                              s.chat_classify_timeout_ms / 1000)
                mark("classify_llm")
            if llm_out:
                turn, reason = llm_out["type"], "llm"
            else:
                turn, reason = ("refine" if old_plan else "new"), "fallback"

    resp: SearchResponse | None = None
    plan = old_plan
    if reason == "patch":
        plan = apply_patch(old_plan, req.patch, schema, d)
    elif turn == "refine" and old_plan is not None:
        if delta is None:
            delta = _delta_from_llm(llm_out, schema) if llm_out else refine(
                msg, old_plan, parsed, schema, lex, d, sess.last_docs)
        if delta.empty() and patch is None:
            turn, reason = "new", reason + "; nothing to refine"
        else:
            plan = apply_delta(old_plan, delta, schema, d)
    if turn == "new" or (turn == "refine" and old_plan is None):
        turn = "new"
        if llm_out and llm_out.get("semantic_text"):
            plan, _ = await understand(state, pid, project, schema, llm_out["semantic_text"])
        else:
            plan, _ = await understand(state, pid, project, schema, msg)
    mark("plan")

    symbol = CURRENCY_SYMBOLS.get(str(getattr(d, "currency", "") or "").upper(), "")
    if turn in ("new", "refine") and plan is not None:
        sreq = SearchRequest(query=msg or plan.semantic_text, size=req.size, highlight=False)
        resp = await search(state, pid, project, schema, sreq, use_cache=False, plan_override=plan)
        mark("search")
        new_chips = _chips(resp)
        yield sse("plan", {"understood": resp.understood.model_dump(mode="json") if resp.understood else None,
                           "delta": _delta_view(old_resp_chips, new_chips, old_text, plan.semantic_text, turn)})
        yield sse("results", {"items": [h.model_dump(mode="json") for h in resp.hits], "total": resp.total,
                              "facets": resp.facets, "pills": [p.model_dump(mode="json") for p in resp.pills],
                              "match_quality": resp.understood.match_quality if resp.understood else "good",
                              "close_matches": resp.understood.close_matches if resp.understood else [],
                              "display": resp.display.model_dump() if resp.display else None})
        mark("results")
        sess.plan = plan
        sess.last_ids = [h.id for h in resp.hits][: sess_mod.MAX_DOCS]
        sess.last_docs = [h.document for h in resp.hits][: sess_mod.MAX_DOCS]
        sess.last_chips = new_chips
        sess.last_quality = resp.understood.match_quality if resp.understood else None
    else:
        # question / chitchat: nothing changes; resend what's on screen so the sequence is always the same
        yield sse("plan", {"understood": None, "delta": {"turn_type": turn, "added": [], "removed": []}})
        yield sse("results", {"items": [{"id": i, "document": doc} for i, doc in zip(sess.last_ids, sess.last_docs,
                                                                                        strict=False)],
                              "total": len(sess.last_ids), "facets": {}, "match_quality": None,
                              "close_matches": [], "unchanged": True})
        mark("results")

    # clarifying question
    clar = None
    if resp is not None and plan is not None:
        clar = clarify.decide(plan, resp, schema, hinglish=hinglish, just_show=wants_just_show(msg),
                              answered_clarifier=sess.clarified and turn == "refine", symbol=symbol,
                              new_search=turn == "new")
        if clar:
            yield sse("clarify", {"question": clar.question, "field": clar.field, "reason": clar.reason,
                                  "chips": [c.model_dump() for c in clar.chips]})
    sess.clarified = clar is not None
    sess.clarify_chips = [c.model_dump() for c in clar.chips] if clar else []

    # answer text
    title_field = next((f.name for f in schema.by_role(Role.title)), None)
    text_parts: list[str] = []
    first = None
    answer_source = "template"  # model | fallback (model output all dropped) | error (LLM call failed) | template
    try:
        if turn == "chitchat":
            text = answer.chitchat_reply(msg, hinglish)
            yield sse("text", {"delta": text})
            text_parts.append(text)
            first = time.perf_counter()
        elif state.chat_llm is None:
            docs = [(h.id, answer.doc_view(h.document, schema), False) for h in (resp.hits if resp else [])[:5]]
            text = (answer.fallback_search_text(resp.total if resp else 0,
                                                resp.understood.match_quality if resp and resp.understood else "good",
                                                docs, hinglish, title_field)
                    if turn != "question" else ("Is sawal ka jawab abhi nahi de sakta." if hinglish
                                                else "I can't answer questions about products right now."))
            yield sse("text", {"delta": text})
            text_parts.append(text)
            first = time.perf_counter()
        else:
            if turn == "question":
                docs_q = [(i, answer.doc_view(doc, schema, detailed=True)) for i, doc in
                          zip(sess.last_ids, sess.last_docs, strict=False)]
                fact_lines, fact_ids = answer.computed_facts(docs_q, schema)
                prompt = answer.question_prompt(msg, docs_q, hinglish, fact_lines, schema)
                system = answer.SYSTEM_QUESTION
                by_id = dict(zip(sess.last_ids, sess.last_docs, strict=False))
            else:
                close = set(resp.understood.close_matches) if resp and resp.understood else set()
                focus = {c.field for c in (resp.understood.chips if resp.understood else [])}
                docs = [(h.id, answer.compact_view(h.document, schema, focus), h.id in close) for h in resp.hits]
                suggestions = [c.label for c in clar.chips] if clar else []
                quality = resp.understood.match_quality if resp.understood else "good"
                fact_lines, fact_ids = answer.computed_facts(
                    [(h.id, answer.doc_view(h.document, schema)) for h in resp.hits], schema)
                prompt = answer.search_prompt(msg, _chips(resp), quality, resp.total, docs, suggestions, hinglish,
                                              fact_lines, schema)
                system = answer.SYSTEM_SEARCH
                by_id = {h.id: h.document for h in resp.hits}
            # numbers and field values come from the documents, never from the model (zerch.chat.slots)
            filler = SlotFiller(by_id, schema, symbol, fact_ids, order=list(by_id))

            async def model_stream():
                async for c in _stream_text(state.chat_llm, prompt, system):
                    if "first_model_token" not in timings:
                        mark("first_model_token")
                    yield c

            async for chunk in filler.stream(model_stream()):
                if first is None:
                    first = time.perf_counter()
                text_parts.append(chunk)
                yield sse("text", {"delta": chunk})
            timings["dropped_sentences"] = len(filler.dropped)
            answer_source = "model"
            if filler.dropped:
                log.info("dropped %d sentence(s): %s", len(filler.dropped), filler.dropped[:3])
            if not "".join(text_parts).strip():
                answer_source = "fallback"
                docs = [(h.id, answer.doc_view(h.document, schema), False) for h in (resp.hits if resp else [])[:5]]
                text = (answer.fallback_search_text(resp.total if resp else 0,
                                                    resp.understood.match_quality if resp and resp.understood
                                                    else "good", docs, hinglish, title_field)
                        if turn != "question" else ("Main iska pakka jawab nahi de paaya; product details "
                                                    "cards par dekh sakte hain." if hinglish else
                                                    "I couldn't give a verified answer to that; the product cards "
                                                    "show each product's details."))
                yield sse("text", {"delta": text})
                text_parts.append(text)
                first = first or time.perf_counter()
    except (LLMError, OSError) as e:
        log.warning("chat answer failed: %s", e)
        answer_source = "error"
        if not text_parts:
            text = "Results upar dikh rahe hain." if hinglish else "Here are the results."
            yield sse("text", {"delta": text})
            text_parts.append(text)
    if first is not None:
        timings["first_token"] = round((first - t0) * 1000, 1)
    mark("total")

    sess.remember("user", msg, turn)
    sess.remember("assistant", "".join(text_parts), turn)
    await sess_mod.save(state.redis, pid, sess)
    yield sse("done", {"timings": timings, "turn_type": turn, "reason": reason, "answer_source": answer_source})


__all__ = ["ChatRequest", "chat_turn", "sse"]
