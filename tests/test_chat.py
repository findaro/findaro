"""Chat search (M3): turn rules, refinement deltas, clarifiers, and the /v1/chat SSE stream."""

import json

import pytest

from findaro.chat.clarify import decide
from findaro.chat.turns import (
    PlanDelta,
    apply_delta,
    classify,
    is_hinglish,
    refine,
    shown_category,
    wants_just_show,
)
from findaro.search.models import SearchResponse, Understood
from findaro.understand.plan import PlanFilter, validate_plan
from findaro.understand.rules import RulesParser

from .conftest import make_catalog
from .test_understand_rules import DICT, LEX, SCHEMA


def parse(msg):
    return validate_plan(RulesParser(SCHEMA, LEX, DICT).parse(msg), SCHEMA, DICT)


CATALOG = make_catalog(120)
BOTTLES = [d for d in CATALOG if "Water Bottle" in d["title"]][:6]


# --- turn classification ---------------------------------------------------------------------------------

@pytest.mark.parametrize("msg,has_plan,has_results,expected", [
    ("hi", False, False, "chitchat"),
    ("thanks!", True, True, "chitchat"),
    ("water bottle", False, False, "new"),
    ("water bottle", True, True, "new"),
    ("cheaper", True, True, "refine"),
    ("aur sasta", True, True, "refine"),
    ("under 500", True, True, "refine"),
    ("only black", True, True, "refine"),
    ("copper nahi", True, True, "refine"),
    ("not plastic", True, True, "refine"),
    ("is the second one copper?", True, True, "question"),
    ("dusra wala kitne ka hai?", True, True, "question"),
    ("which is the cheapest?", True, True, "question"),
    ("start over", True, True, "new"),
])
def test_classify(msg, has_plan, has_results, expected):
    turn, _ = classify(msg, has_plan, has_results, parse(msg), DICT)
    assert turn == expected


def test_category_inside_current_results_is_a_refinement():
    turn, _ = classify("pressure cooker", True, True, parse("pressure cooker"), DICT,
                       context_category="Home")
    assert turn == "refine"
    turn, _ = classify("phone cover", True, True, parse("phone cover"), DICT, context_category="Home")
    assert turn == "new"


def test_shown_category():
    assert shown_category(SCHEMA, BOTTLES) == "Home > Storage > Bottles"
    assert shown_category(SCHEMA, [CATALOG[0], CATALOG[3]]) is None


def test_language_detection():
    assert is_hinglish("sasta wala dikhao") and is_hinglish("500 ke andar") and is_hinglish("kaale joote")
    assert not is_hinglish("black shoes under 1000") and not is_hinglish("car seat cover")
    assert wants_just_show("4K only, just show") and wants_just_show("bas dikha do")


# --- refinement --------------------------------------------------------------------------------------------

def plan_for(q):
    return parse(q)


def test_cheaper_lowers_the_ceiling_and_sorts():
    plan = plan_for("water bottle")
    d = refine("cheaper", plan, parse("cheaper"), SCHEMA, LEX, DICT, BOTTLES)
    prices = sorted(b["price"] for b in BOTTLES)
    assert d.price and d.price["lte"] <= prices[len(prices) // 2]
    assert d.sort and d.sort.order == "asc"
    new = apply_delta(plan, d, SCHEMA, DICT)
    assert any(f.field == "price" and f.op == "range" for f in new.filters)


def test_price_refinement_replaces_range():
    plan = plan_for("water bottle under 900")
    d = refine("500 ke andar", plan, parse("500 ke andar"), SCHEMA, LEX, DICT, BOTTLES)
    new = apply_delta(plan, d, SCHEMA, DICT)
    prices = [f for f in new.filters if f.field == "price"]
    assert len(prices) == 1 and prices[0].value == {"lte": 500.0}


def test_only_value_is_a_strict_filter():
    plan = plan_for("water bottle")
    d = refine("only copper", plan, parse("only copper"), SCHEMA, LEX, DICT, BOTTLES)
    new = apply_delta(plan, d, SCHEMA, DICT)
    f = next(f for f in new.filters if f.field == "material")
    assert f.value == "Copper" and f.strict


@pytest.mark.parametrize("msg", ["not plastic", "plastic nahi", "without plastic", "bina plastic"])
def test_negation_excludes(msg):
    plan = plan_for("water bottle")
    d = refine(msg, plan, parse(msg), SCHEMA, LEX, DICT, BOTTLES)
    new = apply_delta(plan, d, SCHEMA, DICT)
    assert any(f.op == "not" and f.field == "material" and f.value == "Plastic" for f in new.filters)
    assert not any(f.op in ("eq", "in") and f.field == "material" for f in new.filters)


def test_asking_for_an_excluded_value_lifts_the_exclusion():
    plan = apply_delta(plan_for("water bottle"), PlanDelta(exclude=[
        PlanFilter(field="material", op="not", value="Copper")]), SCHEMA, DICT)
    d = refine("only copper", plan, parse("only copper"), SCHEMA, LEX, DICT, BOTTLES)
    new = apply_delta(plan, d, SCHEMA, DICT)
    assert not any(f.op == "not" for f in new.filters)


def test_bigger_shifts_a_quantity_attribute():
    from findaro.schema import infer_schema

    from .test_understand_rules import payload_from

    docs = [{"id": i, "title": f"Steel Cooker {i}", "capacity": c, "price": 1000 + i}
            for i, c in enumerate(["2 L", "3 L", "5 L", "7.5 L"] * 8)]
    schema, d = payload_from(docs)
    assert infer_schema(docs).get("capacity").role.value == "facet"
    shown = [x for x in docs if x["capacity"] in ("2 L", "3 L")][:6]
    plan = validate_plan(RulesParser(schema, LEX, d).parse("cooker"), schema, d)
    delta = refine("bigger", plan, validate_plan(RulesParser(schema, LEX, d).parse("bigger"), schema, d),
                   schema, LEX, d, shown)
    cap = next(f for f in delta.add_filters if f.field == "capacity")
    assert set(cap.value) == {"3 L", "5 L", "7.5 L"} or set(cap.value) == {"5 L", "7.5 L"}


# --- clarifiers --------------------------------------------------------------------------------------------

def resp(total, facets, hits=(), close=(), quality="good"):
    from findaro.search.models import Hit

    return SearchResponse(query="q", total=total, page=1, size=10, facets=facets, took_ms=1,
                          hits=[Hit(id=h, score=1, document={}) for h in hits],
                          understood=Understood(query="q", semantic_text="q", match_quality=quality,
                                                close_matches=list(close)))


def test_clarify_on_category_spread():
    facets = {"category": {"type": "category", "values": [
        {"value": "Home", "count": 40}, {"value": "Home > Cookware", "count": 40},
        {"value": "Home > Cookware > Tawa", "count": 14}, {"value": "Home > Cookware > Kadai", "count": 13},
        {"value": "Home > Cookware > Pressure Cookers", "count": 13}]}}
    c = decide(parse("cookware"), resp(40, facets, hits=[f"h{i}" for i in range(10)]), SCHEMA, hinglish=False,
               just_show=False, answered_clarifier=False, symbol="₹")
    assert c and c.reason == "entropy" and c.field == "category"
    assert [ch.label for ch in c.chips] == ["Tawa", "Kadai", "Pressure Cookers"]
    assert c.chips[0].plan_patch == {"add_filters": [{"field": "category", "op": "eq",
                                                      "value": "Home > Cookware > Tawa"}]}


def test_clarify_budget():
    plan = parse("water bottle under 300")
    c = decide(plan, resp(1, {}, hits=["a", "b"], close=["b"]), SCHEMA, hinglish=True, just_show=False,
               answered_clarifier=False, symbol="₹")
    assert c and c.reason == "budget" and "300" in c.question
    assert c.chips[0].label == "Show slightly over budget" and c.chips[0].plan_patch == {"price": {"lte": 400.0}}


def test_no_clarifier_when_told_or_just_answered():
    facets = {"category": {"type": "category", "values": [
        {"value": "Home", "count": 40}, {"value": "Home > A", "count": 20}, {"value": "Home > B", "count": 20}]}}
    r = resp(40, facets, hits=[f"h{i}" for i in range(10)])
    kw = dict(hinglish=False, symbol="")
    assert decide(parse("stuff"), r, SCHEMA, just_show=True, answered_clarifier=False, **kw) is None
    assert decide(parse("stuff"), r, SCHEMA, just_show=False, answered_clarifier=True, **kw) is None
    assert decide(parse("stuff"), r, SCHEMA, just_show=False, answered_clarifier=False, new_search=False, **kw) is None


def test_no_category_question_when_query_named_one():
    facets = {"category": {"type": "category", "values": [
        {"value": "Home", "count": 40}, {"value": "Home > A", "count": 20}, {"value": "Home > B", "count": 20}]}}
    c = decide(parse("pressure cooker"), resp(40, facets, hits=["h"] * 10), SCHEMA, hinglish=False,
               just_show=False, answered_clarifier=False, symbol="")
    assert c is None or c.field != "category"


# --- /v1/chat end to end -----------------------------------------------------------------------------------

class FakeChatLLM:
    name = "fake-chat"

    def __init__(self):
        self.prompts = []
        self.converse = {"reply": "Sounds like fun!", "search": None}

    async def complete(self, prompt, **kw):
        self.prompts.append(prompt)
        if "shopping assistant" in (kw.get("system") or ""):
            return json.dumps(self.converse)
        return json.dumps({"type": "refine", "semantic_text": None, "add_filters": [], "exclude": []})

    async def stream(self, prompt, system=None, **kw):
        self.prompts.append(prompt)
        ids = [line.split("[")[1].split("]")[0] for line in prompt.splitlines() if line[:3].rstrip(". ").isdigit()]
        for part in ["Here ", "you go ", f"[{ids[0]}]." if ids else "."]:
            yield part


@pytest.fixture
def chat_llm(state):
    fake = FakeChatLLM()
    state.chat_llm = fake
    yield fake
    state.chat_llm = None


async def chat(project, message, session_id=None, apply=None):
    body = {"message": message, "session_id": session_id}
    if apply is not None:
        body["apply"] = apply
    r = await project.client.post("/v1/chat", json=body, headers=project.searcher)
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("text/event-stream")
    events = []
    for block in r.text.strip().split("\n\n"):
        lines = dict(line.split(": ", 1) for line in block.splitlines())
        events.append((lines["event"], json.loads(lines["data"])))
    return events


def names(events):
    out = [e for e, _ in events]
    return [e for i, e in enumerate(out) if e != "text" or out[i - 1] != "text"]  # collapse text deltas


def first(events, name):
    return next(d for e, d in events if e == name)


async def test_event_order_and_session(loaded, chat_llm):
    ev = await chat(loaded, "water bottle")
    assert names(ev)[:3] == ["session", "plan", "results"]
    assert names(ev)[-2:] == ["text", "done"]
    assert set(names(ev)) <= {"session", "plan", "results", "clarify", "text", "done"}
    sid = first(ev, "session")["session_id"]
    res = first(ev, "results")
    assert res["items"] and all("Water Bottle" in i["document"]["title"] for i in res["items"][:3])
    text = "".join(d["delta"] for e, d in ev if e == "text")
    assert f"[{res['items'][0]['id']}]" in text  # the answer cites a returned product
    done = first(ev, "done")
    assert done["turn_type"] == "new" and done["timings"]["results"] <= done["timings"]["total"]

    ev2 = await chat(loaded, "only copper", sid)
    assert first(ev2, "session") == {"session_id": sid, "turn": 2}
    plan = first(ev2, "plan")
    assert plan["delta"]["turn_type"] == "refine" and "Copper" in plan["delta"]["added"]
    assert all(i["document"]["material"] == "Copper" for i in first(ev2, "results")["items"])


async def test_question_answers_from_shown_products(loaded, chat_llm):
    ev = await chat(loaded, "water bottle")
    sid = first(ev, "session")["session_id"]
    shown = [i["id"] for i in first(ev, "results")["items"]]
    ev2 = await chat(loaded, "is the second one copper?", sid)
    assert first(ev2, "done")["turn_type"] == "question"
    assert [i["id"] for i in first(ev2, "results")["items"]] == shown  # nothing re-searched
    prompt = chat_llm.prompts[-1]
    assert f"2. [{shown[1]}]" in prompt and "Shopper:" in prompt


async def test_chitchat_is_one_line_without_llm(loaded, chat_llm):
    n = len(chat_llm.prompts)
    ev = await chat(loaded, "thanks")
    assert first(ev, "done")["turn_type"] == "chitchat"
    assert len(chat_llm.prompts) == n
    assert len("".join(d["delta"] for e, d in ev if e == "text").splitlines()) == 1


async def test_clarifier_chip_patch_applies(loaded, chat_llm):
    ev = await chat(loaded, "water bottle under 250")
    sid = first(ev, "session")["session_id"]
    clar = next((d for e, d in ev if e == "clarify"), None)
    if clar is None:
        pytest.skip("fixture has enough bottles under 250")
    chip = clar["chips"][0]
    ev2 = await chat(loaded, chip["label"], sid, apply=chip["plan_patch"])
    assert first(ev2, "done")["turn_type"] == "refine"
    assert not any(e == "clarify" for e, _ in ev2)  # never two questions in a row


async def test_chat_without_llm_uses_templates(loaded):
    ev = await chat(loaded, "water bottle")
    text = "".join(d["delta"] for e, d in ev if e == "text")
    top = first(ev, "results")["items"][0]["id"]
    assert f"[{top}]" in text


async def test_chat_validation(loaded):
    r = await loaded.client.post("/v1/chat", json={"message": "  "}, headers=loaded.searcher)
    assert r.status_code == 400
    r = await loaded.client.post("/v1/chat", json={"message": "x"})
    assert r.status_code == 401


# --- negation scope (M4 fix: "slim fit, black nahi" must not negate slim fit) -------------------------

@pytest.mark.parametrize("msg", ["copper, black nahi", "copper but not black", "copper aur black ke alawa",
                                 "copper bina black", "not black, copper", "black ke siwa copper"])
def test_negation_applies_to_nearest_value_only(msg):
    plan = plan_for("water bottle")
    d = refine(msg, plan, parse(msg), SCHEMA, LEX, DICT, BOTTLES)
    new = apply_delta(plan, d, SCHEMA, DICT)
    excluded = {(f.field, f.value) for f in new.filters if f.op == "not"}
    assert excluded == {("color", "Black")}, msg
    assert any(f.field == "material" and f.value == "Copper" and f.op in ("eq", "in") for f in new.filters), msg


@pytest.mark.parametrize("msg", ["not black", "black nahi", "black ke alawa", "bina black", "without black",
                                 "black nahin chahiye"])
def test_negation_forms(msg):
    plan = plan_for("water bottle")
    d = refine(msg, plan, parse(msg), SCHEMA, LEX, DICT, BOTTLES)
    assert [(f.field, f.value) for f in d.exclude] == [("color", "Black")], msg
    assert not d.add_filters, msg


async def test_chat_patch_turn_and_pills(loaded, chat_llm):
    ev = await chat(loaded, "water bottle")
    sid = first(ev, "session")["session_id"]
    res = first(ev, "results")
    assert res["pills"], "attribute choices are passive pills"
    assert not any(e == "clarify" and d["field"] not in ("category", "price") for e, d in ev)
    pill = res["pills"][0]["values"][0]
    r = await loaded.client.post("/v1/chat", json={"session_id": sid, "patch": pill["patch"]},
                                 headers=loaded.searcher)
    assert r.status_code == 200
    ev2 = [(b.split("\n")[0][7:], json.loads(b.split("\n")[1][6:])) for b in r.text.strip().split("\n\n")]
    assert first(ev2, "done")["turn_type"] == "refine" and first(ev2, "done")["reason"] == "patch"
    field = res["pills"][0]["field"]
    assert all(i["document"][field] == pill["value"] for i in first(ev2, "results")["items"])


def test_value_in_two_fields_filters_one():
    # "copper" is a colour and a material in the demo-like fixture: keep the field the shown products use
    plan = plan_for("water bottle")
    d = refine("only copper", plan, parse("only copper"), SCHEMA, LEX, DICT, BOTTLES)
    fields = [f.field for f in d.add_filters if str(f.value) == "Copper"]
    assert len(fields) == 1


async def test_patch_after_session_expired(loaded):
    r = await loaded.client.post("/v1/chat", json={"session_id": "chs_gone", "patch": [{"op": "set_sort"}]},
                                 headers=loaded.searcher)
    ev = [(b.split("\n")[0][7:], json.loads(b.split("\n")[1][6:])) for b in r.text.strip().split("\n\n")]
    assert [e for e, _ in ev] == ["session", "plan", "results", "done"]
    assert ev[-1][1]["reason"] == "session_expired"


async def test_product_conversation(loaded, chat_llm, catalog):
    pid = catalog[3]["id"]
    ev = await chat(loaded, "what is it made of?", apply=None)  # no focus: a search
    r = await loaded.client.post("/v1/chat", json={"message": "what is it made of?", "product_ids": [pid]},
                                 headers=loaded.searcher)
    ev = [(b.split("\n")[0][7:], json.loads(b.split("\n")[1][6:])) for b in r.text.strip().split("\n\n")]
    done = first(ev, "done")
    assert done["turn_type"] == "product" and done["reason"] == "product focus"
    prompt = chat_llm.prompts[-1]
    assert f"1. [{pid}]" in prompt and "Shopper:" in prompt
    sid = first(ev, "session")["session_id"]
    r = await loaded.client.post("/v1/chat", json={"session_id": sid, "message": "is it waterproof?",
                                                   "product_ids": [pid]}, headers=loaded.searcher)
    assert "what is it made of?" in chat_llm.prompts[-1]  # follow-ups see the conversation so far
    r = await loaded.client.post("/v1/chat", json={"message": "thanks", "product_ids": [pid]},
                                 headers=loaded.searcher)
    assert '"turn_type": "chitchat"' in r.text
    r = await loaded.client.post("/v1/chat", json={"message": "hi", "product_ids": ["NOPE"]}, headers=loaded.searcher)
    assert r.status_code == 200 and '"turn_type": "product"' not in r.text


async def test_greeting_offers_category_chips(loaded, chat_llm):
    n = len(chat_llm.prompts)
    ev = await chat(loaded, "hi")
    assert first(ev, "done")["turn_type"] == "chitchat"
    assert len(chat_llm.prompts) == n  # instant, no LLM
    c = first(ev, "clarify")
    assert c["reason"] == "suggest" and {"Footwear", "Home"} <= {ch["label"] for ch in c["chips"]}
    assert all(ch["patch"] == [] for ch in c["chips"])
    # tapping a chip sends its label as a message (an empty patch is not a plan edit)
    sid = first(ev, "session")["session_id"]
    r = await loaded.client.post("/v1/chat", json={"message": "Footwear", "session_id": sid, "patch": []},
                                 headers=loaded.searcher)
    assert "event: results" in r.text and '"turn_type": "new"' in r.text


async def test_small_talk_leads_to_a_search(loaded, chat_llm):
    chat_llm.converse = {"reply": "A Goa trip sounds great! Here are some chappals, from just 199.",
                         "search": "kolhapuri chappal"}
    ev = await chat(loaded, "going to goa next week, kuch suggest karo yaar")
    done = first(ev, "done")
    assert done["turn_type"] == "new" and done["reason"] == "conversation", done
    items = first(ev, "results")["items"]
    assert items and "Chappal" in items[0]["document"]["title"]
    text = "".join(d["delta"] for e, d in ev if e == "text")
    assert "Goa" in text and "199" not in text  # the sentence with a number it can't see is dropped


async def test_small_talk_keeps_results_on_screen(loaded, chat_llm):
    ev = await chat(loaded, "running shoes")
    sid = first(ev, "session")["session_id"]
    chat_llm.converse = {"reply": "I'm doing well, thanks for asking! Want to narrow these down?", "search": None}
    ev = await chat(loaded, "how is your day going mate", sid)
    assert first(ev, "results").get("unchanged") is True
    assert "doing well" in "".join(d["delta"] for e, d in ev if e == "text")


async def test_small_talk_on_an_empty_screen_shows_no_cards(loaded, chat_llm):
    chat_llm.converse = {"reply": "I'm good, thanks! What are you shopping for?", "search": None}
    ev = await chat(loaded, "how is your day going mate")
    assert first(ev, "results")["items"] == []
    assert first(ev, "clarify")["reason"] == "suggest"



async def test_daily_llm_budget_falls_back_to_templates(state, loaded):
    from findaro.llm.base import LLMError
    from findaro.llm.budget import BudgetedLLM

    await state.redis.delete(*[k async for k in state.redis.scan_iter(match="llm:calls:*")] or ["-"])
    fake = FakeChatLLM()
    budgeted = BudgetedLLM(fake, state.redis, daily_limit=1)
    assert json.loads(await budgeted.complete("x"))  # first call is within the budget
    with pytest.raises(LLMError):
        await budgeted.complete("x")
    with pytest.raises(LLMError):
        async for _ in budgeted.stream("x"):
            pass
    assert len(fake.prompts) == 1  # over-budget calls never reach the provider

    state.chat_llm = budgeted
    try:
        ev = await chat(loaded, "water bottle")
        assert names(ev)[-2:] == ["text", "done"]  # the turn still completes, with a template answer
        assert "".join(d["delta"] for e, d in ev if e == "text").strip()
    finally:
        state.chat_llm = None
