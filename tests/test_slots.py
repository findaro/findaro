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


# --- claim checks (from real failures in the M4 chat review) ---------------------------------------------

SHOWN = {
    "B1": {"id": "B1", "title": "Zorvik Black Steel Water Bottle", "category": "Home > Storage > Bottles",
           "color": "Black", "material": "Steel", "price": 499, "in_stock": True},
    "B2": {"id": "B2", "title": "Kosmo Copper Water Bottle", "category": "Home > Storage > Bottles",
           "color": "Copper", "material": "Copper", "price": 1299, "in_stock": False},
    "C1": {"id": "C1", "title": "Tarangi Steel Pressure Cooker", "category": "Home > Cookware > Pressure Cookers",
           "color": "Silver", "material": "Steel", "price": 1599, "in_stock": True},
}


def check(sentence, facts=None):
    return SlotFiller(SHOWN, SCHEMA, "₹", facts or {}).check(sentence)


def test_uncited_attribute_or_stock_claims_are_dropped():
    assert check("The Kosmo bottle is made of copper.")[0] is None
    assert check("Both are in stock.")[0] is None
    assert check("Here are a few options for you.")[0] is not None  # no claim, fine without a citation


def test_all_claims_must_hold_for_every_product():
    assert check("All of these are made of steel [B1].")[0] is None  # B2 is copper
    assert check("Sabhi stock mein hain [B1] [C1].")[0] is None  # B2 is out of stock
    assert check("Dono steel ke hain [B1] [C1].")[0] is not None  # both cited ones are steel


def test_product_type_must_fit_the_cited_product():
    assert check("The cheapest pressure cooker is [B1].", {"low_price": "B1"})[0] is None
    assert check("A pressure cooker [C1] in steel.")[0] is not None
    assert check("Water bottles [B1] and pressure cookers [C1] are shown.")[0] is not None


def test_generic_lowest_highest_need_the_computed_fact():
    facts = {"low_price": "B1", "high_price": "B2"}
    assert check("The lowest and highest prices are [B1] and [C1].", facts)[0] is None
    assert check("The lowest and highest prices are [B1] and [B2].", facts)[0] is not None
    assert check("[C1] has the highest rating.", {"top_rating": "B1"})[0] is None


def test_stock_claim_checked_against_cited_product():
    assert check("[B2] is in stock.")[0] is None
    assert check("[B1] is in stock.")[0] is not None


def test_repeated_symbol_and_unit_collapsed():
    f = SlotFiller({"V1": {"id": "V1", "title": "Oil", "price": 199, "color": "5 L"}}, SCHEMA, "₹")
    assert f.check("[V1] costs ₹{price:V1} for {color:V1} L.")[0] == "[V1] costs ₹199 for 5 L."


def test_ordinals_count_as_citations():
    f = SlotFiller(SHOWN, SCHEMA, "₹", {}, order=["B1", "B2", "C1"])
    assert f.check("Yes, the second one is made of copper.")[0] is not None
    assert f.check("Yes, the first one is made of copper.")[0] is None


def test_spelled_out_counts_and_wrong_names_dropped():
    assert check("Two bottles are in stock [B1].")[0] is None
    assert check("Kosmo makes this steel bottle [B1].")[0] is None  # Kosmo is B2's brand
    assert check("Zorvik makes this steel bottle [B1].")[0] is not None


def test_not_shown_claim_when_field_exists():
    assert check("The rating of [B1] is not shown.")[0] is not None  # B1 has no rating: true
    shown = dict(SHOWN, B1=dict(SHOWN["B1"], rating=4.2))
    assert SlotFiller(shown, SCHEMA, "₹", {}).check("The rating of [B1] is not shown.")[0] is None


def test_hindi_superlatives_and_available():
    f = {"top_rating": "B1", "low_price": "B1", "high_price": "B2"}
    assert check("Sabse adhik rating wala [C1] hai.", f)[0] is None
    assert check("Sabse adhik rating wala [B1] hai.", f)[0] is not None
    assert check("Sabse kam daam [C1] ka hai.", f)[0] is None
    assert check("[B2] is available.")[0] is None  # B2 is out of stock
    assert check("Kosmoin bottle [B1] is steel.")[0] is None  # misspelt brand of B2


# --- product conversation: general part and focus (M5) -----------------------------------------------------

def run_parts(chunks, focus):
    """Returns ([(part, joined text)], filler) with whitespace normalised."""
    f = SlotFiller(SHOWN, SCHEMA, "₹", {}, focus=focus)

    async def go():
        return [p async for p in f.stream_parts(chunks)]

    joined: dict[str, str] = {}
    for part, text in asyncio.run(go()):
        joined[part] = joined.get(part, "") + text
    return [(p, " ".join(t.split())) for p, t in joined.items() if t.strip()], f


def test_answer_and_general_parts():
    parts, f = run_parts(["It is made of steel and costs {price:B1}. ", "General: Steel bottles ",
                          "keep water cool and are easy to clean."], ["B1"])
    assert parts == [("answer", "It is made of steel and costs ₹499."),
                     ("general", "Steel bottles keep water cool and are easy to clean.")]


def test_general_part_cannot_carry_product_claims():
    parts, f = run_parts(["Steel [B1]. General: Kosmo bottles are great. Most bottles hold two litres. "
                          "This one is copper. Copper bottles need regular cleaning."], ["B1"])
    general = [t for p, t in parts if p == "general"]
    assert general == ["Copper bottles need regular cleaning."]
    assert {r for _, r in f.dropped} >= {"general part names a product", "number in general part"}


def test_focus_counts_as_citation_and_is_checked():
    parts, _ = run_parts(["It is made of copper. ", "It is made of steel."], ["B1"])
    assert parts == [("answer", "It is made of steel.")]


def test_part_labels_from_the_model_are_handled():
    parts, _ = run_parts(["Part 1: It is made of steel. Part 2: Steel bottles are easy to clean."], ["B1"])
    assert parts == [("answer", "It is made of steel."), ("general", "Steel bottles are easy to clean.")]


def test_hasnt_listed_when_field_is_listed_is_dropped():
    f = SlotFiller(SHOWN, SCHEMA, "₹", {}, focus=["B1"])
    assert f.check("The seller hasn't listed the material.")[0] is None
    assert f.check("The seller hasn't listed the warranty.")[0] is not None  # no such field: nothing to contradict


def test_suitability_verdicts_only_from_the_listing():
    shown = dict(SHOWN, B1=dict(SHOWN["B1"], description="A steel bottle, perfect for daily office use."))
    f = SlotFiller(shown, SCHEMA, "₹", {}, focus=["B1"])
    assert f.check("You can wear it in the rain.")[0] is None
    assert f.check("Haan, aap ise barish mein le ja sakte hain.")[0] is None
    assert f.check("It is waterproof.")[0] is None
    assert f.check("The listing says it is perfect for daily office use.")[0] is not None  # its own words
    assert f.check_general("Steel bottles are fine for daily use.")[0] is not None  # general tips may judge


def test_okay_to_wear_is_a_verdict():
    f = SlotFiller(SHOWN, SCHEMA, "₹", {}, focus=["B1"])
    assert f.check("It's probably okay to wear in light rain.")[0] is None


def test_catalog_wide_values_and_listed_numbers():
    shown = {"K1": {"id": "K1", "title": "Steel Kettle", "material": "Steel", "warranty": "6 months", "price": 999,
                    "category": "Home > Kitchen > Kettles"}}
    known = {"india": {"country_of_origin"}, "china": {"country_of_origin"}, "copper": {"material"}}
    f = SlotFiller(shown, SCHEMA, "₹", {}, focus=["K1"], known_values=known)
    assert f.check("It is made in India.")[0] is None  # origin not listed for this product
    assert f.check("It has a 6 months warranty.")[0] is not None  # number from its own listing
    assert f.check("It has a 12 months warranty.")[0] is None
    assert f.check("The seller doesn't explicitly state a warranty.")[0] is not None  # no warranty field in SCHEMA
    assert f.check("Haan, return ho jayega.")[0] is None
    assert f.check("Ye roz use ke liye theek hai.")[0] is None


def test_return_promises_need_a_listed_policy():
    with_policy = {"R1": {"id": "R1", "title": "Steel Bottle", "material": "Steel", "return_policy": "10-day return"}}
    without = {"R2": {"id": "R2", "title": "Steel Bottle", "material": "Steel"}}
    assert SlotFiller(with_policy, SCHEMA, "₹", {}, focus=["R1"]).check("You can return it.")[0] is not None
    assert SlotFiller(without, SCHEMA, "₹", {}, focus=["R2"]).check("Haan, return ho jayega.")[0] is None
    assert SlotFiller(without, SCHEMA, "₹", {}, focus=["R2"]).check("Roz use ke liye to theek hai.")[0] is None


def test_field_content_vs_missing_field():
    docs = {"D1": {"id": "D1", "title": "Car Charger", "material": "Plastic",
                   "description": "Perfect for long road trips."}}
    f = SlotFiller(docs, SCHEMA, "₹", {}, focus=["D1"])
    assert f.check("The description doesn't specifically mention rain.")[0] is not None
    assert f.check("The description is not listed.")[0] is None
    assert f.check("The seller hasn't listed the material.")[0] is None
    assert f.check("It's best to check the box before use.")[0] is not None


def test_replacement_is_not_a_return():
    docs = {"E1": {"id": "E1", "title": "USB Cable", "material": "PVC", "return_policy": "10-day replacement"}}
    f = SlotFiller(docs, SCHEMA, "₹", {}, focus=["E1"])
    assert f.check("You can return it within 10 days if you don't like it.")[0] is None
    assert f.check("The return policy is a 10-day replacement.")[0] is not None
    assert SlotFiller({"G1": {"id": "G1", "title": "Garam Masala"}}, SCHEMA, "₹", {}, focus=["G1"]).check(
        "Agar pasand nahin aaya to return karne ka option mil jayega.")[0] is None
