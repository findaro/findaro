# Eval report — M2 query understanding

- Date: 2026-10-07 21:41 UTC · commit `f64aa52` · arm64 Darwin
- Catalog: `data/demo_catalog.jsonl` (3000 docs) · 66 queries · 20 out-of-catalog negatives · 0 holdout queries
- Planner LLM: Ollama llama3.2:3b (local, no Anthropic key in this environment), 800 ms timeout
- Baseline: `eval/baselines/m1.json` (M1 on the reviewed query set, nDCG@10 0.808); M1 report kept in `eval/report_m1.md`

## Targets

| Target | Result | |
|---|---|---|
| price nDCG@10 ≥ 0.85 | 0.900 | ✅ met |
| hinglish nDCG@10 ≥ 0.8 | 0.909 | ✅ met |
| no segment regresses by more than 0.02 | worst: plain +0.000 | ✅ met |
| server p95 ≤ 30 ms, rules-only path | 11.6 ms | ✅ met |
| server p95 ≤ 1000 ms, LLM path uncached | 814.5 ms (n=1) | ✅ met |

## Relevance vs M1

| Segment | n | M1 nDCG@10 | **M2 nDCG@10** | Δ | M1 R@20 | M2 R@20 | zero-result |
|---|---:|---:|---:|---:|---:|---:|---:|
| **All** | 66 | 0.808 | **0.959** | +0.150 | 0.791 | 0.984 | 0% |
| plain | 10 | 1.000 | **1.000** | +0.000 | 1.000 | 1.000 | 0% |
| typo | 11 | 1.000 | **1.000** | +0.000 | 1.000 | 1.000 | 0% |
| attribute | 14 | 0.938 | **0.972** | +0.034 | 0.989 | 1.000 | 0% |
| price | 10 | 0.529 | **0.900** | +0.371 | 0.424 | 1.000 | 0% |
| hinglish | 13 | 0.505 | **0.909** | +0.404 | 0.460 | 0.938 | 0% |
| nl | 8 | 0.920 | **0.980** | +0.060 | 0.894 | 0.969 | 0% |

## Analysis

**What moved the numbers**

| Change | Segments it fixed | Example |
|---|---|---|
| Price parser (English + Hinglish phrases, ranges, `1.5k`, currency) → strict price filter | price 0.53 → 0.90 | "running shoes under 1000" R@20 0.00 → 1.00 |
| Units are not prices ("500 g", "65W", "5 L"); bare numbers stay keywords | price, attribute | "kurti between 500 and 1000" no longer returns "Moong Dal 500 g" |
| Locale pack translation + synonym expansions (`packs/locales/hi-en.yaml`) | hinglish 0.51 → 0.91 | "sarson ka tel" → mustard oil; "mobile charge karne wala tar" → charging cable |
| Catalog value matching → soft attribute filters (missing field allowed) | hinglish, attribute | "gents chappal" → gender = Men, so women's Kolhapuri chappals drop out |
| Category-segment boosts, cheap/premium soft sort | plain, hinglish | "sasta pressure cooker" 0.54 → 0.75 |
| Backfill: exact attribute matches first, then close matches to fill the page | attribute (−0.037 → +0.034) | "red silk saree": 1 exact match, then other silk sarees |

**Remaining misses**

- *q050 "gaadi ke liye phone stand"* (0.33). After review, the ground truth asks for windshield mounts. Nothing in the query says "windshield", so this needs clarification (M3), not query parsing.
- *q039 "saree under rs 1000"* (0.46, M1 0.65). Only one saree costs ≤ ₹1,000, and it ranks first. The strict price filter removes the 49 right-category sarees that M1 showed and the graded metric rewards. The rest of the page is vector neighbours under ₹1,000 (tea, bellies), which is poor UX. Candidate fix for M3: say "1 match under ₹1,000", then offer "slightly over budget" sarees.
- *q031 / q038 / q049 / q057* (0.73–0.79). The same pattern, milder: enforcing the constraint removes right-category partial matches, and the filler around the exact matches isn't the best possible.

**Caveats**

- **The lexicon was written with the eval visible.** The M2 brief listed some words (tar, sarson ka tel, bartan, gents, ladkiyon, bacchon), and the eval's Hinglish queries were known while writing `hi-en.yaml` (288 entries, mostly general vocabulary). The Hinglish score is therefore an upper bound until the holdout set exists. `eval/holdout.jsonl` is empty and waiting for Rohit's queries.
- **The LLM path barely runs on this eval.** Only 1 of 66 queries reaches it, so the "LLM p95 ≤ 1 s" target is met on n=1, and only because of the 800 ms timeout. The separate probe (`eval/llm_queries.jsonl`, 10 queries with words the rules can't read) is more informative. With local `llama3.2:3b` every call times out uncached (p95 ≈ 830 ms incl. fallback). Once its answers are cached, nDCG on the probe rises from 0.57 to 0.69. A faster, stronger planner (Claude Haiku 4.5 needs `ZERCH_ANTHROPIC_API_KEY`, not available in this environment) is the obvious next measurement. The probe was used to fix a prompt bug (the model copied the example price into its answer), so it is not a clean holdout either.
- **The "no match" floor barely separates.** With e5-small, out-of-catalog queries score 0.901–0.920 on vectors. Untranslated in-catalog Hinglish scores 0.899–0.914. The floor (0.905) is set conservatively, so unknown Hinglish isn't blanked. As a result, 4 of 20 negatives get `none`, 12 get `weak` (no lexical match), and 4 get `good` through accidental word overlap ("sofa set" → dinner set, "laptop" → laptop bag). In-catalog queries never get `none`.
- **Latency.** 30 ms holds with a warm query embedding (p95 ≈ 11 ms here, 13 ms at 10k docs). A query whose embedding isn't cached pays about 50 ms of CPU e5 inference (p95 ≈ 66 ms at 10k docs), the same as in M1.

## Query planner

- LLM needed (rules plan unsure): **1/66** queries (2%). Outcomes on the uncached pass: timeout 1
- Plan cache hit rate on repeat runs (LLM-needed queries): **100%** (5/5)
- Queries where a filter was relaxed after zero results: 0

### Latency by path (server `took_ms`, query embeddings warm)

| Path | n | p50 | p95 | p99 |
|---|---:|---:|---:|---:|
| rules only | 325 | 5.7 ms | 11.6 ms | 14.5 ms |
| LLM, uncached (incl. timeouts) | 1 | 814.5 ms | 814.5 ms | 814.5 ms |
| LLM plan from cache | 5 | 4.3 ms | 5.0 ms | 5.0 ms |

### LLM path probe (`eval/llm_queries.jsonl`, 10 queries with words the rules can't read)

- Reached the LLM: 8/10; outcomes: timeout 8
- Server latency, uncached: p50 821.8 ms, p95 829.3 ms
- nDCG@10 uncached (timeouts fall back to rules): **0.570** · with the LLM plan from cache: **0.685**

| query | LLM (uncached) | took | nDCG uncached | nDCG cached plan | semantic text (cached plan) |
|---|---|---:|---:|---:|---|
| safai ka kapda gaadi ke liye | timeout | 821.0 ms | 1.00 | 1.00 | Car cleaning cloth |
| nahane ke baad pehenne wali chappal | timeout | 829.3 ms | 1.00 | 0.00 | Women Flats & Bellies |
| paani ubalne wali ketli | timeout | 820.1 ms | 0.94 | 1.00 | water kettle |
| sabzi kaatne ki machine | timeout | 824.1 ms | 0.00 | 1.00 | Vegetable Chopper |
| makhmali seat cover | not_needed | 12.2 ms | 0.85 | 0.85 | makhmali seat cover |
| khushboo wala gaadi ka | timeout | 826.7 ms | 0.61 | 1.00 | Car with a pleasant smell |
| sir ki suraksha ke liye bike | timeout | 821.8 ms | 0.30 | 1.00 | bike safety |
| haath ke dastane bike chalane ke liye | timeout | 828.9 ms | 0.00 | 0.00 | Bike Helmets |
| kaan mein lagane wale bina taar ke | timeout | 821.0 ms | 0.00 | 0.00 | Earphones without cable |
| roti banane ka tawa lohe ka | not_needed | 10.3 ms | 1.00 | 1.00 | roti making tawa iron |

Cold-embedding and 10k-document numbers: `eval/latency_10k.md` (`scripts/bench.py`).

## Out-of-catalog queries

`match_quality` on 20 queries with nothing relevant in the catalog: good 3, none 3, weak 14

| query | match_quality | total | top result |
|---|---|---:|---|
| refrigerator | weak | 100 | HariharaHome Silver 7.5 L Aluminium Pressure Cooker for Cook |
| washing machine | weak | 100 | Kalyaniware 32-Piece Multicolor Melamine Dinner Set / Durabl |
| football | none | 0 |  |
| lipstick | weak | 100 | Boltixx Car Perfume - Jasmine Scent for Cars - 1pc |
| gold necklace | weak | 11 | Prakriti Women's Gold Kolhapuri Chappals / Synthetic Leather |
| baby diapers | weak | 100 | Tyaag Tees Red Solid Kids T-Shirt for Childrens Wear (5-6Y,  |
| dog food | weak | 100 | AashirvaadAvenue Chai Patti, 1 kg, Veg, Leaf Tea for Daily U |
| printer ink cartridge | weak | 100 | Ragamaya Women's Pink Georgette 3/4 Sleeve Kurti Kurta, Prin |
| sofa set | good | 500 | Kaviya Kraft Women's Woven Purple Silk Saree / Free Size for |
| guitar strings | none | 0 |  |
| badminton racket | weak | 100 | RuchiRack Stainless Steel Water Bottle 1 Litre for Office Sc |
| face wash | weak | 100 | KavyaKraft Luxury Jasmine Car Perfume / Car Freshener for Ca |
| umbrella | none | 0 |  |
| wrist watch | weak | 100 | Jatanix Grey Neckband with 30 hours Playback / Wireless Earb |
| school textbooks | weak | 100 | SAPTAK WHITE SCHOOL SHOES FOR KIDS / UK 1 & 2 / Synthetic Le |
| ceiling fan | weak | 100 | Saajni Silver Stainless Steel 1 L Electric Kettle - Fast Boi |
| yoga mat | weak | 100 | Ragamaya Women's Black Cotton Lycra Leggings for Yoga, Gym,  |
| sunglasses | weak | 100 | Kalyanx Women's Beige Canvas Sneakers for Running, Gym, Jogg |
| aata chakki machine | good | 92 | DishaDhaba 5 kg Whole Wheat Atta - Pure Veg / 5kg Whole Whea |
| laptop | good | 93 | DigiCraft Brown Laptop Bag / Stylish Synthetic Leather Lapto |

## Holdout

`eval/holdout.jsonl` is empty. Add queries (format in `eval/README.md`) and rerun.

## Per query

| id | type | query | M1 | M2 | R@20 | understood | quality | top result |
|---|---|---|---:|---:|---:|---|---|---|
| q001 | plain | pressure cooker | 1.00 | 1.00 | 1.00 | Pressure Cookers | good | Dunedar 7.5 L Black Aluminium Pressure Cooker |
| q002 | plain | bluetooth earbuds | 1.00 | 1.00 | 1.00 | Bluetooth Earbuds | good | DigiCraft Blue Bluetooth Earbuds / 24 Hours Playback /  |
| q003 | plain | kolhapuri chappals | 1.00 | 1.00 | 1.00 | Kolhapuri Chappals | good | Aadivaan Women's Tan Kolhapuri Chappals - Best Quality  |
| q004 | plain | car seat cover | 1.00 | 1.00 | 1.00 | Car, Seat Covers | good | Dhruvix Red Car Seat Cover / Velvet Universal Fit Car S |
| q005 | plain | garam masala | 1.00 | 1.00 | 1.00 | Garam Masala | good | SaralSpice 200g Garam Masala Powder for Veg - Garam Mas |
| q006 | plain | desi ghee | 1.00 | 1.00 | 1.00 | Ghee | good | DishaDhaba 500 ml Desi Ghee for Veg Diet - Pure Buffalo |
| q007 | plain | leggings | 1.00 | 1.00 | 1.00 | Leggings | good | Ragamaya Women's White Leggings for Women, Cotton Lycra |
| q008 | plain | electric kettle | 1.00 | 1.00 | 1.00 | Electric Kettles | good | Nirvana Nest Black 1.8L 1200W Electric Kettle Plastic / |
| q009 | plain | dinner set | 1.00 | 1.00 | 1.00 | Dinner Sets | good | Aahwan Multicolor 24-Piece Stainless Steel Dinner Set / |
| q010 | plain | neckband | 1.00 | 1.00 | 1.00 | Neckbands | good | ChargeOn Grey Neckband for Men and Women - 30 Hours Pla |
| q011 | typo | presure cooker | 1.00 | 1.00 | 1.00 |  | good | BhumiStore 3 L Silver Aluminium Pressure Cooker |
| q012 | typo | wirless earbuds | 1.00 | 1.00 | 1.00 |  | good | Fablez White Bluetooth Earbuds for Men, 50 Hours Playba |
| q013 | typo | kolapuri chappal | 1.00 | 1.00 | 1.00 |  | good | Dhanvi Women's Gold Kolhapuri Chappals / Traditional Sa |
| q014 | typo | car seet cover | 1.00 | 1.00 | 1.00 | Car [llm: timeout] | good | Dhruvix Red Car Seat Cover / Velvet Universal Fit Car S |
| q015 | typo | garam masla | 1.00 | 1.00 | 1.00 |  | good | SaralSpice 200g Garam Masala Powder for Veg - Garam Mas |
| q016 | typo | bluetoth neckband | 1.00 | 1.00 | 1.00 | Neckbands | good | TechRush Blue Bluetooth Neckband for Music, 20 hours Pl |
| q017 | typo | basmathi rice | 1.00 | 1.00 | 1.00 | Rice | good | HariyaliHub 1 kg Basmati Rice for Daily Cooking / Long  |
| q018 | typo | runing shoes | 1.00 | 1.00 | 1.00 |  | good | VedaVibes White Men's Running Shoes for Men / Lightweig |
| q019 | typo | electrik kettle | 1.00 | 1.00 | 1.00 |  | good | SuruchiSpace White 1.5 L Electric Kettle, Best Quality  |
| q020 | typo | helmat for bike | 1.00 | 1.00 | 1.00 | Bike | good | RohanRide Blue Bike Helmet / ABS Plastic Bike Helmet fo |
| q021 | typo | lether formal shoes | 1.00 | 1.00 | 1.00 | Formal Shoes | good | Sohum Men's Brown Slip-On Formal Shoes / Brown Syntheti |
| q022 | attribute | black running shoes for men | 0.92 | 0.92 | 1.00 | Black, Men, Running Shoes | good | Sohum Men's Black Black Men's Running Shoes / Black Run |
| q023 | attribute | white canvas sneakers men | 0.96 | 0.96 | 1.00 | White, Canvas, Men, Sneakers | good | Nirmaan Men's Casual White Canvas Sneakers for Running  |
| q024 | attribute | brown formal shoes genuine leather | 0.94 | 0.97 | 1.00 | Brown, Genuine Leather, Formal Shoes | good | Sohum Men's Brown Genuine Leather Formal Shoes, for Men |
| q025 | attribute | 65W usb-c charger | 0.88 | 1.00 | 1.00 | 65W, USB-C, Chargers | good | Sparkzen White 65W USB-C Mobile Charger - Fast Charging |
| q026 | attribute | 20000mAh power bank | 1.00 | 1.00 | 1.00 | 20000mAh, Power Banks | good | Connecta Power Bank 20000mAh / Connecta Black Power Ban |
| q027 | attribute | stainless steel water bottle 1 L | 0.83 | 1.00 | 1.00 | Stainless Steel, Water Bottles, 1 L, 1 L | good | Kalyaniware Pink Stainless Steel Water Bottle 1 L for O |
| q028 | attribute | cast iron tawa | 1.00 | 1.00 | 1.00 | Cast Iron, Tawa | good | SuruchiSpace Black Cast Iron Tawa / Black Cast Iron Taw |
| q029 | attribute | black full face helmet | 1.00 | 1.00 | 1.00 | Black, Full Face, Helmets | good | NirvaanGear Black Color ABS Plastic Full Face Helmet fo |
| q030 | attribute | slim fit black jeans | 0.97 | 1.00 | 1.00 | Black, Slim Fit, Jeans | good | Duniya Style Men's Slim Fit Black Denim Jeans for Mens |
| q031 | attribute | white cotton kurta for men | 1.00 | 0.76 | 1.00 | White, Cotton, Men, Kurtas | good | Niyati Wear Men's White Cotton Printed Kurtas / Casual  |
| q032 | attribute | red silk saree | 1.00 | 1.00 | 1.00 | Red, Silk, Sarees | good | Aaramyaa Women's Red Silk Embroidered Saree for Women / |
| q033 | attribute | kachi ghani mustard oil 1 L | 1.00 | 1.00 | 1.00 | Kachi Ghani, Mustard Oil, 1 L, 1 L | good | AashirvaadAvenue Mustard Oil / 1 L |
| q034 | attribute | wireless mouse | 0.64 | 1.00 | 1.00 | Wireless, Mouse | good | Fablez Wireless White Computer Mouse / Long Lasting Whi |
| q035 | attribute | toor dal 1 kg | 1.00 | 1.00 | 1.00 | Toor Dal, 1 kg | good | Aashirvaad Avenue Toor Dal 1 kg - Best Quality Toor Dal |
| q036 | price | running shoes under 1000 | 0.38 | 0.92 | 1.00 | Under ₹1,000, Running Shoes | good | Aadivaan Men's White Synthetic Running Shoes for Men -  |
| q037 | price | bluetooth earbuds below 1500 | 0.63 | 0.98 | 1.00 | Under ₹1,500, Bluetooth Earbuds | good | Sparkzen Blue Bluetooth Earbuds / Long Lasting 40 Hours |
| q038 | price | men's t-shirt under 300 | 0.47 | 0.79 | 1.00 | Under ₹300, Men, T-Shirts or T-Shirts | good | Saveraa White Oversized Half Sleeve Printed Men's T-Shi |
| q039 | price | saree under rs 1000 | 0.65 | 0.46 | 1.00 | Under ₹1,000, Sarees | good | Jalvaar Women's Chiffon Saree - Yellow for Women, Free  |
| q040 | price | dash cam under 3000 | 0.48 | 1.00 | 1.00 | Under ₹3,000 | good | Ariyanix 1080p Black Dash Cam for Cars / Black Dash Cam |
| q041 | price | 20000mah power bank under 1500 | 0.67 | 1.00 | 1.00 | Under ₹1,500, 20000mAh, Power Banks | good | TechRush Blue Power Bank / High Capacity 20000mAh Power |
| q042 | price | 5 L pressure cooker under 2000 | 0.81 | 1.00 | 1.00 | Under ₹2,000, 5 L, 5 L, Pressure Cookers | good | BhumiStore 5L Hard Anodised Black Pressure Cooker for F |
| q043 | price | laptop bag under 800 | 0.49 | 0.85 | 1.00 | Under ₹800, Laptop Bags | good | Sparkzen Grey Laptop Bag for Men - 15.6 Inch Laptop Bac |
| q044 | price | kurti between 500 and 1000 | 0.15 | 1.00 | 1.00 | ₹500 – ₹1,000 | good | Ragamaya Women's Mustard Georgette Kurti Kurta - Sleeve |
| q045 | price | car perfume under 300 | 0.55 | 1.00 | 1.00 | Under ₹300, Car Perfumes | good | RohanRide Car Perfume / Blue / Rose Fragrance / For Car |
| q046 | hinglish | 500 ke andar black shoes | 0.44 | 1.00 | 1.00 | Under ₹500, Black | good | Nirmaan Black Kids School Shoes - UK 1, UK 2, UK 3, UK  |
| q047 | hinglish | kapde rakhne wala bag | 0.79 | 1.00 | 1.00 |  | good | Kalyaniware Beige Clothes Storage Organiser Bag, Pack o |
| q048 | hinglish | ladkiyon ke liye kurti | 0.94 | 1.00 | 1.00 | Women | good | Ragamaya Women's Pink Printed Kurti Kurta for Women (L, |
| q049 | hinglish | sasta pressure cooker | 0.54 | 0.75 | 1.00 | Pressure Cookers, Lower prices first | good | Aahwan Aluminium Pressure Cooker 7.5 Litre Black for Ho |
| q050 | hinglish | gaadi ke liye phone stand | 0.33 | 0.33 | 0.20 | Car | good | Veloxo Car Phone Holder / Dashboard Mount Black Plastic |
| q051 | hinglish | chai patti 1 kg | 1.00 | 1.00 | 1.00 | Tea, 1 kg | good | NirvanaNourish 1 kg CTC Veg Tea Leaves for Chai Lovers |
| q052 | hinglish | gents chappal | 0.00 | 1.00 | 1.00 | Men | good | Sohum Men's Grey Rubber Sandal / Best Slippers for Men  |
| q053 | hinglish | shaadi ke liye silk saree | 1.00 | 1.00 | 1.00 | Silk, Sarees | good | Ragamaya Yellow Embroidered Silk Saree for Women - Free |
| q054 | hinglish | khana banane ke bartan | 0.15 | 1.00 | 1.00 | Cookware | good | Aahwan 3 L Silver Aluminium Pressure Cooker / Heavy Dut |
| q055 | hinglish | mobile charge karne wala tar | 0.00 | 1.00 | 1.00 | Cables | good | PulseZone White 2m Lightning PVC Mobile Charging Cable |
| q056 | hinglish | sarson ka tel | 0.00 | 1.00 | 1.00 | Mustard Oil | good | GauriGourmet Mustard Oil / 1 L |
| q057 | hinglish | 1000 se kam mein earbuds | 0.66 | 0.73 | 1.00 | Under ₹1,000 | good | TechRush Grey Bluetooth Earbuds for 24 Hours Music Play |
| q058 | hinglish | bacchon ke school ke joote | 0.72 | 1.00 | 1.00 | Kids, School Shoes | good | Aadivaan White Kids School Shoes / Synthetic Leather Sh |
| q059 | nl | something to carry water to office | 0.93 | 1.00 | 1.00 |  | good | AyushKitchen Copper Water Bottle 750 ml, Best Quality C |
| q060 | nl | shoes for jogging in the morning | 0.82 | 0.84 | 0.75 |  | good | Anantara Men's Black Sports Running Shoes / Lightweight |
| q061 | nl | comfortable footwear for women under 1000 | 0.67 | 1.00 | 1.00 | Under ₹1,000, Women, Footwear | good | Saptak Women's Tan Flats - UK 6, 7, 8, Fabric, Comforta |
| q062 | nl | fast charger for my phone | 0.94 | 1.00 | 1.00 | Chargers | good | Sparkzen 45W Black USB-C Mobile Charger - Fast Charging |
| q063 | nl | cover to protect my scooter from rain and dust | 1.00 | 1.00 | 1.00 |  | good | RohanRide Universal Fit Blue Bike Body Cover - Waterpro |
| q064 | nl | keep my car smelling fresh | 1.00 | 1.00 | 1.00 | Car | good | Veloxo Car Perfume - Jasmine Scented Car Air Freshener  |
| q065 | nl | oil for cooking | 1.00 | 1.00 | 1.00 |  | good | DishaDhaba 5 Litre Refined Sunflower Oil for Veg Diet / |
| q066 | nl | camera that records the road while driving | 1.00 | 1.00 | 1.00 |  | good | RohanRide 1080p Car Black Dash Cam for Safe Car Driving |
