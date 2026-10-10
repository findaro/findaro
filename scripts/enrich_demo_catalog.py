"""Add the fields shoppers ask about to the synthetic demo catalog: country of origin, warranty, return policy,
care instructions and a few seller Q&As.

Deterministic (seeded per product id), no LLM calls. Some fields are deliberately left out for a share of
products so "the seller hasn't listed that" stays a realistic answer. Rewrites data/demo_catalog.jsonl and .csv.

    uv run python scripts/enrich_demo_catalog.py
"""

from __future__ import annotations

import csv
import hashlib
import json
import random
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
JSONL = ROOT / "data" / "demo_catalog.jsonl"
CSV = ROOT / "data" / "demo_catalog.csv"
NEW_FIELDS = ["country_of_origin", "warranty", "return_policy", "care", "seller_qa"]
MISSING_RATE = 0.12  # share of products where a field is simply not listed

ORIGIN = {  # top-level category -> weighted countries
    "Footwear": [("India", 70), ("China", 20), ("Vietnam", 10)],
    "Apparel": [("India", 82), ("Bangladesh", 12), ("China", 6)],
    "Electronics Accessories": [("China", 68), ("India", 27), ("Vietnam", 5)],
    "Home & Kitchen": [("India", 74), ("China", 26)],
    "Auto Accessories": [("India", 55), ("China", 45)],
    "Grocery Staples": [("India", 100)],
}

WARRANTY = {  # leaf category -> options (None = no warranty field at all)
    "Bluetooth Earbuds": ["6 months", "1 year"], "Neckbands": ["6 months", "1 year"],
    "Wired Earphones": ["6 months"], "Keyboards": ["1 year"], "Mouse": ["1 year", "6 months"],
    "Chargers": ["6 months", "1 year"], "Power Banks": ["6 months", "1 year"], "Cables": ["6 months", "1 year"],
    "Electric Kettles": ["1 year", "2 years"], "Pressure Cookers": ["5 years", "3 years"],
    "Kadai": ["1 year"], "Tawa": ["1 year"], "Knives": ["1 year"], "Vegetable Choppers": ["6 months"],
    "Dash Cameras": ["1 year"], "Tyre Inflators": ["6 months", "1 year"], "Car Chargers": ["6 months"],
    "Helmets": ["No warranty"], "Laptop Bags": ["6 months"],
}

RETURNS = {
    "Footwear": ["10-day return", "7-day return", "10-day size exchange"],
    "Apparel": ["10-day return", "7-day return", "10-day size exchange"],
    "Electronics Accessories": ["7-day replacement", "10-day replacement"],
    "Home & Kitchen": ["7-day return", "10-day replacement"],
    "Auto Accessories": ["7-day replacement", "No returns"],
    "Grocery Staples": ["No returns", "7-day replacement if damaged"],
}

CARE_BY_MATERIAL = {
    "Genuine Leather": "Wipe with a dry or slightly damp cloth. Use leather conditioner every few weeks. Keep away "
                       "from direct heat and let it dry naturally if it gets wet.",
    "Synthetic Leather": "Wipe clean with a damp cloth. Avoid soaking in water and keep away from direct heat.",
    "Suede": "Brush gently with a suede brush. Avoid water; if it gets wet, dry naturally away from heat.",
    "Canvas": "Hand wash in cold water with mild detergent. Air dry in shade; do not tumble dry.",
    "Mesh": "Remove loose dirt with a soft brush, wipe with a damp cloth and air dry. Do not machine wash.",
    "Knit": "Wipe with a damp cloth and air dry. Do not machine wash or dry near heat.",
    "Rubber": "Rinse with water and wipe dry.",
    "EVA": "Rinse with water and wipe dry. Keep away from direct sunlight for long periods.",
    "Synthetic": "Wipe with a damp cloth and air dry.",
    "Cotton": "Machine wash cold with similar colours. Do not bleach. Dry in shade.",
    "Cotton Blend": "Machine wash cold. Do not bleach. Dry in shade; warm iron if needed.",
    "Rayon": "Hand wash cold separately. Do not wring. Dry in shade.",
    "Georgette": "Gentle hand wash or dry clean. Dry in shade.",
    "Chiffon": "Dry clean recommended. If hand washing, use cold water and dry in shade.",
    "Silk": "Dry clean only.",
    "Polyester": "Machine wash cold. Quick dry; do not iron at high heat.",
    "Denim": "Wash inside out in cold water. Wash dark denim separately for the first few washes.",
    "Cotton Lycra": "Machine wash cold, inside out. Do not bleach or tumble dry.",
    "Cast Iron": "Wash with warm water, dry immediately and apply a thin coat of oil to prevent rust.",
    "Iron": "Wash, dry immediately and apply a thin coat of oil to prevent rust.",
    "Non-Stick": "Use wooden or silicone spatulas. Hand wash with a soft sponge; avoid metal scrubbers.",
    "Stainless Steel": "Dishwasher safe. Dry after washing to avoid water spots.",
    "Aluminium": "Hand wash. Avoid harsh scrubbers that scratch the surface.",
    "Hard Anodised": "Hand wash with a soft sponge. Not dishwasher safe.",
    "Copper": "Clean with lemon and salt or a copper cleaner to remove tarnish. Do not use in a dishwasher.",
    "Plastic": "Hand wash with mild soap. Keep away from direct flame.",
    "Velvet": "Vacuum or brush lightly. Spot clean with a damp cloth.",
    "Leatherette": "Wipe with a damp cloth. Avoid harsh chemicals.",
    "Fabric": "Remove and hand wash cold, or spot clean. Air dry.",
}
CARE_BY_TOP = {
    "Electronics Accessories": "Keep away from water and extreme heat. Use a certified charger and cable.",
    "Auto Accessories": "Wipe clean with a dry cloth. Keep away from direct heat when not in use.",
    "Grocery Staples": "Store in a cool, dry place. Keep airtight after opening.",
}

QA = {  # (question, answer template); answers only restate the product's own fields or general facts
    "Footwear": [("Is it true to size?", "Most buyers find it true to size. If you are between sizes, go one size up."),
                 ("Can I wear it daily?", "Yes, it is made for regular daily wear.")],
    "Apparel": [("Does the colour fade after washing?", "Wash it in cold water and dry in shade to keep the colour."),
                ("Is the fit as shown?", "Yes, the fit is as described on the product page.")],
    "Electronics Accessories": [("Does it come with a bill for warranty?", "Yes, a GST invoice is included."),
                                ("Is it compatible with all phones?", "It works with most phones that match the "
                                 "listed connector or connectivity.")],
    "Home & Kitchen": [("Is it safe for daily use?", "Yes, it is made for regular household use."),
                       ("Does it come with a manual?", "Yes, basic use and care instructions are included.")],
    "Auto Accessories": [("Will it fit my vehicle?", "Check the listed vehicle type and fit before ordering.")],
    "Grocery Staples": [("Is it vegetarian?", "Yes."), ("How long does it last after opening?",
                                                         "Use within 3 months of opening, stored airtight.")],
}


def rng_for(pid: str, salt: str) -> random.Random:
    return random.Random(int(hashlib.sha1(f"{pid}:{salt}".encode()).hexdigest()[:12], 16))


def weighted(r: random.Random, options: list[tuple[str, int]]) -> str:
    return r.choices([o for o, _ in options], weights=[w for _, w in options])[0]


def enrich(doc: dict) -> dict:
    pid, cat = doc["id"], doc["category"]
    top, leaf = cat.split(" > ")[0], cat.split(" > ")[-1]
    out = {k: v for k, v in doc.items() if k not in NEW_FIELDS}

    def present(field: str) -> bool:
        return rng_for(pid, "missing:" + field).random() >= MISSING_RATE

    if present("origin") and top in ORIGIN:
        out["country_of_origin"] = weighted(rng_for(pid, "origin"), ORIGIN[top])
    if leaf in WARRANTY and present("warranty"):
        out["warranty"] = rng_for(pid, "warranty").choice(WARRANTY[leaf])
    if present("returns") and top in RETURNS:
        out["return_policy"] = rng_for(pid, "returns").choice(RETURNS[top])
    care = CARE_BY_MATERIAL.get(str(doc.get("material"))) or CARE_BY_TOP.get(top)
    if care and present("care"):
        out["care"] = care
    qa = QA.get(top, [])
    if qa and present("qa"):
        r = rng_for(pid, "qa")
        picks = r.sample(qa, k=min(len(qa), r.choice([1, 2])))
        out["seller_qa"] = " ".join(f"Q: {q} A: {a}" for q, a in picks)
    return out


def main() -> None:
    docs = [json.loads(line) for line in JSONL.read_text().splitlines() if line.strip()]
    docs = [enrich(d) for d in docs]
    JSONL.write_text("".join(json.dumps(d, ensure_ascii=False) + "\n" for d in docs))
    cols: list[str] = []
    for d in docs:
        for k in d:
            if k not in cols:
                cols.append(k)
    with CSV.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for d in docs:
            w.writerow({k: ";".join(map(str, v)) if isinstance(v, list) else v for k, v in d.items()})
    have = {f: sum(1 for d in docs if f in d) for f in NEW_FIELDS}
    print(f"enriched {len(docs)} products: " + ", ".join(f"{k} {v}" for k, v in have.items()))


if __name__ == "__main__":
    main()
