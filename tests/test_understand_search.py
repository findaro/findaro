"""Query understanding end to end: plan -> filters/boosts/sort -> results, understood chips, debug, LLM path."""

import asyncio
import json
from dataclasses import replace

import httpx
import pytest

from zerch.llm.base import LLMError
from zerch.main import create_app
from zerch.understand import service as understand_service

from .conftest import make_settings


async def search_with(state, project, body, headers=None, **settings):
    """Search through an app whose settings differ from the shared test state."""
    st = replace(state, settings=make_settings(**settings)) if settings else state
    app = create_app(st.settings, state.embedder)
    app.state.zerch = st
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        r = await c.post("/v1/search", json=body, headers={**project.searcher, **(headers or {})})
    assert r.status_code == 200, r.text
    return r.json()


async def test_price_filter_from_text(loaded, catalog):
    res = await loaded.search(query="water bottle under 500", size=50)
    assert res["hits"] and all(h["document"]["price"] <= 500 for h in res["hits"])
    chips = res["understood"]["chips"]
    assert {"label": "Under ₹500", "kind": "filter", "field": "price"}.items() <= chips[0].items()
    assert res["understood"]["semantic_text"] == "water bottle"
    assert res["total"] == sum(1 for d in catalog if "Water Bottle" in d["title"] and d["price"] <= 500)


async def test_hinglish_price_and_colour(loaded, catalog):
    res = await loaded.search(query="1000 ke andar kaale joote", size=50)
    labels = [c["label"] for c in res["understood"]["chips"]]
    assert "Under ₹1,000" in labels and "Black" in labels
    assert res["hits"]
    close = set(res["understood"]["close_matches"])
    exact = [h for h in res["hits"] if h["id"] not in close]
    for h in exact:
        assert h["document"]["price"] <= 1000
        assert h["document"]["color"] == "Black"
    assert "Running Shoes" in res["hits"][0]["document"]["title"]
    for h in res["hits"]:
        if h["id"] in close:  # backfill stays in the matched category, just over budget
            assert h["document"]["category"].startswith("Footwear")


async def test_bare_number_is_not_a_price(loaded):
    res = await loaded.search(query="bottle 500", size=5, debug=True)
    assert not any(c["field"] == "price" for c in res["understood"]["chips"])


async def test_understand_off_is_plain_retrieval(loaded):
    res = await loaded.search(query="water bottle under 500", size=50, understand=False)
    assert res["understood"]["source"] == "off" and res["understood"]["chips"] == []
    assert any(h["document"]["price"] > 500 for h in res["hits"])


async def test_explicit_filter_wins_over_inferred(loaded):
    res = await loaded.search(query="black kurta", filters={"color": "White"}, size=20)
    assert res["hits"] and all(h["document"]["color"] == "White" for h in res["hits"])
    assert not any(c["field"] == "color" for c in res["understood"]["chips"])


async def test_soft_sort_prefers_cheaper(loaded, catalog):
    plain = await loaded.search(query="pressure cooker", size=5)
    cheap = await loaded.search(query="sasta pressure cooker", size=5)
    assert any(c["kind"] == "sort" for c in cheap["understood"]["chips"])
    avg = lambda r: sum(h["document"]["price"] for h in r["hits"]) / len(r["hits"])  # noqa: E731
    assert avg(cheap) < avg(plain)
    assert all("Pressure Cooker" in h["document"]["title"] for h in cheap["hits"])


async def test_relaxation_when_filters_match_nothing(loaded, catalog):
    # Leather pressure cookers don't exist: the inferred material filter is relaxed, the price one kept.
    res = await loaded.search(query="leather pressure cooker under 3000", size=10, debug=True)
    und = res["understood"]
    assert [r["field"] for r in und["relaxations"]] in (["material"], [])
    assert res["hits"]
    assert all(h["document"]["price"] <= 3000 for h in res["hits"])


async def test_backfill_close_matches(loaded, catalog):
    # Exactly one Blue Silicone Phone Cover may exist; the page is filled with close matches after it.
    res = await loaded.search(query="blue silicone phone cover", size=10)
    exact = [d for d in catalog if d["color"] == "Blue" and d["material"] == "Silicone" and "Phone Cover" in d["title"]]
    close = res["understood"]["close_matches"]
    assert 0 < len(exact) < 10  # fixture precondition
    ids = [h["id"] for h in res["hits"]]
    assert set(ids[: len(exact)]) == {d["id"] for d in exact}  # exact matches first
    assert close and close == ids[len(exact):]  # then close matches (that still match the query) follow
    assert all("Phone Cover" in h["document"]["title"] for h in res["hits"])


async def test_budget_backfill_stays_in_category(loaded, catalog):
    res = await loaded.search(query="kolhapuri chappal under 300", size=10)
    close = set(res["understood"]["close_matches"])
    exact = [h for h in res["hits"] if h["id"] not in close]
    assert all(h["document"]["price"] <= 300 for h in exact)
    assert close, "two chappals under 300: the page should be filled with chappals just over budget"
    over = [h["document"]["price"] for h in res["hits"] if h["id"] in close]
    assert over == sorted(over) and all(p > 300 for p in over)
    assert all("Kolhapuri" in h["document"]["title"] for h in res["hits"])


async def test_match_quality_none_returns_nothing(state, loaded):
    res = await search_with(state, loaded, {"query": "zxqv plorbinate"}, match_floor=2.0, understand_llm=False)
    assert res["understood"]["match_quality"] == "none"
    assert res["total"] == 0 and res["hits"] == []
    res = await search_with(state, loaded, {"query": "pressure cooker"}, match_floor=2.0, understand_llm=False)
    assert res["understood"]["match_quality"] == "good" and res["hits"]


async def test_debug_payload(loaded):
    res = await loaded.search(query="water bottle under 3000", debug=True)
    d = res["debug"]
    assert d["plan"]["source"] == "rules"
    assert {"understand", "embed", "retrieve", "fetch", "total"} <= set(d["timings_ms"])
    assert d["lexical_hits"] > 0 and d["vector_top_score"] is not None
    assert "debug" not in await loaded.search(query="copper bottle")


# --- LLM path --------------------------------------------------------------------------------------------

class FakePlanner:
    name = "fake"

    def __init__(self, reply: dict, delay: float = 0.0):
        self.reply, self.delay, self.calls = reply, delay, 0

    async def complete(self, prompt, **kw):
        self.calls += 1
        await asyncio.sleep(self.delay)
        return json.dumps(self.reply)


@pytest.fixture
def with_planner(state):
    def install(p):
        state.planner = p
        return p

    yield install
    state.planner = None


async def test_llm_rewrites_unknown_words(state, loaded, with_planner):
    fake = with_planner(FakePlanner({"semantic_text": "copper water bottle", "category": "Home > Storage > Bottles",
                                     "filters": [{"field": "color", "op": "eq", "value": "Ultraviolet"}]}))
    res = await loaded.search(query="tambe ki glorpkin", debug=True)
    assert fake.calls == 1
    assert res["understood"]["source"] == "llm"
    assert res["understood"]["semantic_text"] == "copper water bottle"
    assert "Water Bottle" in res["hits"][0]["document"]["title"]
    assert not any(c["label"] == "Ultraviolet" for c in res["understood"]["chips"])  # not in the catalog
    # second time: served from the plan cache
    res = await loaded.search(query="tambe ki glorpkin", debug=True)
    assert res["understood"]["source"] == "cache" and fake.calls == 1


async def test_llm_hallucinated_price_is_ignored(state, loaded, with_planner):
    with_planner(FakePlanner({"semantic_text": "pressure cooker", "category": None,
                              "filters": [{"field": "price", "op": "range", "value": {"lte": 300}}]}))
    res = await loaded.search(query="dabbuwala cooker", debug=True)
    assert res["understood"]["source"] == "llm"
    assert not any(c["field"] == "price" for c in res["understood"]["chips"])


async def test_llm_timeout_falls_back_and_fills_cache(state, loaded, with_planner):
    fake = with_planner(FakePlanner({"semantic_text": "kolhapuri chappal", "category": None, "filters": []},
                                    delay=0.3))
    body = {"query": "frobnicated kolhapuri", "debug": True}
    res = await search_with(state, loaded, body, planner_timeout_ms=50, search_cache_ttl=0)
    assert res["debug"]["llm"]["llm"] == "timeout"
    assert res["understood"]["source"] == "rules" and res["hits"]
    await asyncio.sleep(0.5)  # the call keeps running and lands in the plan cache
    res = await search_with(state, loaded, body, planner_timeout_ms=50, search_cache_ttl=0)
    assert res["understood"]["source"] == "cache" and fake.calls == 1


async def test_rules_only_queries_never_call_the_llm(state, loaded, with_planner):
    fake = with_planner(FakePlanner({"semantic_text": "x", "category": None, "filters": []}))
    await loaded.search(query="black copper bottle under 900")
    await loaded.search(query="gents chappal")
    assert fake.calls == 0


async def test_dictionary_rebuilt_after_ingest(loaded, catalog):
    # a brand-new facet value becomes understood after the ingest job finishes
    new = dict(catalog[0], id="NEW1", color="Saffron", title="Saffron Cotton Kurta Special")
    await loaded.ingest([new])
    understand_service._dicts.pop(loaded.id, None)
    res = await loaded.search(query="saffron kurta")
    assert any(c["label"] == "Saffron" for c in res["understood"]["chips"])
    assert res["hits"][0]["id"] == "NEW1"


# --- M4: patches and pills ---------------------------------------------------------------------------------

async def test_chip_remove_patch(loaded, catalog):
    color = next(d["color"] for d in catalog if "Water Bottle" in d["title"] and d["material"] == "Copper")
    q = f"{color.lower()} copper bottle"
    res = await loaded.search(query=q, size=50)
    chips = {c["label"]: c for c in res["understood"]["chips"]}
    assert {color, "Copper"} <= set(chips)
    assert chips[color]["remove"] == [{"op": "remove_filter", "field": "color", "value": color}]
    res2 = await loaded.search(query=q, size=50, patch=chips[color]["remove"])
    labels = [c["label"] for c in res2["understood"]["chips"]]
    assert color not in labels and "Copper" in labels
    assert color.lower() not in res2["understood"]["semantic_text"]
    colors = {h["document"]["color"] for h in res2["hits"] if h["document"]["material"] == "Copper"}
    assert len(colors) > 1


async def test_patch_price_sort_add_exclude(loaded):
    res = await loaded.search(query="water bottle", size=50, patch=[
        {"op": "set_price_range", "lte": 999}, {"op": "set_sort", "field": "price", "order": "asc"},
        {"op": "exclude", "field": "material", "value": "Plastic"}])
    prices = [h["document"]["price"] for h in res["hits"]]
    assert prices and prices == sorted(prices) and max(prices) <= 999
    assert all(h["document"]["material"] != "Plastic" for h in res["hits"])
    labels = [c["label"] for c in res["understood"]["chips"]]
    assert "Under ₹999" in labels and "Not Plastic" in labels
    res = await loaded.search(query="water bottle under 900", size=50, patch=[{"op": "set_price_range"}])
    assert not any(c["field"] == "price" for c in res["understood"]["chips"])
    res = await loaded.search(query="kurta", size=50, patch=[{"op": "add_filter", "field": "color", "value": "Red"}])
    assert res["hits"] and all(h["document"]["color"] == "Red" for h in res["hits"])


async def test_pills(loaded):
    res = await loaded.search(query="water bottle", size=20)
    fields = [p["field"] for p in res["pills"]]
    assert fields and "color" in fields
    pill = next(p for p in res["pills"] if p["field"] == "color")
    v = pill["values"][0]
    assert v["patch"] == [{"op": "add_filter", "field": "color", "value": v["value"]}]
    res2 = await loaded.search(query="water bottle", size=20, patch=v["patch"])
    assert all(h["document"]["color"] == v["value"] for h in res2["hits"])
    assert "color" not in [p["field"] for p in res2["pills"]]  # a chosen attribute is no longer a pill


# --- planner call limits (audit) ---------------------------------------------------------------------------

async def test_as_you_type_skips_llm(state, loaded, with_planner):
    fake = with_planner(FakePlanner({"semantic_text": "x", "category": None, "filters": []}))
    res = await loaded.search(query="tambe ki vorblenix", llm=False, debug=True)
    assert fake.calls == 0 and res["debug"]["llm"]["llm"] == "skipped"


async def test_identical_inflight_queries_share_one_call(state, loaded, with_planner):
    fake = with_planner(FakePlanner({"semantic_text": "copper bottle", "category": None, "filters": []}, delay=0.3))
    body = {"query": "glorpka bottle", "debug": True}
    await asyncio.gather(*(search_with(state, loaded, body, planner_timeout_ms=50, search_cache_ttl=0)
                           for _ in range(3)))
    await asyncio.sleep(0.4)
    assert fake.calls == 1


async def test_planner_concurrency_cap(state, loaded, with_planner):
    with_planner(FakePlanner({"semantic_text": "x", "category": None, "filters": []}, delay=0.5))
    outs = await asyncio.gather(*(search_with(state, loaded, {"query": f"zorbquix{"abcd"[i]}a bottle", "debug": True},
                                              planner_timeout_ms=50, search_cache_ttl=0) for i in range(4)))
    assert sum(o["debug"]["llm"]["llm"] == "busy" for o in outs) >= 2
    await asyncio.sleep(0.6)


async def test_plan_cache_bypass_is_admin_only_and_errors_hidden(state, loaded, with_planner):
    class Failing(FakePlanner):
        async def complete(self, prompt, **kw):
            self.calls += 1
            raise LLMError("provider said: secret detail")

    with_planner(Failing({}))
    r = await loaded.client.post("/v1/search", json={"query": "plorkish bottle", "debug": True},
                                 headers={**loaded.searcher, "x-zerch-plan-cache": "bypass"})
    assert "llm_error" not in (r.json()["debug"]["llm"])


async def test_request_bounds(loaded):
    r = await loaded.client.post("/v1/search", json={"query": "x", "patch": [{"op": "set_sort"}] * 21},
                                 headers=loaded.searcher)
    assert r.status_code == 422
