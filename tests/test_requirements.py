from findaro.schema.model import Schema
from findaro.search.requirements import check


async def test_hits_say_which_requirements_they_meet(loaded):
    res = await loaded.search(query="black leather phone cover")
    chips = {c["label"] for c in res["understood"]["chips"] if c["kind"] in ("filter", "boost")}
    assert "Black" in chips, res["understood"]
    assert res["hits"]
    for hit in res["hits"]:
        r = hit["requirements"]
        assert r["total"] == len(r["met"]) + len(r["unmet"]) + len(r["unknown"])
        assert ("Black" in r["met"]) == (hit["document"]["color"] == "Black")
        assert ("Black" in r["unmet"]) == (hit["document"]["color"] != "Black")


async def test_no_requirements_without_understood_attributes(loaded):
    res = await loaded.search(query="zxqv")
    assert all(h.get("requirements") is None for h in res["hits"])


def test_check_semantics():
    schema = Schema.model_validate({"id_field": "id", "fields": [
        {"name": "id", "role": "id"}, {"name": "cat", "role": "category"}, {"name": "price", "role": "price"},
        {"name": "color", "role": "facet"}, {"name": "in_stock", "role": "boolean"}]})
    doc = {"cat": "Footwear > Men > Shoes", "price": 799, "color": ["Black", "Brown"], "in_stock": True}
    assert check(schema, doc, "cat", "eq", "Footwear > Men") is True  # a path matches its subtree
    assert check(schema, doc, "cat", "eq", "Footwear > Women") is False
    assert check(schema, doc, "price", "range", {"lte": 1000}) is True
    assert check(schema, doc, "price", "range", {"gte": 1000}) is False
    assert check(schema, doc, "color", "in", ["black"]) is True  # case-insensitive, any value of a list field
    assert check(schema, doc, "color", "not", ["black"]) is False
    assert check(schema, doc, "in_stock", "eq", True) is True
    assert check(schema, {"price": 5}, "color", "eq", "Black") is None  # missing field: unknown, not unmet
