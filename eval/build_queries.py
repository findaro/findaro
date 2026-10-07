"""Build eval/queries.jsonl from the demo catalog.

Each query has a predicate over the catalog's structured attributes (which the generator sampled, so
they are ground truth). Relevance grades:
    2 = satisfies the full predicate (category + attributes + price)
    1 = right category, but some attribute or price constraint is off
Hinglish and natural-language queries need a human check that the predicate captures what the query
means. Decisions live in eval/reviews.json (approved / changed predicate / dropped); a query of those
types without a decision is written with needs_review: true.

    uv run python eval/build_queries.py
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CATALOG = ROOT / "data" / "demo_catalog.jsonl"
OUT = ROOT / "eval" / "queries.jsonl"
REVIEWS = ROOT / "eval" / "reviews.json"

FW, AP, EL, HK, AU, GR = ("Footwear", "Apparel", "Electronics Accessories", "Home & Kitchen", "Auto Accessories",
                          "Grocery Staples")

# (type, query, predicate). Predicate keys: cat (prefix or list of prefixes), price_max, price_min,
# and any attribute name -> value (case-insensitive; list attributes match by membership).
Q: list[tuple[str, str, dict]] = [
    # plain
    ("plain", "pressure cooker", {"cat": f"{HK} > Cookware > Pressure Cookers"}),
    ("plain", "bluetooth earbuds", {"cat": f"{EL} > Audio > Bluetooth Earbuds"}),
    ("plain", "kolhapuri chappals", {"cat": f"{FW} > Women > Kolhapuri Chappals"}),
    ("plain", "car seat cover", {"cat": f"{AU} > Car > Seat Covers"}),
    ("plain", "garam masala", {"cat": f"{GR} > Spices & Masalas > Garam Masala"}),
    ("plain", "desi ghee", {"cat": f"{GR} > Ghee & Butter > Ghee"}),
    ("plain", "leggings", {"cat": f"{AP} > Women > Leggings"}),
    ("plain", "electric kettle", {"cat": f"{HK} > Appliances > Electric Kettles"}),
    ("plain", "dinner set", {"cat": f"{HK} > Dinnerware > Dinner Sets"}),
    ("plain", "neckband", {"cat": f"{EL} > Audio > Neckbands"}),
    # typos
    ("typo", "presure cooker", {"cat": f"{HK} > Cookware > Pressure Cookers"}),
    ("typo", "wirless earbuds", {"cat": f"{EL} > Audio > Bluetooth Earbuds"}),
    ("typo", "kolapuri chappal", {"cat": f"{FW} > Women > Kolhapuri Chappals"}),
    ("typo", "car seet cover", {"cat": f"{AU} > Car > Seat Covers"}),
    ("typo", "garam masla", {"cat": f"{GR} > Spices & Masalas > Garam Masala"}),
    ("typo", "bluetoth neckband", {"cat": f"{EL} > Audio > Neckbands"}),
    ("typo", "basmathi rice", {"cat": f"{GR} > Rice > Basmati Rice"}),
    ("typo", "runing shoes", {"cat": f"{FW} > Men > Running Shoes"}),
    ("typo", "electrik kettle", {"cat": f"{HK} > Appliances > Electric Kettles"}),
    ("typo", "helmat for bike", {"cat": f"{AU} > Bike > Helmets"}),
    ("typo", "lether formal shoes", {"cat": f"{FW} > Men > Formal Shoes", "material": ["Genuine Leather",
                                                                                         "Synthetic Leather",
                                                                                         "Patent Leather"]}),
    # attribute-heavy
    ("attribute", "black running shoes for men", {"cat": f"{FW} > Men > Running Shoes", "color": "Black"}),
    ("attribute", "white canvas sneakers men", {"cat": f"{FW} > Men > Casual Sneakers", "color": "White",
                                                "material": "Canvas"}),
    ("attribute", "brown formal shoes genuine leather", {"cat": f"{FW} > Men > Formal Shoes", "color": "Brown",
                                                         "material": "Genuine Leather"}),
    ("attribute", "65W usb-c charger", {"cat": f"{EL} > Mobile Accessories > Chargers", "wattage": "65W",
                                        "connector": "USB-C"}),
    ("attribute", "20000mAh power bank", {"cat": f"{EL} > Mobile Accessories > Power Banks",
                                          "capacity": "20000mAh"}),
    ("attribute", "stainless steel water bottle 1 L", {"cat": f"{HK} > Storage & Containers > Water Bottles",
                                                       "material": "Stainless Steel", "capacity": "1 L"}),
    ("attribute", "cast iron tawa", {"cat": f"{HK} > Cookware > Tawa", "material": "Cast Iron"}),
    ("attribute", "black full face helmet", {"cat": f"{AU} > Bike > Helmets", "color": "Black",
                                             "helmet_type": "Full Face"}),
    ("attribute", "slim fit black jeans", {"cat": f"{AP} > Men > Jeans", "fit": "Slim Fit", "color": "Black"}),
    ("attribute", "white cotton kurta for men", {"cat": f"{AP} > Men > Kurtas", "color": "White",
                                                 "material": "Cotton"}),
    ("attribute", "red silk saree", {"cat": f"{AP} > Women > Sarees", "color": "Red", "material": "Silk"}),
    ("attribute", "kachi ghani mustard oil 1 L", {"cat": f"{GR} > Edible Oils > Mustard Oil",
                                                  "process": "Kachi Ghani", "volume": "1 L"}),
    ("attribute", "wireless mouse", {"cat": f"{EL} > Computer Accessories > Mouse", "connectivity": "Wireless"}),
    ("attribute", "toor dal 1 kg", {"cat": f"{GR} > Dals & Pulses > Toor Dal", "weight": "1 kg"}),
    # price-constrained
    ("price", "running shoes under 1000", {"cat": f"{FW} > Men > Running Shoes", "price_max": 1000}),
    ("price", "bluetooth earbuds below 1500", {"cat": f"{EL} > Audio > Bluetooth Earbuds", "price_max": 1500}),
    ("price", "men's t-shirt under 300", {"cat": f"{AP} > Men > T-Shirts", "price_max": 300}),
    ("price", "saree under rs 1000", {"cat": f"{AP} > Women > Sarees", "price_max": 1000}),
    ("price", "dash cam under 3000", {"cat": f"{AU} > Car > Dash Cameras", "price_max": 3000}),
    ("price", "20000mah power bank under 1500", {"cat": f"{EL} > Mobile Accessories > Power Banks",
                                                 "capacity": "20000mAh", "price_max": 1500}),
    ("price", "5 L pressure cooker under 2000", {"cat": f"{HK} > Cookware > Pressure Cookers", "capacity": "5 L",
                                                 "price_max": 2000}),
    ("price", "laptop bag under 800", {"cat": f"{EL} > Computer Accessories > Laptop Bags", "price_max": 800}),
    ("price", "kurti between 500 and 1000", {"cat": f"{AP} > Women > Kurtis", "price_min": 500,
                                             "price_max": 1000}),
    ("price", "car perfume under 300", {"cat": f"{AU} > Car > Car Perfumes", "price_max": 300}),
    # Hinglish
    ("hinglish", "500 ke andar black shoes", {"cat": FW, "color": "Black", "price_max": 500}),
    ("hinglish", "kapde rakhne wala bag", {"cat": f"{HK} > Home Storage > Cloth Organisers"}),
    ("hinglish", "ladkiyon ke liye kurti", {"cat": f"{AP} > Women > Kurtis"}),
    ("hinglish", "sasta pressure cooker", {"cat": f"{HK} > Cookware > Pressure Cookers", "price_max": 1500}),
    ("hinglish", "gaadi ke liye phone stand", {"cat": f"{AU} > Car > Phone Holders"}),
    ("hinglish", "chai patti 1 kg", {"cat": f"{GR} > Tea & Coffee > Tea", "weight": "1 kg"}),
    ("hinglish", "gents chappal", {"cat": [f"{FW} > Men > Sandals & Floaters", f"{FW} > Men > Flip Flops & Slippers"]}),
    ("hinglish", "shaadi ke liye silk saree", {"cat": f"{AP} > Women > Sarees", "material": "Silk"}),
    ("hinglish", "khana banane ke bartan", {"cat": f"{HK} > Cookware"}),
    ("hinglish", "mobile charge karne wala tar", {"cat": f"{EL} > Mobile Accessories > Cables"}),
    ("hinglish", "sarson ka tel", {"cat": f"{GR} > Edible Oils > Mustard Oil"}),
    ("hinglish", "1000 se kam mein earbuds", {"cat": f"{EL} > Audio > Bluetooth Earbuds", "price_max": 1000}),
    ("hinglish", "bacchon ke school ke joote", {"cat": f"{FW} > Kids > School Shoes"}),
    # natural language
    ("nl", "something to carry water to office", {"cat": f"{HK} > Storage & Containers > Water Bottles"}),
    ("nl", "shoes for jogging in the morning", {"cat": f"{FW} > Men > Running Shoes"}),
    ("nl", "comfortable footwear for women under 1000", {"cat": f"{FW} > Women", "price_max": 1000}),
    ("nl", "fast charger for my phone", {"cat": f"{EL} > Mobile Accessories > Chargers"}),
    ("nl", "cover to protect my scooter from rain and dust", {"cat": f"{AU} > Bike > Bike Covers"}),
    ("nl", "keep my car smelling fresh", {"cat": f"{AU} > Car > Car Perfumes"}),
    ("nl", "oil for cooking", {"cat": f"{GR} > Edible Oils"}),
    ("nl", "camera that records the road while driving", {"cat": f"{AU} > Car > Dash Cameras"}),
]


def _cat_ok(doc: dict, cat: str | list[str]) -> bool:
    cats = cat if isinstance(cat, list) else [cat]
    return any(doc["category"] == c or doc["category"].startswith(c + " > ") for c in cats)


def _price(doc: dict) -> float:
    return float(doc["price"])


def _attr_ok(doc: dict, k: str, v) -> bool:
    if k == "price_max":
        return _price(doc) <= v
    if k == "price_min":
        return _price(doc) >= v
    have = doc.get(k)
    if have is None:
        return False
    want = {str(x).lower() for x in (v if isinstance(v, list) else [v])}
    haves = {str(x).lower() for x in (have if isinstance(have, list) else [have])}
    return bool(want & haves)


def grade(doc: dict, pred: dict) -> int:
    if not _cat_ok(doc, pred["cat"]):
        return 0
    return 2 if all(_attr_ok(doc, k, v) for k, v in pred.items() if k != "cat") else 1


def main() -> None:
    docs = [json.loads(line) for line in CATALOG.read_text().splitlines() if line.strip()]
    decisions = json.loads(REVIEWS.read_text())["decisions"] if REVIEWS.exists() else {}
    n = 0
    with open(OUT, "w") as f:
        for i, (typ, query, pred) in enumerate(Q, 1):
            qid = f"q{i:03d}"  # ids stay positional even when a query is dropped
            decision = decisions.get(qid, {})
            if decision.get("status") == "dropped":
                continue
            if decision.get("status") == "changed":
                pred = decision["predicate"]
            rel = [d["id"] for d in docs if grade(d, pred) == 2]
            partial = [d["id"] for d in docs if grade(d, pred) == 1]
            row = {"id": qid, "query": query, "type": typ, "predicate": pred, "relevant": rel,
                   "partial": partial, "needs_review": typ in ("hinglish", "nl") and not decision}
            if decision:
                row["review"] = decision["status"]
            n += 1
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
            if not rel:
                print(f"warning: {query!r} has no fully relevant docs")
    print(f"wrote {n} queries to {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
