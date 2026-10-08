# Eval report — M2 query understanding

- Date: 2026-10-08 08:04 UTC · commit `9e55d2c` · arm64 Darwin
- Catalog: `data/demo_catalog.jsonl` (3000 docs) · 66 queries · 20 out-of-catalog negatives · 20 holdout queries
- Planner LLM: Ollama llama3.2:3b (local), 800 ms timeout
- Baseline: `eval/baselines/m1.json` (M1 on the reviewed query set, nDCG@10 0.808); M1 report kept in `eval/report_m1.md`

## Targets

| Target | Result | |
|---|---|---|
| price nDCG@10 ≥ 0.85 | 0.954 | ✅ met |
| hinglish nDCG@10 ≥ 0.8 | 0.909 | ✅ met |
| no segment regresses by more than 0.02 | worst: plain +0.000 | ✅ met |
| server p95 ≤ 30 ms, rules-only path | 11.7 ms | ✅ met |
| server p95 ≤ 1000 ms, LLM path uncached | 816.1 ms (n=1) | ✅ met |

## Relevance vs M1

| Segment | n | M1 nDCG@10 | **M2 nDCG@10** | Δ | M1 R@20 | M2 R@20 | zero-result |
|---|---:|---:|---:|---:|---:|---:|---:|
| **All** | 66 | 0.808 | **0.967** | +0.159 | 0.791 | 0.978 | 0% |
| plain | 10 | 1.000 | **1.000** | +0.000 | 1.000 | 1.000 | 0% |
| typo | 11 | 1.000 | **1.000** | +0.000 | 1.000 | 1.000 | 0% |
| attribute | 14 | 0.938 | **0.975** | +0.037 | 0.989 | 1.000 | 0% |
| price | 10 | 0.529 | **0.954** | +0.425 | 0.424 | 1.000 | 0% |
| hinglish | 13 | 0.505 | **0.909** | +0.404 | 0.460 | 0.908 | 0% |
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

- **Holdout: the honest Hinglish number is 0.82, not 0.91.** The lexicon was written with the eval visible. To get an independent number, `eval/gen_holdout.py` had a different model (OpenAI gpt-5.5) write 20 Hinglish queries. It wrote them for targets sampled from the catalog and never saw `hi-en.yaml` or `queries.jsonl`. On that set:
  - M1 (understanding off): nDCG@10 0.540, R@20 0.466.
  - M2: nDCG@10 **0.818** (0.828 with cached planner answers), R@20 0.80.

  Understanding clearly generalises (+0.28), but the dev-set Hinglish score (0.909) overstates it by about 0.09. Holdout failures:
  - spellings the pack doesn't have ("ladko" vs "ladke"/"ladkon");
  - "tee" for t-shirt;
  - ambiguous targets ("kurti style top" → Tops; "running ke liye earphones" → Neckbands; "office ke liye black joota", whose target has no colour).

  Nothing was tuned on the holdout. Its queries are marked `needs_review`.
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
| rules only | 325 | 6.0 ms | 11.7 ms | 15.5 ms |
| LLM, uncached (incl. timeouts) | 1 | 816.1 ms | 816.1 ms | 816.1 ms |
| LLM plan from cache | 5 | 5.2 ms | 21.1 ms | 21.1 ms |

### LLM path probe (`eval/llm_queries.jsonl`, 10 queries with words the rules can't read)

- Reached the LLM: 8/10; outcomes: timeout 8
- Server latency, uncached: p50 827.4 ms, p95 831.7 ms
- nDCG@10 uncached (timeouts fall back to rules): **0.570** · with the LLM plan from cache: **0.686**

| query | LLM (uncached) | took | nDCG uncached | nDCG cached plan | semantic text (cached plan) |
|---|---|---:|---:|---:|---|
| safai ka kapda gaadi ke liye | timeout | 828.4 ms | 1.00 | 1.00 | Car cleaning cloth |
| nahane ke baad pehenne wali chappal | timeout | 827.4 ms | 1.00 | 0.00 | Women Flats & Bellies |
| paani ubalne wali ketli | timeout | 816.5 ms | 0.94 | 1.00 | water kettle |
| sabzi kaatne ki machine | timeout | 823.6 ms | 0.00 | 1.00 | Vegetable chopper |
| makhmali seat cover | not_needed | 12.6 ms | 0.86 | 0.86 | makhmali seat cover |
| khushboo wala gaadi ka | timeout | 831.7 ms | 0.61 | 1.00 | Car with fragrance smell |
| sir ki suraksha ke liye bike | timeout | 827.5 ms | 0.30 | 1.00 | bike safety |
| haath ke dastane bike chalane ke liye | timeout | 828.9 ms | 0.00 | 0.00 | bike helmets |
| kaan mein lagane wale bina taar ke | timeout | 815.6 ms | 0.00 | 0.00 | Earphones without cable |
| roti banane ka tawa lohe ka | not_needed | 11.2 ms | 1.00 | 1.00 | roti making tawa iron |

Cold-embedding and 10k-document numbers: `eval/latency_10k.md` (`scripts/bench.py`).

## Out-of-catalog queries

`match_quality` on 20 queries with nothing relevant in the catalog: good 2, none 4, weak 14

| query | match_quality | total | top result |
|---|---|---:|---|
| refrigerator | weak | 100 | HariharaHome Silver 7.5 L Aluminium Pressure Cooker for Cook |
| washing machine | good | 29 | Aahwan Blue Non-Woven Clothes Storage Organiser Bag Pack of  |
| football | none | 0 |  |
| lipstick | weak | 100 | Boltixx Car Perfume - Jasmine Scent for Cars - 1pc |
| gold necklace | weak | 11 | Prakriti Women's Gold Kolhapuri Chappals / Synthetic Leather |
| baby diapers | weak | 100 | Tyaag Tees Red Solid Kids T-Shirt for Childrens Wear (5-6Y,  |
| dog food | none | 0 |  |
| printer ink cartridge | weak | 100 | Duniya Style Women's Pink Cotton Full Sleeve Printed Top (XS |
| sofa set | weak | 13 | KritiCraze Custom Fit Black Velvet Car Seat Cover for Cars |
| guitar strings | none | 0 |  |
| badminton racket | weak | 100 | RuchiRack Stainless Steel Water Bottle 1 Litre for Office Sc |
| face wash | weak | 100 | Veloxo Car Perfume - Jasmine Scented Car Air Freshener for C |
| umbrella | none | 0 |  |
| wrist watch | weak | 100 | Jatanix Grey Neckband with 30 hours Playback / Wireless Earb |
| school textbooks | weak | 100 | SAPTAK WHITE SCHOOL SHOES FOR KIDS / UK 1 & 2 / Synthetic Le |
| ceiling fan | weak | 100 | Saajni Silver Stainless Steel 1 L Electric Kettle - Fast Boi |
| yoga mat | weak | 100 | Ragamaya Women's Black Cotton Lycra Leggings for Yoga, Gym,  |
| sunglasses | weak | 100 | Kalyanx Women's Beige Canvas Sneakers for Running, Gym, Jogg |
| aata chakki machine | weak | 92 | SaralSpice Besan Atta / 1 kg Pack of Gram Flour for Veg Cook |
| laptop | good | 93 | DigiCraft Brown Laptop Bag / Stylish Synthetic Leather Lapto |

## Holdout (never tuned on)

| Segment | n | M1 nDCG@10 | **M2 nDCG@10** | Δ | M1 R@20 | M2 R@20 | zero-result |
|---|---:|---:|---:|---:|---:|---:|---:|
| **All** | 20 | — | **0.827** | — | — | 0.823 | 0% |
| hinglish | 20 | — | **0.827** | — | — | 0.823 | 0% |

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
| q023 | attribute | white canvas sneakers men | 0.96 | 1.00 | 1.00 | White, Canvas, Men, Sneakers | good | Nirmaan Men's Casual White Canvas Sneakers for Running  |
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
| q039 | price | saree under rs 1000 | 0.65 | 1.00 | 1.00 | Under ₹1,000, Sarees | good | Jalvaar Women's Chiffon Saree - Yellow for Women, Free  |
| q040 | price | dash cam under 3000 | 0.48 | 1.00 | 1.00 | Under ₹3,000 | good | Ariyanix 1080p Black Dash Cam for Cars / Black Dash Cam |
| q041 | price | 20000mah power bank under 1500 | 0.67 | 1.00 | 1.00 | Under ₹1,500, 20000mAh, Power Banks | good | TechRush Blue Power Bank / High Capacity 20000mAh Power |
| q042 | price | 5 L pressure cooker under 2000 | 0.81 | 1.00 | 1.00 | Under ₹2,000, 5 L, 5 L, Pressure Cookers | good | BhumiStore 5L Hard Anodised Black Pressure Cooker for F |
| q043 | price | laptop bag under 800 | 0.49 | 0.85 | 1.00 | Under ₹800, Laptop Bags | good | Sparkzen Grey Laptop Bag for Men - 15.6 Inch Laptop Bac |
| q044 | price | kurti between 500 and 1000 | 0.15 | 1.00 | 1.00 | ₹500 – ₹1,000 | good | Ragamaya Women's Mustard Georgette Kurti Kurta - Sleeve |
| q045 | price | car perfume under 300 | 0.55 | 1.00 | 1.00 | Under ₹300, Car Perfumes | good | RohanRide Car Perfume / Blue / Rose Fragrance / For Car |
| q046 | hinglish | 500 ke andar black shoes | 0.44 | 1.00 | 0.60 | Under ₹500, Black | good | Nirmaan Black Kids School Shoes - UK 1, UK 2, UK 3, UK  |
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

<!-- M3:BEGIN -->

## M3 — chat search

- Date: 2026-10-08 08:08 UTC · 25 conversations, 71 turns (`eval/conversations.jsonl`, marked needs_review)
- Chat model: openai:gpt-4.1-mini (default; gpt-5.4-mini grounds better but misses first-token p95) · judge: openai:gpt-5.5 (OpenAI in place of claude-haiku-4-5, approved by Rohit 2026-10-08)

| Target / metric | Result | |
|---|---|---|
| results event p95 ≤ 150 ms (rules path, client-measured) | 24 ms (n=60) | ✅ met |
| first text token p95 ≤ 1200 ms | 1109 ms (p50 730, n=68) | ✅ met |
| turn type accuracy | 99% (70/71) | |
| plan-assertion pass rate | 97% (36/37) | |
| per-turn nDCG@10 | 0.935 (n=57; turn 1 1.000, turn 2 0.891, turn 3+ 0.903) | |
| clarifier precision / recall (labelled turns) | 100% / 75% (asked on 19/71 turns; 0 where the label says don't ask) | |
| groundedness (judge: every claim supported) | 90% (61/68 answers) | |
| out-of-catalog chats: match_quality | good 2, none 4, weak 14 (none/weak 18/20; target ≥ 15) | ✅ met |

### Turn-type and plan failures

| conv | turn | user | expected | got | understood |
|---|---:|---|---|---|---|
| c18 | 2 | masala chai wali | refine | refine | Tea |
| c20 | 2 | type c wala | refine | new |  |

### Ungrounded answers (judge)

| conv | turn | answer | unsupported claim |
|---|---:|---|---|
| c04 | 2 | The Sparsh Clothing Wine Women's Georgette Saree is priced at ₹1299, slightly over the budget limit [AP-00277]. The Jalv | AP-00277 is slightly over the budget limit.: The active search constraint is under ₹1,300, and AP-00277 is priced at ₹1299, which is wi |
| c04 | 2 | The Sparsh Clothing Wine Women's Georgette Saree is priced at ₹1299, slightly over the budget limit [AP-00277]. The Jalv | AP-00437 has the highest rating.: AP-00437 has a higher listed rating than AP-00487, but AP-00277 has no rating field, so th |
| c07 | 2 | Sabse sasta Bluetooth Earbuds hai Fablez Blue Bluetooth Neckband ₹549 mein [EL-00427]. Agar earbuds chahiye toh Sparkzen | EL-00427 (Fablez Blue Bluetooth Neckband) is the cheapest Bluetooth Earbuds.: EL-00427 is priced at ₹549, but its category is 'Electronics Accessories > Audio > Neckban |
| c08 | 3 | The first product, Connecta Power Bank 20000mAh [EL-00243], has a wattage of 10W, which typically does not indicate fast | 10W typically does not indicate fast charging.: The product data lists EL-00243 as 10W but does not define what wattage qualifies as fast  |
| c08 | 3 | The first product, Connecta Power Bank 20000mAh [EL-00243], has a wattage of 10W, which typically does not indicate fast | EL-00243 does not support fast charging.: The product data does not explicitly state that EL-00243 supports or does not support fast |
| c09 | 1 | Sarson ka tel ke liye aap GauriGourmet Mustard Oil 1 L 549 Rs mein le sakte hain [GR-00226]. Agar aapko highest rating c | The stock status of DishaDhaba Mustard Oil 5 L needs to be checked / is not confirmed.: GR-00182 explicitly has in_stock set to true, so its stock status is known and it is in st |
| c09 | 2 | 5 L mustard oil me sabse sasta DishaDhaba Mustard Oil hai 199 Rs me, jo cold pressed hai [GR-00182]. Sabse accha rating  | HariyaliHub 5 L mustard oil options are priced from ₹499 to ₹699 [GR-00402, GR-00039].: GR-00402 is ₹699 and GR-00039 is ₹549; the cited products do not include a ₹499 item. A Ha |
| c17 | 3 | The KritiKraft Wireless Computer Mouse Blue has the highest rating of 5.0 and is priced at 1199 [EL-00128]. The ChargeOn | EL-00228 has a rating of 3.5.: EL-00228 has no rating field listed; 3.5 is the rating for EL-00088, not EL-00228. |
| c18 | 2 | Masala chai ke liye aapko chai patti mil sakti hai jaise DishaDhaba Chai Patti for Men 250g sirf ₹149 mein [GR-00307], j | DishaDhaba Chai Patti for Men 250g [GR-00307] is a chai patti option for masala chai.: The product is tea/chai patti and its description says it is suitable for daily consumptio |

### Out-of-catalog queries in chat

| query | match_quality | clarifier | answer |
|---|---|---|---|
| refrigerator | weak | I couldn't find an exact match. Is one of these close? | The search results do not include refrigerators but show various kitchen items like pressure cookers and conta |
| washing machine | good |  | The highest rated product is the Kalyaniware Blue Non-Woven Clothings Storage Organiser Bag priced at 649 with |
| football | none |  | No products related to "football" were found in the catalog. |
| lipstick | weak | I couldn't find an exact match. Is one of these close? | The search did not return exact matches for lipstick. The results mainly include car perfumes such as Boltixx  |
| gold necklace | weak | I couldn't find an exact match. Is one of these close? | The search results do not include gold necklaces but show various women's gold-colored footwear such as Kolhap |
| baby diapers | weak | I couldn't find an exact match. Is one of these close? | The search results do not include baby diapers but show various kids' T-shirts instead. Prices range from 199  |
| dog food | none |  | There are no dog food products available in the catalog at this time. |
| printer ink cartridge | weak | I couldn't find an exact match. Is one of these close? | The search did not return any printer ink cartridges but showed various apparel items instead. The lowest pric |
| sofa set | weak |  | The search results do not include exact matches for sofa sets; instead, they show various car seat covers. Amo |
| guitar strings | none |  | No guitar strings are available in the catalog at this time. |
| badminton racket | weak | I couldn't find an exact match. Is one of these close? | There are no exact matches for badminton rackets in the results. The items shown include stainless steel water |
| face wash | weak | I couldn't find an exact match. Is one of these close? | The search results do not include face wash products but show various car perfumes and microfiber cleaning clo |
| umbrella | none |  | There are no umbrellas available in the catalog at this time. |
| wrist watch | weak | I couldn't find an exact match. Is one of these close? | The search results show neckbands rather than wrist watches. Among these, the Aahvaan Red Wireless Neckband of |
| school textbooks | weak | I couldn't find an exact match. Is one of these close? | The search results do not include school textbooks but show various kids' school shoes instead. The lowest pri |
| ceiling fan | weak | I couldn't find an exact match. Is one of these close? | No exact matches for ceiling fans were found. The results show various electric kettles, including a Kalyaniwa |
| yoga mat | weak | I couldn't find an exact match. Is one of these close? | The search results do not include yoga mats but show various women's leggings suitable for yoga and fitness. T |
| sunglasses | weak | I couldn't find an exact match. Is one of these close? | The search results do not include sunglasses but show various footwear options like sneakers and sandals. The  |
| aata chakki machine | weak | Exact match nahi mila. Inme se kuch chahiye? | Yeh results aapke "aata chakki machine" ke liye exact matches nahi hain, yeh sab whole wheat atta (gehun ka aa |
| laptop | good | Which kind are you looking for? | The DigiCraft Brown Laptop Bag for 15.6 inch laptops is priced at 1899 with a rating of 4.1 [EL-00380]. The Kr |

### All turns

| conv | turn | user | type | understood | nDCG | clarifier | results ms | first token ms | answer |
|---|---:|---|---|---|---:|---|---:|---:|---|
| c01 | 1 | running shoes for men | new | Men, Running Shoes | 1.00 |  | 42 | 915 | The lowest priced men's running shoes are Aadivaan White Synthetic Slip-On shoes at 799 [FW-00201],  |
| c01 | 2 | cheaper ones | refine | Men, Under ₹2,199, Running Shoes, Lower prices first | 1.00 |  | 14 | 1050 | The cheapest men's running shoes are Sohum Blue Synthetic Slip-On priced at ₹549 [FW-00011]. Aadivaa |
| c01 | 3 | only black | refine | Men, Under ₹2,199, Black, Running Shoes, Lower prices first | 0.71 |  | 21 | 870 | Among the black men's running shoes under ₹2,199, the lowest priced is Shreyas Men's Sports Running  |
| c01 | 4 | is the second one lace-up? | question |  |  |  | 14 | 1109 | Yes, the second product, Prakriti Men's Black Mesh Running Shoes [FW-00181], has a lace-up closure. |
| c02 | 1 | ladies ke liye kurti chahiye | new | Women | 1.00 |  | 17 | 703 | Ladies ke liye kuch achhi kurtis available hain jaise Ragamaya Women's Mustard Georgette Kurti sirf  |
| c02 | 2 | 500 ke andar | refine | Women, Under ₹500 | 0.92 |  | 20 | 782 | 500 ke andar kuch achhe options hain jaise ki Ragamaya Women's Maroon Printed Sleeveless Rayon Kurti |
| c02 | 3 | pink nahi chahiye | refine | Women, Under ₹500, Not Pink | 0.84 |  | 18 | 750 | Pink nahi chahiye toh aapke liye Maroon cotton kurti [AP-00406] (price 349, rating 4.0) ya Maroon ra |
| c03 | 1 | pressure cooker | new | Pressure Cookers | 1.00 | Any preference for material? | 21 | 757 | The Dunedar 7.5 L Black Aluminium Pressure Cooker is priced at 1899 with a rating of 3.8 [HK-00281]. |
| c03 | 2 | a bigger one | refine | 7.5 L or 5 L, Pressure Cookers | 1.00 |  | 17 | 869 | You can consider the Dunedar 7.5 L Black Aluminium Pressure Cooker priced at 1899 [HK-00281] or the  |
| c03 | 3 | which is the cheapest? | question |  |  |  | 10 | 720 | The cheapest pressure cooker is the Dunedar Stainless Steel 7.5 L Pressure Cooker Black for Home Use |
| c04 | 1 | saree under rs 1000 | new | Under ₹1,000, Sarees | 1.00 | Only 1 match under ₹1,000. Want to see options slightly over budget? | 12 | 763 | The Jalvaar Women's Chiffon Saree in yellow is priced at ₹899 and has a rating of 4.3 [AP-00437]. Ot |
| c04 | 2 | Show slightly over budget | refine | Under ₹1,300, Sarees | 0.73 |  | 21 | 871 | The Sparsh Clothing Wine Women's Georgette Saree is priced at ₹1299, slightly over the budget limit  |
| c05 | 1 | shoes | new |  | 1.00 | Which kind are you looking for? | 18 | 819 | The Sohum White Synthetic Running Shoes for Men are priced at ₹1,999 with a rating of 4.1 and are in |
| c05 | 2 | Running Shoes | refine | Running Shoes | 1.00 |  | 7 | 681 | The Sohum White Synthetic Running Shoes for Men are priced at ₹1,999 with a rating of 4.1 and are in |
| c05 | 3 | under 1500 | refine | Running Shoes, Under ₹1,500 | 0.98 |  | 11 | 670 | You can find men's running shoes under ₹1500 such as the Sohum Blue Synthetic Slip-On shoes priced a |
| c06 | 1 | water bottle | new | Water Bottles | 1.00 | Any preference for color? | 18 | 808 | The Dunedar Blue Water Bottle is a 1-liter plastic bottle priced at 549 with the highest rating of 4 |
| c06 | 2 | not plastic | refine | Not Plastic, Water Bottles | 1.00 |  | 20 | 675 | There are several non-plastic water bottles available made from copper and stainless steel. The Saaj |
| c06 | 3 | only copper | refine | Not Plastic, Copper, Copper, Water Bottles | 0.56 |  | 14 | 730 | The AyushKitchen Copper Water Bottle 750 ml has the highest rating of 4.1 and costs 499 [HK-00087].  |
| c07 | 1 | bluetooth earbuds | new | Bluetooth Earbuds | 1.00 | Any preference for color? | 21 | 631 | The Fablez White Bluetooth Earbuds offer the highest rating of 4.8 and 50 hours of playback for 2099 |
| c07 | 2 | aur sasta | refine | Under ₹1,699, Bluetooth Earbuds, Lower prices first | 0.94 |  | 26 | 742 | Sabse sasta Bluetooth Earbuds hai Fablez Blue Bluetooth Neckband ₹549 mein [EL-00427]. Agar earbuds  |
| c07 | 3 | sabse sasta kaunsa hai? | question |  |  |  | 9 | 988 | Sabse sasta product Fablez Blue Bluetooth Neckband hai jo 549 INR ka hai [EL-00427]. |
| c08 | 1 | power bank | new | Power Banks | 1.00 | Any preference for color? | 19 | 948 | The Connecta Power Bank offers 20000mAh capacity with 10W output at a price of 2599 [EL-00243]. The  |
| c08 | 2 | 20000mAh only | refine | 20000mAh, Power Banks | 1.00 |  | 18 | 652 | There are several 20000mAh power banks available, including the Vibrota White High Capacity Power Ba |
| c08 | 3 | does the first one support fast charging? | question |  |  |  | 6 | 707 | The first product, Connecta Power Bank 20000mAh [EL-00243], has a wattage of 10W, which typically do |
| c09 | 1 | sarson ka tel | new | Mustard Oil | 1.00 | Volume ka koi preference? | 18 | 703 | Sarson ka tel ke liye aap GauriGourmet Mustard Oil 1 L 549 Rs mein le sakte hain [GR-00226]. Agar aa |
| c09 | 2 | 5 L wala | refine | 5 L, Mustard Oil | 1.00 |  | 16 | 648 | 5 L mustard oil me sabse sasta DishaDhaba Mustard Oil hai 199 Rs me, jo cold pressed hai [GR-00182]. |
| c10 | 1 | hi | chitchat |  |  |  | 4 | 4 | I can help you find products. Try something like 'black running shoes under 1500'. |
| c10 | 2 | I need a helmet for my bike | new | Helmets, Bike | 1.00 | Any preference for brand? | 7 | 651 | You can consider the KritiCraze Red Fibreglass Full Face Bike Helmet priced at 1099 with a rating of |
| c10 | 3 | full face | refine | Full Face, Helmets, Bike | 1.00 |  | 17 | 704 | The KritiCraze Red Fibreglass Full Face Bike Helmet is priced at 1099 and has a rating of 4.2 [AU-00 |
| c10 | 4 | thanks! | chitchat |  |  |  | 4 | 4 | I can help you find products. Try something like 'black running shoes under 1500'. |
| c11 | 1 | gents chappal | new | Men | 1.00 | Kaunsa type chahiye? | 10 | 753 | Gents chappal mein Sohum Men's Grey Rubber Sandal sabse acchi rating ke sath 4.5 rating aur price ₹1 |
| c11 | 2 | brown wala | refine | Men, Brown | 1.00 |  | 18 | 821 | Brown color ke men's sandals mein Kalyanx ke Genuine Leather sandals [FW-00024] ka rating sabse zyad |
| c12 | 1 | t-shirt for men | new | Men, T-Shirts or T-Shirts | 1.00 |  | 21 | 750 | You can find men's t-shirts ranging from ₹349 to ₹999. The highest rated t-shirt is the Duniya Style |
| c12 | 2 | oversized | refine | Men, Oversized, T-Shirts or T-Shirts | 1.00 |  | 16 | 669 | The highest rated oversized men's T-shirt is the Ragamaya Green Cotton Half Sleeve Solid T-Shirt pri |
| c12 | 3 | under 500 | refine | Men, Oversized, Under ₹500, T-Shirts or T-Shirts | 0.85 |  | 23 | 710 | There are several oversized men's T-shirts under ₹500, including the Duniya Style Grey Oversized Cot |
| c13 | 1 | khana banane ke bartan | new | Cookware | 1.00 | Kaunsa type chahiye? | 22 | 898 | Aapke liye kuch khana banane ke bartan hain jaise Aahwan ka 3 L Silver Aluminium Pressure Cooker jo  |
| c13 | 2 | Kadai | refine | Kadai | 1.00 |  | 11 | 694 | The Kalyaniware Classic Kadai 1.5 L is a cast iron cookware with the highest rating of 4.9 and price |
| c13 | 3 | lohe ki | refine | Kadai, Iron | 1.00 |  | 14 | 710 | Lohe ki Kadai me AyushKitchen ka 1.5 L Black Iron Kadai sabse accha rating wala hai 4.6 ke saath [HK |
| c14 | 1 | car seat cover | new | Car, Seat Covers | 1.00 |  | 20 | 644 | The Dhruvix Red Car Seat Cover is a velvet universal fit option priced at 1999 [AU-00211]. The Bolti |
| c14 | 2 | leatherette | refine | Leatherette, Car, Seat Covers | 1.00 |  | 6 | 717 | Leatherette car seat covers are available in various colors and fits, including custom and universal |
| c14 | 3 | what colours does the first one come in? | question |  |  |  | 6 | 650 | The first product, PulsarPro Tan Custom Fit Leatherette Car Seat Cover for Car [AU-00451], comes in  |
| c15 | 1 | atta | new |  | 1.00 | Which kind are you looking for? | 13 | 752 | The HariyaliHub 10 kg Whole Wheat Atta is highly rated at 4.6 and priced at 299 [GR-00342]. The Sara |
| c15 | 2 | smaller pack | refine | 1 kg or 2 kg or 5 kg | 0.63 |  | 21 | 660 | For smaller pack options, there are several 1 kg whole wheat atta products such as PragatiProvisions |
| c16 | 1 | bacchon ke school ke joote | new | Kids, School Shoes | 1.00 |  | 19 | 698 | Bacchon ke school shoes mein Aadivaan White Synthetic Leather shoes sirf 399 rupees ke price par mil |
| c16 | 2 | white wale | refine | Kids, White, School Shoes | 1.00 |  | 15 | 634 | White kids school shoes me sabse sasta option SAPTAK ka hai jo 349 rupees me milta hai aur synthetic |
| c16 | 3 | velcro wale? | refine | Kids, White, Velcro, School Shoes | 1.00 |  | 20 | 774 | Velcro wale white kids school shoes me se Aadivaan Canvas shoes ka rating sabse zyada 4.8 hai aur pr |
| c17 | 1 | laptop bag | new | Laptop Bags | 1.00 | Any preference for color? | 18 | 650 | The Sparkzen Men's Laptop Bag in Navy Blue is priced at 2399 with a rating of 3.9 and fits 17-inch l |
| c17 | 2 | for a 15.6 inch laptop | refine | 15.6 inch, Laptop Bags | 1.00 |  | 18 | 1855 | For a 15.6 inch laptop, the KritiKraft Grey Nylon Laptop Bag has the highest rating of 4.4 and is pr |
| c17 | 3 | now show me wireless mouse | new | Wireless, Mouse | 1.00 | Any preference for color? | 13 | 715 | The KritiKraft Wireless Computer Mouse Blue has the highest rating of 5.0 and is priced at 1199 [EL- |
| c18 | 1 | chai patti | new | Tea | 1.00 |  | 10 | 677 | Chai patti ke liye aapko 250g ka DishaDhaba Chai Patti 149 Rs mein milta hai jiska rating 4 hai [GR- |
| c18 | 2 | masala chai wali | refine | Tea ✗ | 0.35 |  | 18 | 712 | Masala chai ke liye aapko chai patti mil sakti hai jaise DishaDhaba Chai Patti for Men 250g sirf ₹14 |
| c18 | 3 | isme sabse badi packing kaunsi hai? | question |  |  |  | 7 | 1116 | Sabse badi packing 1 kg ki hai, jaise ki NirvanaNourish 1 kg CTC Veg Tea Leaves [GR-00241], SaralSpi |
| c19 | 1 | refrigerator | new |  |  | I couldn't find an exact match. Is one of these close? | 20 | 773 | There are no exact matches for refrigerators in the results. The items shown include various pressur |
| c19 | 2 | ok what about an electric kettle | new | Electric Kettles | 1.00 | Any preference for color? | 18 | 695 | There are several electric kettles available with prices ranging from 649 to 1999. The Aahwan Silver |
| c20 | 1 | mobile charge karne wala tar | new | Cables | 1.00 |  | 24 | 825 | Mobile charging cables me braided nylon material wale options jaise DigiCraft 2m black cable 449 rup |
| c20 | 2 | type c wala | new ✗ |  | 0.87 | Kaunsa type chahiye? | 12 | 820 | Type C cables me se sabse sasta braided nylon cable KritiKraft ka 1m cable hai jo 199 rupees me milt |
| c20 | 3 | 2m lamba chahiye | refine | 2m | 1.00 |  | 9 | 730 | 2m lamba braided nylon USB-C cable ChargeOn se 349₹ mein milta hai [EL-00102]. Agar aapko sabse sast |
| c21 | 1 | silk saree | new | Silk, Sarees | 1.00 |  | 9 | 657 | The highest rated silk saree is the Aaramyaa Women's Red Silk Embroidered Saree priced at 2099 with  |
| c21 | 2 | red or maroon | refine | Silk, Red or Maroon, Sarees | 0.63 |  | 15 | 674 | You can choose the Kaalpaash Maroon Silk Saree priced at 4699 with a rating of 3.8 [AP-00347], or th |
| c21 | 3 | is the first one embroidered? | question |  |  |  | 10 | 727 | The first saree, Kaalpaash Maroon Silk Saree, is woven and not embroidered [AP-00347]. The embroider |
| c22 | 1 | dal | new |  | 1.00 |  | 17 | 969 | The SampoornaStore Moong Dal 1 kg pack is priced at 149 with a rating of 4.1 and is in stock [GR-002 |
| c22 | 2 | Moong Dal | refine | Moong Dal | 1.00 |  | 7 | 749 | The SampoornaStore Moong Dal 1 kg pack is priced at 149 with a rating of 4.1 [GR-00280]. HariyaliHub |
| c22 | 3 | 1 kg | refine | Moong Dal, 1 kg | 1.00 |  | 11 | 839 | The SampoornaStore Moong Dal 1 kg pack is priced at 149 with a rating of 4.1 and is in stock [GR-002 |
| c23 | 1 | dash cam | new |  | 1.00 | Any preference for resolution? | 19 | 881 | The Dhruvix 2K Dash Cam for Cars offers the highest rating of 4.5 and is priced at 5499 [AU-00127].  |
| c23 | 2 | 4K only, just show | refine | 4K | 1.00 |  | 10 | 659 | The Boltixx 4K Dash Cam for Cars [AU-00487] has the highest rating of 4.2 and includes night vision. |
| c23 | 3 | does it have night vision? | question |  |  |  | 12 | 1047 | The Boltixx 4K Dash Cam for Cars with ID AU-00487 has night vision. The other dash cams listed do no |
| c24 | 1 | jeans | new | Jeans | 1.00 | Any preference for color? | 15 | 1051 | You can find men's jeans in various colors such as black, grey, blue, and navy blue. The lowest pric |
| c24 | 2 | slim fit, black nahi | refine | Not Black, Not Slim Fit, Jeans | 0.33 |  | 17 | 679 | You can find men's regular fit jeans in grey and blue colors such as the Kaviya Kraft Grey Regular F |
| c25 | 1 | football | new |  |  |  | 19 | 834 | No products related to "football" were found in the catalog. |
| c25 | 2 | how are you | chitchat |  |  |  | 9 | 9 | I can help you find products. Try something like 'black running shoes under 1500'. |
| c25 | 3 | show me yoga mats | new |  |  | I couldn't find an exact match. Is one of these close? | 523 | 1208 | The search results do not include yoga mats but show various women's leggings suitable for yoga and  |

### Analysis

**Model choice.** The brief asks for claude-haiku-4-5. No Anthropic key was available, so Rohit approved OpenAI.
The same 71-turn eval was run with three chat models:

| Model | First token p95 | Groundedness |
|---|---:|---:|
| gpt-4.1-mini (default) | 915–1,109 ms | 88–90% |
| gpt-4o-mini | 1,009 ms | 84% |
| gpt-5.4-mini (reasoning `none`) | 1,237–1,456 ms | 93–96% |

gpt-5.4-mini grounds best but misses the 1.2 s first-token target, so the default is gpt-4.1-mini. Two prompt
changes closed most of the grounding gap:
- the model sees every product on screen, not just the top 5;
- comparisons ("cheapest", "highest rated") are computed in code and handed to the model as facts.

Set `ZERCH_CHAT_MODEL=gpt-5.4-mini` to prefer grounding over latency.

**Known-problem fixes from M2.**
- *match_quality:* now also uses planner evidence (did the rules recognise a catalog value or category, or did the
  user confirm one in chat) and how many query words the top results actually contain. Synonym expansions count,
  and missing words only lower the quality when the catalog has never seen them.
  - Result: 18/20 out-of-catalog queries get `none`/`weak`, and 0 in-catalog queries get `none`.
  - Still `good`: "laptop" (laptop bags) and "washing machine" (laundry organisers).
- *Backfill:* "saree under rs 1000" now shows the one saree under ₹1,000, then sarees just over budget, cheapest
  first. It used to show tea and bellies. Rules:
  - Filler and backfill stay inside the category the lexical matches agree on.
  - Category votes are weighted by lexical score, so a weak fuzzy match can't redirect it.
  - Price segment: 0.900 → 0.954.

**Remaining failures.**
- *Turn type ("type c wala").* "type c" isn't recognised as USB-C, so it's treated as a new search. That
  needs a synonym the packs don't have; it wasn't added to avoid tuning on the eval.
- *Groundedness (judge-flagged answers, about 10%), three kinds:*
  - Category slips: calling a neckband "earbuds", because "bluetooth earbuds" retrieval includes neckbands.
  - Inference beyond the fields: "10W typically means no fast charging".
  - A few judge disagreements. For example, "slightly over budget" for ₹1,299 is correct relative to the
    original ₹1,000 budget, but the judge only sees the relaxed ₹1,300 cap.
- *Clarifier recall 75%.* "dal" doesn't trigger a category question. The query also matches a spice ("dal
  tadka masala"), so no single parent category covers 90% of the results.
- *Clarifier frequency.* It asks on 19/71 turns. Bare category queries ("water bottle", "jeans") get an
  attribute question ("Any preference for color?") when results spread evenly. The brief's rule allows it.
  Whether it's wanted is a product call for review.

**Caveats.**
- *The conversations aren't independent.* They were written by the same model that built the rules, and are
  marked `needs_review`. Several were checked while iterating (turn classification, refinement rules), so the
  turn-type and plan numbers are dev-set numbers, not holdout numbers.
- *The judge is an LLM too* (gpt-5.5), not human review.
- *Latency is client-measured* against Docker on a laptop. First-token time is dominated by the OpenAI API, about
  700 ms at p50.

<!-- M3:END -->
