import asyncio

from zerch.chat.answer import computed_facts, slotted
from zerch.chat.slots import SlotFiller

from .test_understand_rules import SCHEMA

DOCS = {"P001": {"id": "P001", "title": "Zorvik Black Steel Water Bottle", "price": 499, "rating": 4.2,
                 "tags": ["new", "eco"], "in_stock": True},
        "P002": {"id": "P002", "title": "Kosmo Copper Water Bottle", "price": 1299, "rating": 4.6}}
FACTS = {"low_price": "P001", "high_price": "P002", "top_rating": "P002"}


def run(chunks, facts=FACTS):
    f = SlotFiller(DOCS, SCHEMA, "₹", facts)

    async def go():
        return [c async for c in f.stream(chunks)]

    return "".join(asyncio.run(go())), f


def test_slots_are_filled_from_documents():
    text, f = run(["{title:P001} [P001] costs {pri", "ce:P001} and is rated {rating:P001}."])
    assert text == "Zorvik Black Steel Water Bottle [P001] costs ₹499 and is rated 4.2."
    assert f.filled == 3 and not f.dropped


def test_model_written_number_drops_the_whole_sentence():
    text, f = run(["Kosmo bottle [P002] costs ₹1,199, a fair price. ", "Zorvik [P001] is {price:P001}."])
    assert text.strip() == "Zorvik [P001] is ₹499."
    assert f.dropped[0][1] == "number written by the model"


def test_slot_for_an_uncited_product_is_dropped():
    # misattribution: talks about P002 but places P001's price
    text, f = run(["Kosmo [P002] costs {price:P001}. ", "Kosmo [P002] costs {price:P002}."])
    assert text.strip() == "Kosmo [P002] costs ₹1,299."
    assert "doesn't cite" in f.dropped[0][1]


def test_unknown_product_field_or_missing_value_drop_the_sentence():
    text, _ = run(["Great pick [P009]. ", "Weight {weight:P001} [P001]. ", "Costs {price:P002} [P002]."])
    assert text.strip() == "Costs ₹1,299 [P002]."


def test_comparisons_only_for_the_computed_product():
    text, f = run(["The cheapest is Kosmo [P002]. ", "The cheapest is Zorvik [P001] at {price:P001}. ",
                   "Sabse accha rating Kosmo [P002] ka hai."])
    assert text.strip() == "The cheapest is Zorvik [P001] at ₹499. Sabse accha rating Kosmo [P002] ka hai."
    text, _ = run(["The cheapest is Zorvik [P001]."], facts={})
    assert text == ""


def test_lists_booleans_and_ids_with_digits():
    text, _ = run(["Tags: {tags:P001}; in stock: {in_stock:P001} [P001]. ", "Try [P001] or [P002]."])
    assert text == "Tags: new, eco; in stock: yes [P001]. Try [P001] or [P002]."


def test_prompt_views_hide_numbers():
    v = slotted("P001", {"title": "Steel Bottle 1 L", "price": 499, "color": "Black", "in_stock": True}, SCHEMA)
    assert v == {"title": "Steel Bottle # L", "price": "{price:P001}", "color": "Black", "in_stock": True}
    text, f = run(["Zorvik [P001] holds # L of water."])
    assert text == "" and f.dropped[0][1] == "masked number copied"
    lines, ids = computed_facts([("P001", DOCS["P001"]), ("P002", DOCS["P002"])], SCHEMA)
    assert ids == {"low_price": "P001", "high_price": "P002", "top_rating": "P002"}
    assert not any(c.isdigit() for line in lines for c in line.replace("P001", "").replace("P002", ""))
