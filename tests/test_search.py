import pytest


async def test_basic_relevance(loaded, catalog):
    res = await loaded.search(query="pressure cooker", size=10)
    assert res["hits"], res
    assert all("Pressure Cooker" in h["document"]["title"] for h in res["hits"][:5])
    assert res["total"] >= 10


async def test_typo_tolerance(loaded):
    res = await loaded.search(query="presure coker", size=5)
    assert res["hits"] and "Pressure Cooker" in res["hits"][0]["document"]["title"]


async def test_transliteration_and_phonetic(loaded):
    # Devanagari input is transliterated; romanised spelling variants match via the phonetic subfield.
    res = await loaded.search(query="कोल्हापुरी", size=3)
    assert res["hits"] and "Kolhapuri" in res["hits"][0]["document"]["title"]
    res = await loaded.search(query="kolhapuree chappals", size=3)
    assert res["hits"] and "Kolhapuri" in res["hits"][0]["document"]["title"]


async def test_attribute_match_across_fields(loaded, catalog):
    res = await loaded.search(query="black water bottle", size=5)
    top = res["hits"][0]["document"]
    assert top["color"] == "Black" and "Water Bottle" in top["title"]


async def test_facet_and_numeric_filters(loaded, catalog):
    res = await loaded.search(query="", filters={"color": "black", "price": {"gte": 300, "lte": 1000}}, size=100)
    expected = {d["id"] for d in catalog if d["color"] == "Black" and 300 <= d["price"] <= 1000}
    assert {h["id"] for h in res["hits"]} == expected
    assert res["total"] == len(expected)


async def test_filter_any_of_and_not(loaded, catalog):
    res = await loaded.search(query="", filters={"brand": ["Zorvik", "Kosmo"], "color": {"not": ["Red"]}}, size=100)
    expected = {d["id"] for d in catalog if d["brand"] in ("Zorvik", "Kosmo") and d["color"] != "Red"}
    assert {h["id"] for h in res["hits"]} == expected


async def test_category_prefix_filter(loaded, catalog):
    res = await loaded.search(query="", filters={"category": "Footwear"}, size=100)
    assert res["total"] == sum(1 for d in catalog if d["category"].startswith("Footwear"))
    res = await loaded.search(query="", filters={"category": "footwear>women"}, size=100)
    assert res["total"] == sum(1 for d in catalog if d["category"].startswith("Footwear > Women"))


async def test_boolean_and_multi_value_filters(loaded, catalog):
    res = await loaded.search(query="", filters={"in_stock": False, "tags": "eco"}, size=100)
    expected = {d["id"] for d in catalog if not d["in_stock"] and "eco" in d["tags"]}
    assert {h["id"] for h in res["hits"]} == expected


async def test_filters_apply_to_hybrid_results(loaded):
    res = await loaded.search(query="phone cover", filters={"color": "Blue"}, size=20)
    assert res["hits"] and all(h["document"]["color"] == "Blue" for h in res["hits"])


async def test_facet_counts(loaded, catalog):
    res = await loaded.search(query="", size=1)
    colors = {v["value"]: v["count"] for v in res["facets"]["color"]["values"]}
    for c in {d["color"] for d in catalog}:
        assert colors[c] == sum(1 for d in catalog if d["color"] == c)
    assert res["facets"]["price"]["type"] == "stats"
    assert res["facets"]["price"]["min"] == min(d["price"] for d in catalog)
    cats = {v["value"]: v["count"] for v in res["facets"]["category"]["values"]}
    assert cats["Footwear"] == sum(1 for d in catalog if d["category"].startswith("Footwear"))
    res = await loaded.search(query="", size=1, facets=["brand"])
    assert list(res["facets"]) == ["brand"]


async def test_sort_and_pagination(loaded, catalog):
    res = await loaded.search(query="", sort="price:desc", size=5)
    prices = [h["document"]["price"] for h in res["hits"]]
    assert prices == sorted(prices, reverse=True) and prices[0] == max(d["price"] for d in catalog)
    res = await loaded.search(query="bottle", sort=[{"field": "price", "order": "asc"}], size=50)
    prices = [h["document"]["price"] for h in res["hits"]]
    assert prices == sorted(prices)
    p1 = await loaded.search(query="", sort="-rating", size=7, page=1)
    p2 = await loaded.search(query="", sort="-rating", size=7, page=2)
    assert not {h["id"] for h in p1["hits"]} & {h["id"] for h in p2["hits"]}
    q1 = await loaded.search(query="kurta", size=3, page=1)
    q2 = await loaded.search(query="kurta", size=3, page=2)
    assert not {h["id"] for h in q1["hits"]} & {h["id"] for h in q2["hits"]}


async def test_highlighting(loaded):
    res = await loaded.search(query="copper bottle", size=3)
    hl = res["hits"][0].get("highlights") or {}
    assert "<em>" in hl.get("title", "")
    res = await loaded.search(query="copper bottle", size=3, highlight=False)
    assert "highlights" not in res["hits"][0]


async def test_sku_lookup(loaded):
    res = await loaded.search(query="p017", size=3)
    assert res["hits"][0]["id"] == "P017"


@pytest.mark.parametrize("body,code", [
    ({"filters": {"nope": 1}}, "invalid_filter"),
    ({"filters": {"title": "x"}}, "invalid_filter"),
    ({"filters": {"price": {"between": 1}}}, "invalid_filter"),
    ({"filters": {"price": "cheap"}}, "invalid_filter"),
    ({"sort": "description:asc"}, "invalid_sort"),
    ({"facets": ["title"]}, "invalid_facet"),
    ({"page": 500, "size": 100}, "page_too_deep"),
])
async def test_invalid_requests(loaded, body, code):
    r = await loaded.client.post("/v1/search", json={"query": "x", **body}, headers=loaded.searcher)
    assert r.status_code == 400, r.text
    assert r.json()["error"]["code"] == code


async def test_validation_errors(loaded):
    r = await loaded.client.post("/v1/search", json={"size": 1000}, headers=loaded.searcher)
    assert r.status_code == 422


async def test_empty_project_returns_nothing(project):
    res = await project.search(query="anything")
    assert res["total"] == 0 and res["hits"] == []


async def test_cache(loaded, state):
    from dataclasses import replace

    import httpx

    from zerch.main import create_app

    from .conftest import make_settings

    st = replace(state, settings=make_settings(search_cache_ttl=30))
    app = create_app(st.settings, state.embedder)
    app.state.zerch = st
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        a = (await c.post("/v1/search", json={"query": "kurta"}, headers=loaded.searcher)).json()
        b = (await c.post("/v1/search", json={"query": "kurta"}, headers=loaded.searcher)).json()
        n = (await c.post("/v1/search", json={"query": "kurta"},
                          headers={**loaded.searcher, "cache-control": "no-cache"})).json()
    assert not a.get("cached") and b["cached"] and not n.get("cached")
    assert [h["id"] for h in a["hits"]] == [h["id"] for h in b["hits"]]
