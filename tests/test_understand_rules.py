"""Rules path: tokenizer, prices, quantities, Hinglish translation, catalog value matching."""

import pytest

from findaro.schema import infer_schema
from findaro.understand.dictionary import compile_payload, value_key
from findaro.understand.lexicon import default_lexicon, tokenize
from findaro.understand.plan import QueryPlan, primary_price_field, validate_plan
from findaro.understand.rules import RulesParser, describe_price

from .conftest import make_catalog

LEX = default_lexicon()


def payload_from(docs):
    """Same shape dictionary.build_payload produces, built straight from documents."""
    from collections import Counter

    schema = infer_schema(docs)
    values, paths, present, vocab = {}, {}, Counter(), Counter()
    for d in docs:
        for f in schema.fields:
            v = d.get(f.name)
            if v is None:
                continue
            present[f.name] += 1
            vals = v if isinstance(v, list) else [v]
            if f.role.value in ("facet", "keyword", "currency"):
                values.setdefault(f.name, Counter()).update(str(x) for x in vals)
            if f.role.value == "category":
                parts = str(v).split(" > ")
                paths.setdefault(f.name, Counter()).update(" > ".join(parts[: i + 1]) for i in range(len(parts)))
            if f.searchable:
                for x in vals:
                    vocab.update(t for t in tokenize(str(x)) if t.isalpha())
    payload = {"data_version": 1, "n_docs": len(docs), "coverage": {k: c / len(docs) for k, c in present.items()},
               "values": {k: c.most_common() for k, c in values.items()},
               "paths": {k: c.most_common() for k, c in paths.items()}, "vocab": dict(vocab)}
    return schema, compile_payload(payload, schema, LEX)


SCHEMA, DICT = payload_from(make_catalog(120))
P = RulesParser(SCHEMA, LEX, DICT)


def price(plan: QueryPlan):
    return next((f.value for f in plan.filters if f.field == "price"), None)


def test_tokenize():
    assert tokenize("5kg atta") == ["5", "kg", "atta"]
    assert tokenize("1.5L bottle") == ["1.5", "l", "bottle"]
    assert tokenize("₹1,299 men's t-shirt") == ["rs", "1299", "men", "t-shirt"]
    assert tokenize("rs500") == ["rs", "500"]
    assert tokenize("2k earbuds 4K cam") == ["2k", "earbuds", "4k", "cam"]


def test_value_key_normalises_units_and_plurals():
    assert value_key("5 L", LEX) == value_key("5 litre", LEX) == value_key("5l", LEX) == "5 l"
    assert value_key("Pressure Cookers", LEX) == "pressure cooker"
    assert value_key("USB-C", LEX) == "usb c"


@pytest.mark.parametrize("q,expected", [
    ("bottle under 500", {"lte": 500}),
    ("bottle below rs 500", {"lte": 500}),
    ("500 ke andar bottle", {"lte": 500}),
    ("1000 se kam mein bottle", {"lte": 1000}),
    ("bottle 500 tak", {"lte": 500}),
    ("bottle above 800", {"gte": 800}),
    ("bottle 800 se zyada", {"gte": 800}),
    ("kurta between 500 and 1000", {"gte": 500, "lte": 1000}),
    ("kurta from 1000 to 500", {"gte": 500, "lte": 1000}),
    ("kurta 500 se 1000", {"gte": 500, "lte": 1000}),
    ("kurta ₹500-₹1000", {"gte": 500, "lte": 1000}),
    ("earbuds 1.5k", {"lte": 1500}),
    ("rs 500 bottle", {"lte": 500}),
    ("budget 2000 cooker", {"lte": 2000}),
])
def test_price_phrases(q, expected):
    assert price(P.parse(q)) == expected


@pytest.mark.parametrize("q", ["500 ml bottle", "2 L cooker", "65W charger", "pack of 6 bottles", "bottle 500"])
def test_numbers_that_are_not_prices(q):
    plan = P.parse(q)
    assert price(plan) is None
    assert any(c.isdigit() for c in plan.semantic_text)  # kept as a keyword


def test_price_words_are_consumed():
    plan = P.parse("500 ke andar black shoes")
    assert plan.semantic_text == "black shoes"


def test_cheap_and_premium_are_soft_sorts():
    plan = P.parse("sasta pressure cooker")
    assert plan.sort is not None and plan.sort.order == "asc" and plan.sort.mode == "soft"
    assert "sasta" not in plan.semantic_text
    assert P.parse("premium bottle").sort.order == "desc"
    assert P.parse("budget 900 bottle").sort is None  # "budget <number>" is a price, not a sort


def test_hinglish_translation():
    plan = P.parse("kaale joote")
    assert plan.semantic_text == "black shoes"
    assert any(f.field == "color" and f.value == "Black" for f in plan.filters)
    plan = P.parse("sarson ka tel")
    assert plan.semantic_text == "mustard oil"


def test_catalog_words_are_not_translated():
    # "garam" is a lexicon word, but if the catalog itself uses a word it stays as typed
    schema, d = payload_from([{"id": i, "title": f"Garam Masala pack {i}", "category": "Spices"} for i in range(30)])
    plan = RulesParser(schema, LEX, d).parse("garam masala")
    assert plan.semantic_text == "garam masala"


def test_expansions_are_optional_synonyms():
    plan = P.parse("gents chappal")
    assert plan.semantic_text == "men chappal"
    assert set(plan.expansions) == {"sandals", "slippers"}


def test_facet_values_become_soft_filters():
    plan = P.parse("black copper bottle for women")
    by = {f.field: f for f in plan.filters}
    assert by["color"].value == "Black" and not by["color"].strict
    assert by["material"].value == "Copper"
    assert any(b.field == "category" and "Bottles" in str(b.value) for b in plan.boosts)


def test_two_values_of_one_field_become_in():
    plan = P.parse("black or white kurta")
    color = next(f for f in plan.filters if f.field == "color")
    assert color.op == "in" and set(color.value) == {"Black", "White"}


def test_longer_category_match_beats_shorter_value():
    plan = P.parse("pressure cooker")
    assert any(b.origin == "category" and b.value.endswith("Pressure Cookers") for b in plan.boosts)


def test_unparsed_tokens_and_confidence():
    plan = P.parse("glorptastic bottle")
    assert plan.unparsed_tokens == ["glorptastic"]
    assert plan.confidence == 0.5
    assert P.parse("bottel").unparsed_tokens == []  # one typo away from a corpus word


def test_non_latin_words_pass_through():
    assert "कोल्हापुरी" in P.parse("कोल्हापुरी").semantic_text


def test_validate_plan_drops_unknown_fields_and_values():
    plan = P.parse("black bottle")
    plan.filters[0].value = "Ultraviolet"
    v = validate_plan(plan, SCHEMA, DICT)
    assert not any(f.field == "color" for f in v.filters)


def test_primary_price_field_prefers_selling_price():
    schema = infer_schema([{"id": i, "title": f"Thing {i} here", "mrp": 100 + i, "sale_price": 90 + i}
                           for i in range(30)])
    assert primary_price_field(schema) == "sale_price"


def test_describe_price():
    from findaro.understand.plan import PlanFilter

    f = lambda v: PlanFilter(field="price", op="range", value=v)  # noqa: E731
    assert describe_price(f({"lte": 500}), "₹") == "Under ₹500"
    assert describe_price(f({"gte": 500, "lte": 1000}), "₹") == "₹500 – ₹1,000"
    assert describe_price(f({"gte": 2000}), "$") == "Over $2,000"


def test_codes_are_not_unparsed_words():
    assert P.parse("p017").unparsed_tokens == []
    assert P.parse("x200 charger").unparsed_tokens == []


def test_head_word_of_a_facet_value_matches_every_value_ending_in_it():
    docs = []
    for i, (mat, size) in enumerate([("Stainless Steel", "Free Size"), ("Carbon Steel", "M"), ("Plastic", "L"),
                                     ("Stainless Steel", "M"), ("Glass", "Free Size"), ("Plastic", "S")] * 4):
        docs.append({"id": f"p{i}", "title": f"{mat} bottle {i}", "category": "Home > Bottles", "material": mat,
                     "size": size, "price": 100 + i})
    schema, d = payload_from(docs)
    assert "steel" in d.head_keys
    assert "size" not in d.values  # a word of the field's own name never becomes a value of that field
    plan = validate_plan(RulesParser(schema, LEX, d).parse("steel bottle"), schema, d)
    assert not any(f.field == "material" for f in plan.filters)  # too weak to filter on: ranks instead
    b = next(b for b in plan.boosts if b.field == "material")
    assert sorted(b.value) == ["Carbon Steel", "Stainless Steel"]
    plan = validate_plan(RulesParser(schema, LEX, d).parse("stainless steel bottle"), schema, d)
    f = next(f for f in plan.filters if f.field == "material")
    assert f.value == "Stainless Steel"  # the full value still wins over its head word


def test_a_value_word_means_its_whole_family():
    docs = []
    for i, mat in enumerate(["Leather", "Genuine Leather", "Synthetic Leather", "Canvas", "Mesh", "Leather"] * 4):
        docs.append({"id": f"s{i}", "title": f"{mat} shoe {i}", "category": "Footwear > Shoes", "material": mat,
                     "price": 500 + i})
    schema, d = payload_from(docs)
    plan = validate_plan(RulesParser(schema, LEX, d).parse("leather shoes"), schema, d)
    f = next(f for f in plan.filters if f.field == "material")
    assert f.op == "in" and sorted(f.value) == ["Genuine Leather", "Leather", "Synthetic Leather"]
    plan = validate_plan(RulesParser(schema, LEX, d).parse("genuine leather shoes"), schema, d)
    f = next(f for f in plan.filters if f.field == "material")
    assert f.value == "Genuine Leather"  # an exact longer value stays exact
