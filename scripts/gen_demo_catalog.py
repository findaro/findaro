"""Generate a synthetic Indian e-commerce demo catalog with an LLM.

Structured attributes (category, colour, material, size, price, ...) are sampled here from a
taxonomy, deterministically from --seed. They are the ground truth the eval set is built on.
The LLM invents brand names and writes messy marketplace-style titles and short descriptions.
Every brand is invented; nothing here is scraped.

    uv run python scripts/gen_demo_catalog.py                 # Ollama (llama3.1:8b by default)
    uv run python scripts/gen_demo_catalog.py --provider anthropic --model claude-sonnet-5-5
    uv run python scripts/gen_demo_catalog.py --assemble-only # rebuild outputs from cache

LLM replies are cached under data/.gen_cache so interrupted runs resume. Outputs:
data/demo_catalog.jsonl and data/demo_catalog.csv.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import hashlib
import json
import random
import re
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

from zerch.llm import LLMError, get_llm
from zerch.llm.base import parse_json

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
CACHE = DATA / ".gen_cache"

COLORS = [
    "Black", "White", "Grey", "Navy Blue", "Blue", "Sky Blue", "Red", "Maroon", "Pink", "Peach",
    "Green", "Olive", "Mint Green", "Yellow", "Mustard", "Orange", "Brown", "Tan", "Beige", "Cream",
    "Purple", "Wine", "Silver", "Gold", "Copper", "Rose Gold", "Teal", "Multicolor", "Transparent",
]
# Colour words that must not appear in a title unless they are the product's colour.
COLOR_WORDS = sorted(
    {w.lower() for c in COLORS for w in c.split()} - {"multicolor", "mint", "sky", "navy", "rose", "light"}
    | {"multicolour", "multi-colour", "multi-color"}
)
GENDER_WORDS = {
    "Men": {"women", "womens", "women's", "ladies", "girls", "girl's", "kids", "boys"},
    "Women": {"men", "mens", "men's", "gents", "boys", "kids"},
    "Kids": {"men", "mens", "men's", "women", "womens", "women's", "ladies", "gents"},
}

# Well-known real brands the LLM must not reuse (brand names are checked case-insensitively).
REAL_BRANDS = {
    "bata", "liberty", "relaxo", "sparx", "paragon", "campus", "woodland", "red tape", "khadim",
    "metro", "mochi", "puma", "nike", "adidas", "reebok", "skechers", "asics", "fila", "crocs",
    "biba", "w", "aurelia", "fabindia", "manyavar", "peter england", "allen solly", "van heusen",
    "louis philippe", "raymond", "arrow", "levis", "levi's", "wrangler", "lee", "pepe", "spykar",
    "mufti", "roadster", "hrx", "jockey", "dollar", "lux", "rupa", "boat", "boAt", "noise",
    "boult", "mivi", "portronics", "ambrane", "zebronics", "realme", "mi", "xiaomi", "samsung",
    "oneplus", "apple", "sony", "jbl", "logitech", "hp", "dell", "lenovo", "anker", "syska",
    "prestige", "hawkins", "pigeon", "butterfly", "bajaj", "philips", "milton", "cello", "borosil",
    "tupperware", "wonderchef", "vinod", "havells", "usha", "morphy richards", "kent", "steelbird",
    "studds", "vega", "bosch", "3m", "michelin", "amaron", "exide", "castrol", "aashirvaad",
    "pillsbury", "fortune", "saffola", "india gate", "daawat", "kohinoor", "tata", "tata sampann",
    "mdh", "everest", "catch", "patanjali", "amul", "dabur", "brooke bond", "red label", "taj mahal",
    "society", "wagh bakri", "nescafe", "bru", "dhara", "gemini", "emami", "24 mantra", "organic tattva",
    "himalaya", "bharat", "zara", "h&m", "uniqlo", "decathlon", "amazon basics", "amazonbasics", "flipkart", "myntra",
}


@dataclass
class Sub:
    path: str  # category path below the root
    price: tuple[int, int]
    colors: list[str] | None = None
    materials: list[str] | None = None
    sizes: list[str] | None = None  # ordered size ladder; products get a contiguous run
    gender: str | None = None
    attrs: dict[str, list[str]] = field(default_factory=dict)
    noun: str = ""  # what a shopper would call it, used in prompts


@dataclass
class Cat:
    key: str
    root: str
    subs: list[Sub]


MEN_SHOE = [f"UK {n}" for n in range(6, 12)]
WOMEN_SHOE = [f"UK {n}" for n in range(3, 9)]
KID_SHOE = ["UK 10C", "UK 11C", "UK 12C", "UK 13C", "UK 1", "UK 2", "UK 3", "UK 4"]
APPAREL = ["XS", "S", "M", "L", "XL", "XXL", "3XL"]
KIDS_APPAREL = ["2-3Y", "3-4Y", "4-5Y", "5-6Y", "6-7Y", "8-9Y", "10-11Y"]
NEUTRAL = ["Black", "White", "Grey", "Navy Blue", "Blue", "Red", "Brown", "Beige", "Olive", "Green"]

TAXONOMY = [
    Cat("footwear", "Footwear", [
        Sub("Men > Running Shoes", (499, 3999), ["Black", "Grey", "Navy Blue", "White", "Red", "Blue", "Olive"],
            ["Mesh", "Knit", "Synthetic"], MEN_SHOE, "Men", {"closure": ["Lace-Up", "Slip-On"]}, "running shoes"),
        Sub("Men > Casual Sneakers", (599, 2999), ["White", "Black", "Grey", "Navy Blue", "Beige", "Tan"],
            ["Canvas", "Synthetic Leather", "Suede"], MEN_SHOE, "Men", {"closure": ["Lace-Up", "Slip-On"]},
            "sneakers"),
        Sub("Men > Formal Shoes", (799, 3499), ["Black", "Brown", "Tan", "Wine"],
            ["Genuine Leather", "Synthetic Leather", "Patent Leather"], MEN_SHOE, "Men",
            {"closure": ["Lace-Up", "Slip-On", "Buckle"]}, "formal shoes"),
        Sub("Men > Sandals & Floaters", (299, 1499), ["Black", "Brown", "Tan", "Navy Blue", "Olive", "Grey"],
            ["Synthetic", "Genuine Leather", "Rubber"], MEN_SHOE, "Men", {"closure": ["Velcro", "Buckle"]},
            "sandals"),
        Sub("Men > Flip Flops & Slippers", (149, 699), ["Black", "Navy Blue", "Grey", "Blue", "Red", "Olive"],
            ["Rubber", "EVA"], MEN_SHOE, "Men", {}, "slippers"),
        Sub("Women > Heels", (499, 2499), ["Black", "Beige", "Gold", "Silver", "Pink", "Red", "Peach"],
            ["Synthetic", "Synthetic Leather", "Suede"], WOMEN_SHOE, "Women",
            {"heel_type": ["Block Heel", "Stiletto", "Wedge", "Kitten Heel"]}, "heels"),
        Sub("Women > Flats & Bellies", (299, 1299), ["Black", "Beige", "Pink", "Gold", "Tan", "White", "Peach"],
            ["Synthetic", "Synthetic Leather", "Fabric"], WOMEN_SHOE, "Women", {}, "bellies"),
        Sub("Women > Sneakers", (599, 2999), ["White", "Pink", "Black", "Grey", "Beige", "Peach"],
            ["Canvas", "Mesh", "Synthetic Leather"], WOMEN_SHOE, "Women", {"closure": ["Lace-Up", "Slip-On"]},
            "sneakers"),
        Sub("Women > Kolhapuri Chappals", (249, 999), ["Tan", "Brown", "Gold", "Black", "Maroon"],
            ["Genuine Leather", "Synthetic Leather"], WOMEN_SHOE, "Women", {}, "kolhapuri chappals"),
        Sub("Kids > School Shoes", (299, 999), ["Black", "White"], ["Synthetic Leather", "Canvas"], KID_SHOE,
            "Kids", {"closure": ["Velcro", "Lace-Up"]}, "school shoes"),
    ]),
    Cat("apparel", "Apparel", [
        Sub("Men > T-Shirts", (199, 999), NEUTRAL + ["Maroon", "Mustard", "Yellow", "Teal"],
            ["Cotton", "Polyester", "Cotton Blend"], APPAREL, "Men",
            {"fit": ["Regular Fit", "Slim Fit", "Oversized"], "sleeve": ["Half Sleeve", "Full Sleeve"],
             "pattern": ["Solid", "Printed", "Striped"]}, "t-shirt"),
        Sub("Men > Shirts", (399, 1999), ["White", "Sky Blue", "Blue", "Navy Blue", "Black", "Pink", "Grey", "Olive"],
            ["Cotton", "Linen", "Cotton Blend"], APPAREL, "Men",
            {"fit": ["Regular Fit", "Slim Fit"], "sleeve": ["Full Sleeve", "Half Sleeve"],
             "pattern": ["Solid", "Checked", "Striped", "Printed"]}, "shirt"),
        Sub("Men > Jeans", (599, 2499), ["Blue", "Navy Blue", "Black", "Grey"], ["Denim"],
            ["28", "30", "32", "34", "36", "38"], "Men", {"fit": ["Slim Fit", "Regular Fit", "Skinny Fit"]}, "jeans"),
        Sub("Men > Kurtas", (399, 1999), ["White", "Cream", "Maroon", "Navy Blue", "Mustard", "Beige", "Green"],
            ["Cotton", "Silk Blend", "Linen"], APPAREL, "Men", {"pattern": ["Solid", "Printed", "Embroidered"]},
            "kurta"),
        Sub("Men > Track Pants", (299, 1199), ["Black", "Navy Blue", "Grey", "Olive"], ["Polyester", "Cotton Blend"],
            APPAREL, "Men", {"fit": ["Regular Fit", "Slim Fit"]}, "track pants"),
        Sub("Women > Kurtis", (299, 1999), ["Pink", "Yellow", "Blue", "Green", "Maroon", "White", "Peach", "Mustard"],
            ["Rayon", "Cotton", "Georgette"], APPAREL, "Women",
            {"pattern": ["Printed", "Solid", "Embroidered"], "sleeve": ["3/4 Sleeve", "Full Sleeve", "Sleeveless"]},
            "kurti"),
        Sub("Women > Sarees", (499, 4999), ["Red", "Maroon", "Pink", "Green", "Blue", "Yellow", "Wine", "Purple"],
            ["Georgette", "Silk", "Cotton", "Chiffon"], ["Free Size"], "Women",
            {"pattern": ["Printed", "Woven", "Embroidered"]}, "saree"),
        Sub("Women > Tops", (249, 1199), ["Black", "White", "Pink", "Yellow", "Blue", "Green", "Peach"],
            ["Cotton", "Rayon", "Polyester"], APPAREL, "Women",
            {"pattern": ["Solid", "Printed", "Striped"], "sleeve": ["Half Sleeve", "Sleeveless", "Full Sleeve"]},
            "top"),
        Sub("Women > Leggings", (199, 699), ["Black", "White", "Navy Blue", "Maroon", "Beige", "Grey"],
            ["Cotton Lycra"], APPAREL, "Women", {}, "leggings"),
        Sub("Kids > T-Shirts", (149, 599), ["Red", "Blue", "Yellow", "Green", "White", "Navy Blue", "Pink"],
            ["Cotton"], KIDS_APPAREL, "Kids", {"pattern": ["Printed", "Solid"]}, "kids t-shirt"),
    ]),
    Cat("electronics", "Electronics Accessories", [
        Sub("Mobile Accessories > Chargers", (299, 1999), ["White", "Black"], None, None, None,
            {"wattage": ["10W", "18W", "20W", "25W", "33W", "45W", "65W"], "connector": ["USB-C", "Micro USB", "Lightning"]},
            "mobile charger"),
        Sub("Mobile Accessories > Cables", (149, 799), ["White", "Black", "Grey", "Red"], ["Braided Nylon", "PVC"], None,
            None, {"connector": ["USB-C", "Micro USB", "Lightning", "USB-C to USB-C"], "length": ["1m", "1.5m", "2m"]},
            "charging cable"),
        Sub("Mobile Accessories > Power Banks", (699, 2999), ["Black", "White", "Blue", "Grey"], None, None, None,
            {"capacity": ["10000mAh", "20000mAh", "5000mAh"], "wattage": ["10W", "18W", "22.5W"]}, "power bank"),
        Sub("Mobile Accessories > Phone Cases & Covers", (149, 699), ["Black", "Transparent", "Blue", "Red", "Pink", "Green"],
            ["Silicone", "TPU", "Leather"], None, None, {}, "phone cover"),
        Sub("Audio > Wired Earphones", (199, 999), ["Black", "White", "Blue", "Red"], None, None, None,
            {"connector": ["3.5mm", "USB-C"]}, "earphones"),
        Sub("Audio > Bluetooth Earbuds", (699, 3999), ["Black", "White", "Blue", "Grey", "Green"], None, None, None,
            {"playback": ["24 hours", "40 hours", "50 hours"]}, "earbuds"),
        Sub("Audio > Neckbands", (499, 1999), ["Black", "Blue", "Red", "Grey"], None, None, None,
            {"playback": ["20 hours", "30 hours", "40 hours"]}, "neckband"),
        Sub("Computer Accessories > Mouse", (249, 1499), ["Black", "White", "Grey", "Blue"], None, None, None,
            {"connectivity": ["Wired", "Wireless", "Bluetooth"]}, "mouse"),
        Sub("Computer Accessories > Keyboards", (399, 2499), ["Black", "White", "Grey"], None, None, None,
            {"connectivity": ["Wired", "Wireless", "Bluetooth"]}, "keyboard"),
        Sub("Computer Accessories > Laptop Bags", (499, 2499), ["Black", "Grey", "Navy Blue", "Brown"],
            ["Polyester", "Nylon", "Synthetic Leather"], None, None, {"fits_laptop": ["14 inch", "15.6 inch", "17 inch"]},
            "laptop bag"),
    ]),
    Cat("kitchen", "Home & Kitchen", [
        Sub("Cookware > Pressure Cookers", (899, 3499), ["Silver", "Black"], ["Aluminium", "Stainless Steel", "Hard Anodised"],
            None, None, {"capacity": ["2 L", "3 L", "5 L", "7.5 L"]}, "pressure cooker"),
        Sub("Cookware > Tawa", (399, 1499), ["Black"], ["Cast Iron", "Non-Stick", "Iron"], None, None,
            {"diameter": ["24 cm", "26 cm", "28 cm"]}, "tawa"),
        Sub("Cookware > Kadai", (499, 1999), ["Black", "Silver", "Copper"], ["Cast Iron", "Non-Stick", "Stainless Steel", "Iron"],
            None, None, {"capacity": ["1.5 L", "2.5 L", "3.5 L"]}, "kadai"),
        Sub("Kitchen Tools > Knives", (149, 999), ["Black", "Silver", "Red", "Green"], ["Stainless Steel"], None, None,
            {"pack_of": ["1", "3", "5"]}, "kitchen knife"),
        Sub("Kitchen Tools > Vegetable Choppers", (199, 799), ["Green", "Red", "White", "Transparent"], ["Plastic"], None,
            None, {"capacity": ["500 ml", "750 ml", "900 ml"]}, "vegetable chopper"),
        Sub("Storage & Containers > Container Sets", (299, 1499), ["Transparent", "Green", "Blue", "Silver"],
            ["Plastic", "Glass", "Stainless Steel"], None, None, {"pack_of": ["3", "6", "12", "18"]},
            "kitchen containers"),
        Sub("Storage & Containers > Water Bottles", (199, 899), ["Silver", "Black", "Blue", "Copper", "Pink", "Green"],
            ["Stainless Steel", "Copper", "Plastic"], None, None, {"capacity": ["500 ml", "750 ml", "1 L", "1.5 L"]},
            "water bottle"),
        Sub("Appliances > Electric Kettles", (599, 1999), ["Silver", "Black", "White"], ["Stainless Steel", "Plastic"],
            None, None, {"capacity": ["1 L", "1.5 L", "1.8 L"], "wattage": ["1200W", "1500W"]}, "electric kettle"),
        Sub("Dinnerware > Dinner Sets", (999, 3999), ["White", "Silver", "Multicolor"], ["Melamine", "Stainless Steel", "Ceramic"],
            None, None, {"pieces": ["18", "24", "32", "40"]}, "dinner set"),
        Sub("Home Storage > Cloth Organisers", (199, 999), ["Grey", "Beige", "Blue", "Pink", "Brown", "Maroon"],
            ["Non-Woven", "Polyester", "Canvas"], None, None, {"pack_of": ["1", "2", "3", "4"]},
            "clothes storage organiser bag"),
    ]),
    Cat("auto", "Auto Accessories", [
        Sub("Car > Seat Covers", (1499, 5999), ["Black", "Beige", "Tan", "Grey", "Red"], ["Leatherette", "Fabric", "Velvet"],
            None, None, {"vehicle_type": ["Car"], "fit": ["Universal Fit", "Custom Fit"]}, "car seat cover"),
        Sub("Car > Phone Holders", (199, 999), ["Black", "Grey", "Silver"], ["Plastic", "Aluminium"], None, None,
            {"vehicle_type": ["Car"], "mount": ["Dashboard", "Air Vent", "Windshield"]}, "car mobile holder"),
        Sub("Car > Car Chargers", (199, 899), ["Black", "Silver"], None, None, None,
            {"vehicle_type": ["Car"], "wattage": ["18W", "24W", "36W", "45W"], "connector": ["USB-C", "Dual USB"]},
            "car charger"),
        Sub("Car > Microfiber Cloths", (149, 499), ["Blue", "Grey", "Yellow", "Green"], ["Microfiber"], None, None,
            {"vehicle_type": ["Car", "Bike"], "pack_of": ["2", "3", "4", "6"]}, "microfiber cleaning cloth"),
        Sub("Car > Car Perfumes", (149, 599), ["Blue", "Black", "Transparent"], None, None, None,
            {"vehicle_type": ["Car"], "fragrance": ["Lavender", "Lemon", "Ocean", "Jasmine", "Rose"]}, "car perfume"),
        Sub("Car > Tyre Inflators", (1499, 3499), ["Black", "Grey"], None, None, None,
            {"vehicle_type": ["Car", "Bike"], "wattage": ["120W", "150W"]}, "tyre inflator"),
        Sub("Car > Dash Cameras", (1999, 5999), ["Black"], None, None, None,
            {"vehicle_type": ["Car"], "resolution": ["1080p", "2K", "4K"]}, "dash cam"),
        Sub("Bike > Helmets", (699, 2999), ["Black", "White", "Red", "Grey", "Blue", "Yellow"],
            ["ABS Plastic", "Polycarbonate", "Fibreglass"], ["M", "L", "XL"], None,
            {"vehicle_type": ["Bike"], "helmet_type": ["Full Face", "Open Face", "Half Face"]}, "helmet"),
        Sub("Bike > Bike Covers", (299, 899), ["Black", "Grey", "Silver", "Blue", "Maroon"], ["Polyester", "Nylon"],
            None, None, {"vehicle_type": ["Bike"], "fit": ["Universal Fit"]}, "bike body cover"),
        Sub("Bike > Riding Gloves", (299, 1299), ["Black", "Grey", "Red"], ["Synthetic Leather", "Mesh", "Genuine Leather"],
            ["M", "L", "XL"], None, {"vehicle_type": ["Bike"]}, "riding gloves"),
    ]),
    Cat("grocery", "Grocery Staples", [
        Sub("Atta & Flours > Whole Wheat Atta", (199, 549), None, None, None, None,
            {"weight": ["1 kg", "5 kg", "10 kg"], "diet": ["Veg"]}, "atta"),
        Sub("Atta & Flours > Besan", (69, 249), None, None, None, None, {"weight": ["500 g", "1 kg"], "diet": ["Veg"]},
            "besan"),
        Sub("Rice > Basmati Rice", (149, 1299), None, None, None, None,
            {"weight": ["1 kg", "5 kg", "10 kg"], "diet": ["Veg"], "grain": ["Long Grain", "Extra Long Grain"]},
            "basmati rice"),
        Sub("Dals & Pulses > Toor Dal", (119, 499), None, None, None, None,
            {"weight": ["500 g", "1 kg", "2 kg"], "diet": ["Veg"]}, "toor dal"),
        Sub("Dals & Pulses > Moong Dal", (109, 449), None, None, None, None,
            {"weight": ["500 g", "1 kg", "2 kg"], "diet": ["Veg"]}, "moong dal"),
        Sub("Edible Oils > Mustard Oil", (159, 899), None, None, None, None,
            {"volume": ["1 L", "2 L", "5 L"], "diet": ["Veg"], "process": ["Kachi Ghani", "Cold Pressed", "Refined"]},
            "mustard oil"),
        Sub("Edible Oils > Sunflower Oil", (149, 849), None, None, None, None,
            {"volume": ["1 L", "2 L", "5 L"], "diet": ["Veg"], "process": ["Refined", "Cold Pressed"]}, "sunflower oil"),
        Sub("Spices & Masalas > Turmeric Powder", (49, 199), None, None, None, None,
            {"weight": ["100 g", "200 g", "500 g"], "diet": ["Veg"]}, "haldi powder"),
        Sub("Spices & Masalas > Garam Masala", (49, 249), None, None, None, None,
            {"weight": ["50 g", "100 g", "200 g"], "diet": ["Veg"]}, "garam masala"),
        Sub("Tea & Coffee > Tea", (99, 599), None, None, None, None,
            {"weight": ["250 g", "500 g", "1 kg"], "diet": ["Veg"], "tea_type": ["CTC", "Leaf", "Green Tea", "Masala Chai"]},
            "chai patti"),
        Sub("Ghee & Butter > Ghee", (299, 1299), None, None, None, None,
            {"volume": ["500 ml", "1 L"], "diet": ["Veg"], "source": ["Cow", "Buffalo"]}, "desi ghee"),
    ]),
]

CAT_CODES = {"footwear": "FW", "apparel": "AP", "electronics": "EL", "kitchen": "HK", "auto": "AU", "grocery": "GR"}


def charm_price(lo: int, hi: int, rng: random.Random) -> int:
    """Indian marketplace prices: 199, 249, 499, 1299, ..."""
    raw = rng.uniform(lo, hi)
    step = 50 if raw < 1000 else 100
    p = int(raw // step) * step + step - 1
    return max(lo, min(hi, p))


def build_specs(n_total: int, seed: int) -> list[dict]:
    rng = random.Random(seed)
    per_cat = n_total // len(TAXONOMY)
    specs = []
    for cat in TAXONOMY:
        for i in range(per_cat):
            sub = cat.subs[i % len(cat.subs)]
            pid = f"{CAT_CODES[cat.key]}-{i + 1:05d}"
            price = charm_price(*sub.price, rng)
            discount = rng.choice([0, 0, 10, 20, 25, 30, 40, 50, 60, 70])
            mrp = price if discount == 0 else int(round(price / (1 - discount / 100) / 10) * 10 - 1)
            spec: dict = {
                "id": pid,
                "_cat": cat.key,
                "_noun": sub.noun,
                "category": f"{cat.root} > {sub.path}",
                "price": price,
                "mrp": max(mrp, price),
                "currency": "INR",
            }
            if sub.gender:
                spec["gender"] = sub.gender
            if sub.colors:
                spec["color"] = rng.choice(sub.colors)
            if sub.materials:
                spec["material"] = rng.choice(sub.materials)
            if sub.sizes:
                if len(sub.sizes) == 1:
                    spec["size"] = list(sub.sizes)
                else:
                    a = rng.randrange(0, max(1, len(sub.sizes) - 2))
                    b = rng.randrange(a + 2, len(sub.sizes) + 1)
                    spec["size"] = sub.sizes[a:b]
            for k, opts in sub.attrs.items():
                spec[k] = rng.choice(opts)
            # Ratings are missing for some listings, like on real marketplaces.
            if rng.random() < 0.85:
                spec["rating"] = round(min(5.0, max(2.5, rng.gauss(4.0, 0.4))), 1)
                spec["rating_count"] = int(rng.lognormvariate(5, 1.6))
            spec["in_stock"] = rng.random() < 0.9
            specs.append(spec)
    return specs


SYSTEM = (
    "You write product listings for a busy Indian online marketplace. You are precise about the "
    "attributes you are given and never invent attributes that contradict them. Always reply with JSON."
)

BRAND_PROMPT = """Invent {n} fictional brand names for an Indian online seller of {what}.
They should sound like real Indian D2C / marketplace brands (mix of Hindi/Sanskrit-inspired and
English-sounding names, e.g. styles like "Urbanveer", "Kraftika", "Desi Nest"), but must NOT be
real existing brands. One to two words each.
Reply as JSON: {{"brands": ["...", "..."]}}"""

LISTING_PROMPT = """Write marketplace listings for these {n} products. For each, write:
- "title": a messy, keyword-stuffed marketplace title like real Indian e-commerce listings
  (8-25 words). Start with the brand most of the time. Use separators like | , - ( ) and things like
  "for Men", "Pack of 2", size or capacity info. Vary style between items: some Title Case,
  some with a WORD IN CAPS, some with repeated synonyms. Include the colour if one is given.
  Style examples (different products, do not copy):
    "Urbanveer Men's Sports Running Shoes | Lightweight Walking Shoes for Mens Gym Jogging (Black, UK 8)"
    "KRAFTIKA Women Rayon Printed Straight Kurti Kurta for Women - Pink - XL"
    "Desi Nest Stainless Steel Water Bottle 1 Litre for Office School Gym, Fridge Bottle, Silver, Pack of 1"
- "description": 1-3 sentences (20-50 words) in Indian English: what it is, material/feature,
  and a typical use (office, gym, daily cooking, festive wear, long rides...).

Hard rules: use exactly the given brand; mention no other brand; never mention a colour other than the
given one; never contradict gender, material, size or capacity; no prices in the text.

Products:
{items}

Reply as JSON: {{"items": [{{"i": 0, "title": "...", "description": "..."}}, ...]}} with one entry per product, same order."""


def _spec_for_prompt(i: int, s: dict) -> dict:
    out = {"i": i, "product": s["_noun"], "brand": s["brand"], "category": s["category"]}
    for k in ("gender", "color", "material", "size"):
        if k in s:
            out[k] = s[k]
    for k, v in s.items():
        if k.startswith("_") or k in out or k in {"id", "price", "mrp", "currency", "rating", "rating_count",
                                                  "in_stock", "category"}:
            continue
        out[k] = v
    return out


WORD = re.compile(r"[a-z0-9']+")


def validate(spec: dict, title: str, desc: str) -> str | None:
    if not isinstance(title, str) or not (15 <= len(title) <= 220):
        return "title length"
    if not isinstance(desc, str) or not (30 <= len(desc) <= 600):
        return "description length"
    text = f"{title} {desc}".lower()
    words = set(WORD.findall(text))
    own_color = {w.lower() for w in spec.get("color", "").split()}
    if spec.get("color") == "Multicolor":
        own_color |= {"multicolour", "multi-colour", "multi-color"}
    allowed = own_color | {w.lower() for w in spec.get("material", "").split()}
    # 'gold'/'silver'/'copper' may legitimately describe material/finish; only check pure colours.
    for w in COLOR_WORDS:
        if w in words and w not in allowed and w not in {"gold", "silver", "copper", "rose", "wine", "tan", "orange"}:
            return f"foreign colour {w!r}"
    g = spec.get("gender")
    if g and words & GENDER_WORDS[g]:
        return f"gender conflict {sorted(words & GENDER_WORDS[g])}"
    for b in REAL_BRANDS:
        if re.search(rf"\b{re.escape(b)}\b", text) and b.lower() not in spec["brand"].lower():
            return f"real brand {b!r}"
    return None


def fallback_listing(spec: dict, rng: random.Random) -> tuple[str, str]:
    bits = [spec["brand"]]
    if spec.get("gender"):
        bits.append(f"{spec['gender']}'s")
    if spec.get("color"):
        bits.append(spec["color"])
    if spec.get("material"):
        bits.append(spec["material"])
    bits.append(spec["_noun"].title())
    extra = [str(spec[k]) for k in ("capacity", "weight", "volume", "wattage", "pack_of") if k in spec]
    title = " ".join(bits) + (" | " + " ".join(extra) if extra else "")
    desc = f"{spec['brand']} {spec['_noun']} from our {spec['category'].split(' > ')[-1]} range. " \
           f"Good quality, value for money and built for everyday use."
    return title, desc


async def ask_json(llm, prompt: str, temperature: float, retries: int = 3) -> dict:
    last = None
    for attempt in range(retries):
        try:
            raw = await llm.complete(prompt, system=SYSTEM, temperature=temperature, max_tokens=3000, json_mode=True)
            data = parse_json(raw)
            if isinstance(data, dict):
                return data
            last = LLMError("not an object")
        except LLMError as e:
            last = e
        await asyncio.sleep(1 + attempt)
    raise LLMError(f"giving up after {retries} attempts: {last}")


async def gen_brands(llm, specs: list[dict], seed: int) -> dict[str, list[str]]:
    path = CACHE / "brands.json"
    if path.exists():
        return json.loads(path.read_text())
    whats = {
        "footwear": "shoes, sandals and chappals",
        "apparel": "clothing (t-shirts, kurtas, kurtis, sarees, jeans)",
        "electronics": "mobile and computer accessories (chargers, earbuds, cables)",
        "kitchen": "kitchenware, cookware and home storage",
        "auto": "car and bike accessories",
        "grocery": "packaged grocery staples (atta, dal, rice, spices, oil)",
    }
    brands: dict[str, list[str]] = {}
    seen: set[str] = set()
    for cat in TAXONOMY:
        got: list[str] = []
        for _ in range(4):
            data = await ask_json(llm, BRAND_PROMPT.format(n=16, what=whats[cat.key]), temperature=1.0)
            for b in data.get("brands", []):
                b = str(b).strip().strip(".")
                key = b.lower()
                if not b or len(b) > 24 or key in seen or key in REAL_BRANDS or any(
                    re.search(rf"\b{re.escape(r)}\b", key) for r in REAL_BRANDS if len(r) > 3
                ):
                    continue
                seen.add(key)
                got.append(b)
            if len(got) >= 12:
                break
        brands[cat.key] = got[:12]
        print(f"  brands[{cat.key}] = {brands[cat.key]}", file=sys.stderr)
    CACHE.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(brands, indent=2))
    return brands


async def gen_batch(llm, idx: int, batch: list[dict], sem: asyncio.Semaphore, stats: dict) -> None:
    path = CACHE / "batches" / f"{idx:05d}.json"
    if path.exists():
        return
    async with sem:
        rng = random.Random(idx)
        pending = list(range(len(batch)))
        results: dict[int, dict] = {}
        for attempt in range(3):
            items = json.dumps([_spec_for_prompt(j, batch[i]) for j, i in enumerate(pending)], ensure_ascii=False,
                               indent=1)
            try:
                data = await ask_json(llm, LISTING_PROMPT.format(n=len(pending), items=items),
                                      temperature=0.8 + 0.1 * attempt)
            except LLMError as e:
                print(f"  batch {idx}: {e}", file=sys.stderr)
                continue
            out = data.get("items") or []
            still = []
            for j, i in enumerate(pending):
                entry = next((o for o in out if isinstance(o, dict) and o.get("i") == j), None)
                if entry is None and j < len(out) and isinstance(out[j], dict):
                    entry = out[j]
                title = (entry or {}).get("title")
                desc = (entry or {}).get("description")
                err = validate(batch[i], title, desc) if entry else "missing"
                if err:
                    stats["rejected"] += 1
                    still.append(i)
                else:
                    results[i] = {"title": title.strip(), "description": desc.strip(), "source": "llm"}
            pending = still
            if not pending:
                break
        for i in pending:
            t, d = fallback_listing(batch[i], rng)
            results[i] = {"title": t, "description": d, "source": "fallback"}
            stats["fallback"] += 1
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"ids": [s["id"] for s in batch], "listings": [results[i] for i in range(len(batch))]},
                                   ensure_ascii=False))
        stats["done"] += 1
        if stats["done"] % 10 == 0:
            el = time.time() - stats["t0"]
            print(f"  {stats['done']}/{stats['todo']} batches, {el:.0f}s, rejected={stats['rejected']} "
                  f"fallback={stats['fallback']}", file=sys.stderr)


def assign_brands(specs: list[dict], brands: dict[str, list[str]], seed: int) -> None:
    rng = random.Random(seed + 1)
    for s in specs:
        pool = brands[s["_cat"]]
        # Zipf-ish: a few brands dominate, like real marketplaces.
        weights = [1 / (r + 1) ** 0.8 for r in range(len(pool))]
        s["brand"] = rng.choices(pool, weights)[0]


def finalize(spec: dict, listing: dict, rng: random.Random) -> dict:
    slug = re.sub(r"[^a-z0-9]+", "-", listing["title"].lower()).strip("-")[:60]
    doc = {"id": spec["id"], "title": listing["title"], "description": listing["description"], "brand": spec["brand"]}
    for k, v in spec.items():
        if k.startswith("_") or k in doc:
            continue
        doc[k] = v
    # Marketplace messiness: some MRPs arrive as formatted strings.
    if rng.random() < 0.15:
        doc["mrp"] = f"₹{doc['mrp']:,}"
    doc["image_url"] = f"https://images.example.com/demo/{spec['id'].lower()}.jpg"
    doc["url"] = f"https://shop.example.com/p/{slug}-{spec['id'].lower()}"
    return doc


def assemble(specs: list[dict], seed: int) -> list[dict]:
    rng = random.Random(seed + 2)
    listings = {}
    for p in sorted((CACHE / "batches").glob("*.json")):
        data = json.loads(p.read_text())
        listings.update(zip(data["ids"], data["listings"], strict=True))
    docs = []
    for s in specs:
        if s["id"] in listings:
            docs.append(finalize(s, listings[s["id"]], rng))
    return docs


def write_outputs(docs: list[dict]) -> None:
    DATA.mkdir(exist_ok=True)
    with open(DATA / "demo_catalog.jsonl", "w") as f:
        for d in docs:
            f.write(json.dumps(d, ensure_ascii=False) + "\n")
    cols: list[str] = []
    for d in docs:
        for k in d:
            if k not in cols:
                cols.append(k)
    with open(DATA / "demo_catalog.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for d in docs:
            w.writerow({k: (";".join(v) if isinstance(v, list) else v) for k, v in d.items()})
    n_llm = sum(1 for d in docs)
    digest = hashlib.sha256((DATA / "demo_catalog.jsonl").read_bytes()).hexdigest()[:12]
    print(f"wrote {n_llm} docs to data/demo_catalog.jsonl (+ .csv), sha256 {digest}", file=sys.stderr)


async def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--n", type=int, default=3000)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--batch-size", type=int, default=8)
    ap.add_argument("--concurrency", type=int, default=4)
    ap.add_argument("--provider", default=None, help="ollama | anthropic (default from ZERCH_LLM_PROVIDER)")
    ap.add_argument("--model", default=None)
    ap.add_argument("--limit-batches", type=int, default=None, help="only generate the first N batches (smoke test)")
    ap.add_argument("--assemble-only", action="store_true")
    args = ap.parse_args()

    specs = build_specs(args.n, args.seed)
    if not args.assemble_only:
        llm = get_llm(args.provider, args.model)
        print(f"generating {len(specs)} products with {llm.name}", file=sys.stderr)
        brands = await gen_brands(llm, specs, args.seed)
        assign_brands(specs, brands, args.seed)
        # Interleave categories so a partial run still covers everything.
        order = sorted(range(len(specs)), key=lambda i: (int(specs[i]["id"][3:]), specs[i]["id"]))
        ordered = [specs[i] for i in order]
        batches = [ordered[i : i + args.batch_size] for i in range(0, len(ordered), args.batch_size)]
        if args.limit_batches:
            batches = batches[: args.limit_batches]
        sem = asyncio.Semaphore(args.concurrency)
        todo = [i for i in range(len(batches)) if not (CACHE / "batches" / f"{i:05d}.json").exists()]
        stats = {"done": 0, "todo": len(todo), "rejected": 0, "fallback": 0, "t0": time.time()}
        await asyncio.gather(*(gen_batch(llm, i, batches[i], sem, stats) for i in todo))
        print(f"llm done: rejected={stats['rejected']} fallback={stats['fallback']}", file=sys.stderr)
    else:
        brands = json.loads((CACHE / "brands.json").read_text())
        assign_brands(specs, brands, args.seed)
    write_outputs(assemble(specs, args.seed))


if __name__ == "__main__":
    asyncio.run(main())
