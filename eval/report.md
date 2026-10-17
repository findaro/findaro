# Eval report — M2 query understanding

- Date: 2026-10-10 23:42 UTC · commit `d4a1a2c` · arm64 Darwin
- Catalog: `data/demo_catalog.jsonl` (3000 docs) · 66 queries · 20 out-of-catalog negatives · 20 holdout queries
- Planner LLM: see docker-compose.yml
- Baseline: `eval/baselines/m1.json` (M1 on the reviewed query set, nDCG@10 0.808); M1 report kept in `eval/report_m1.md`

## Targets

| Target | Result | |
|---|---|---|
| price nDCG@10 ≥ 0.85 | 0.954 | ✅ met |
| hinglish nDCG@10 ≥ 0.8 | 0.910 | ✅ met |
| no segment regresses by more than 0.02 | worst: plain +0.000 | ✅ met |
| server p95 ≤ 30 ms, rules-only path | 24.7 ms | ✅ met |
| server p95 ≤ 1000 ms, LLM path uncached | 849.2 ms (n=1) | ✅ met |

## Relevance vs M1

| Segment | n | M1 nDCG@10 | **M2 nDCG@10** | Δ | M1 R@20 | M2 R@20 | zero-result |
|---|---:|---:|---:|---:|---:|---:|---:|
| **All** | 66 | 0.808 | **0.970** | +0.161 | 0.791 | 0.982 | 0% |
| plain | 10 | 1.000 | **1.000** | +0.000 | 1.000 | 1.000 | 0% |
| typo | 11 | 1.000 | **1.000** | +0.000 | 1.000 | 1.000 | 0% |
| attribute | 14 | 0.938 | **0.972** | +0.034 | 0.989 | 1.000 | 0% |
| price | 10 | 0.529 | **0.954** | +0.425 | 0.424 | 1.000 | 0% |
| hinglish | 13 | 0.505 | **0.910** | +0.406 | 0.460 | 0.913 | 0% |
| nl | 8 | 0.920 | **1.000** | +0.080 | 0.894 | 0.994 | 0% |

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
- **The LLM path barely runs on this eval.** Only 1 of 66 queries reaches it, so the "LLM p95 ≤ 1 s" target is met on n=1, and only because of the 800 ms timeout. The separate probe (`eval/llm_queries.jsonl`, 10 queries with words the rules can't read) is more informative. With local `llama3.2:3b` every call times out uncached (p95 ≈ 830 ms incl. fallback). Once its answers are cached, nDCG on the probe rises from 0.57 to 0.69. A faster, stronger planner (Claude Haiku 4.5 needs `FINDARO_ANTHROPIC_API_KEY`, not available in this environment) is the obvious next measurement. The probe was used to fix a prompt bug (the model copied the example price into its answer), so it is not a clean holdout either.
- **The "no match" floor barely separates.** With e5-small, out-of-catalog queries score 0.901–0.920 on vectors. Untranslated in-catalog Hinglish scores 0.899–0.914. The floor (0.905) is set conservatively, so unknown Hinglish isn't blanked. As a result, 4 of 20 negatives get `none`, 12 get `weak` (no lexical match), and 4 get `good` through accidental word overlap ("sofa set" → dinner set, "laptop" → laptop bag). In-catalog queries never get `none`.
- **Latency.** 30 ms holds with a warm query embedding (p95 ≈ 11 ms here, 13 ms at 10k docs). A query whose embedding isn't cached pays about 50 ms of CPU e5 inference (p95 ≈ 66 ms at 10k docs), the same as in M1.

## Query planner

- LLM needed (rules plan unsure): **1/66** queries (2%). Outcomes on the uncached pass: timeout 1
- Plan cache hit rate on repeat runs (LLM-needed queries): **100%** (5/5)
- Queries where a filter was relaxed after zero results: 0

### Latency by path (server `took_ms`, query embeddings warm)

| Path | n | p50 | p95 | p99 |
|---|---:|---:|---:|---:|
| rules only | 325 | 12.1 ms | 24.7 ms | 52.3 ms |
| LLM, uncached (incl. timeouts) | 1 | 849.2 ms | 849.2 ms | 849.2 ms |
| LLM plan from cache | 5 | 14.5 ms | 27.4 ms | 27.4 ms |

### LLM path probe (`eval/llm_queries.jsonl`, 10 queries with words the rules can't read)

- Reached the LLM: 8/10; outcomes: busy 6, timeout 2
- Server latency, uncached: p50 16.4 ms, p95 861.6 ms
- nDCG@10 uncached (timeouts fall back to rules): **0.578** · with the LLM plan from cache: **0.583**

| query | LLM (uncached) | took | nDCG uncached | nDCG cached plan | semantic text (cached plan) |
|---|---|---:|---:|---:|---|
| safai ka kapda gaadi ke liye | timeout | 832.4 ms | 1.00 | 1.00 | Car cleaning cloth |
| nahane ke baad pehenne wali chappal | timeout | 861.6 ms | 1.00 | 0.00 | Women Flats & Bellies |
| paani ubalne wali ketli | busy | 16.4 ms | 1.00 | 1.00 | water boiling kettle |
| sabzi kaatne ki machine | busy | 15.2 ms | 0.00 | 1.00 | Vegetable chopper |
| makhmali seat cover | not_needed | 15.5 ms | 0.83 | 0.83 | makhmali seat cover |
| khushboo wala gaadi ka | busy | 17.9 ms | 0.66 | 0.00 | Women's Flats & Bellies |
| sir ki suraksha ke liye bike | busy | 20.1 ms | 0.29 | 1.00 | bike safety |
| haath ke dastane bike chalane ke liye | busy | 14.5 ms | 0.00 | 0.00 | Bike helmets |
| kaan mein lagane wale bina taar ke | busy | 14.2 ms | 0.00 | 0.00 | Earphones without cable |
| roti banane ka tawa lohe ka | not_needed | 23.3 ms | 1.00 | 1.00 | roti making tawa iron |

Cold-embedding and 10k-document numbers: `eval/latency_10k.md` (`scripts/bench.py`).

## Out-of-catalog queries

`match_quality` on 20 queries with nothing relevant in the catalog: good 2, none 4, weak 14

| query | match_quality | total | top result |
|---|---|---:|---|
| refrigerator | weak | 100 | HariharaHome Silver 7.5 L Aluminium Pressure Cooker for Cook |
| washing machine | good | 187 | Duniya Style Women's White Printed Cotton Full Sleeve Top /  |
| football | none | 0 |  |
| lipstick | none | 0 |  |
| gold necklace | weak | 10 | Aadivaan Women's Gold Genuine Leather Kolhapuri Chappals for |
| baby diapers | weak | 100 | Tyaag Tees Red Solid Kids T-Shirt for Childrens Wear (5-6Y,  |
| dog food | weak | 100 | AashirvaadAvenue Toor Dal 1kg Pack, Pure Vegetarian, Healthy |
| printer ink cartridge | weak | 100 | Ragamaya Women's Printed Full Sleeve Top / Cotton Fabric, Pi |
| sofa set | weak | 14 | Dhruvix Beige Universal Fit Velvet Car Seat Cover for Comfor |
| guitar strings | none | 0 |  |
| badminton racket | weak | 100 | RuchiRack Stainless Steel Water Bottle 1 Litre for Office Sc |
| face wash | weak | 326 | Ragamaya Men's Skinny Fit Black Denim Jeans / Casual Wear fo |
| umbrella | none | 0 |  |
| wrist watch | weak | 100 | Aahvaan Red Wireless Neckband / 40 hours Long Playtime Bluet |
| school textbooks | weak | 61 | Anantara Kids School Shoes / Black School Shoes for Boys & G |
| ceiling fan | weak | 100 | Saajni Silver Stainless Steel 1 L Electric Kettle - Fast Boi |
| yoga mat | weak | 100 | Ragamaya Women's Grey Cotton Lycra Leggings for Yoga, Fitnes |
| sunglasses | weak | 100 | Kalyanx Black Colour Men's Synthetic Sandals - Buckle Closur |
| aata chakki machine | weak | 92 | SaralSpice Besan Atta / 1 kg Pack of Gram Flour for Veg Cook |
| laptop | good | 93 | DigiCraft Brown Laptop Bag / Stylish Synthetic Leather Lapto |

## Holdout (never tuned on)

| Segment | n | M1 nDCG@10 | **M2 nDCG@10** | Δ | M1 R@20 | M2 R@20 | zero-result |
|---|---:|---:|---:|---:|---:|---:|---:|
| **All** | 20 | — | **0.818** | — | — | 0.812 | 0% |
| hinglish | 20 | — | **0.818** | — | — | 0.812 | 0% |

## Per query

| id | type | query | M1 | M2 | R@20 | understood | quality | top result |
|---|---|---|---:|---:|---:|---|---|---|
| q001 | plain | pressure cooker | 1.00 | 1.00 | 1.00 | Pressure Cookers | good | BhumiStore 5 Litre Stainless Steel Pressure Cooker Blac |
| q002 | plain | bluetooth earbuds | 1.00 | 1.00 | 1.00 | Bluetooth Earbuds | good | DigiCraft Blue Bluetooth Earbuds / 24 Hours Playback /  |
| q003 | plain | kolhapuri chappals | 1.00 | 1.00 | 1.00 | Kolhapuri Chappals | good | Aadivaan Women's Tan Kolhapuri Chappals - Best Quality  |
| q004 | plain | car seat cover | 1.00 | 1.00 | 1.00 | Car, Seat Covers | good | Dhruvix Red Car Seat Cover / Velvet Universal Fit Car S |
| q005 | plain | garam masala | 1.00 | 1.00 | 1.00 | Garam Masala | good | SaralSpice 200g Garam Masala Powder for Veg - Garam Mas |
| q006 | plain | desi ghee | 1.00 | 1.00 | 1.00 | Ghee | good | DishaDhaba Desi Ghee 1 L / Veg Buffalo Milk Ghee for Co |
| q007 | plain | leggings | 1.00 | 1.00 | 1.00 | Leggings | good | Kaviya Kraft Women's Navy Blue Cotton Lycra Leggings /  |
| q008 | plain | electric kettle | 1.00 | 1.00 | 1.00 | Electric Kettles | good | Nirvana Nest Black 1.8L 1200W Electric Kettle Plastic / |
| q009 | plain | dinner set | 1.00 | 1.00 | 1.00 | Dinner Sets | good | Aahwan Multicolor 24-Piece Stainless Steel Dinner Set / |
| q010 | plain | neckband | 1.00 | 1.00 | 1.00 | Neckbands | good | DigiCraft Blue Neckband with 20 Hours Playback for Musi |
| q011 | typo | presure cooker | 1.00 | 1.00 | 1.00 | Pressure Cookers | good | BhumiStore 3 L Silver Aluminium Pressure Cooker |
| q012 | typo | wirless earbuds | 1.00 | 1.00 | 1.00 | Bluetooth Earbuds | good | Sparkzen Grey Bluetooth Earbuds for 24 Hours Music Play |
| q013 | typo | kolapuri chappal | 1.00 | 1.00 | 1.00 | Kolhapuri Chappals | good | Dhanvi Women's Gold Kolhapuri Chappals / Traditional Sa |
| q014 | typo | car seet cover | 1.00 | 1.00 | 1.00 | Car, Cover [llm: timeout] | good | Dhruvix Red Car Seat Cover / Velvet Universal Fit Car S |
| q015 | typo | garam masla | 1.00 | 1.00 | 1.00 |  | good | SaralSpice 200g Garam Masala Powder for Veg - Garam Mas |
| q016 | typo | bluetoth neckband | 1.00 | 1.00 | 1.00 | Neckbands | good | TechRush Blue Bluetooth Neckband for Music, 20 hours Pl |
| q017 | typo | basmathi rice | 1.00 | 1.00 | 1.00 | Rice | good | BhavnaBazaar 5 kg Basmati Rice - Extra Long Grain - Veg |
| q018 | typo | runing shoes | 1.00 | 1.00 | 1.00 | Shoes | good | VedaVibes White Men's Running Shoes for Men / Lightweig |
| q019 | typo | electrik kettle | 1.00 | 1.00 | 1.00 | Electric Kettles | good | SuruchiSpace White 1.5 L Electric Kettle, Best Quality  |
| q020 | typo | helmat for bike | 1.00 | 1.00 | 1.00 | Bike | good | RohanRide Black ABS Plastic Half Face Helmet for Bike - |
| q021 | typo | lether formal shoes | 1.00 | 1.00 | 1.00 | Formal Shoes | good | Sohum Men's Brown Slip-On Formal Shoes / Brown Syntheti |
| q022 | attribute | black running shoes for men | 0.92 | 0.92 | 1.00 | Black, Men, Running Shoes | good | Sohum Men's Black Black Men's Running Shoes / Black Run |
| q023 | attribute | white canvas sneakers men | 0.96 | 1.00 | 1.00 | White, Canvas, Men, Sneakers | good | Nirmaan Men's Casual White Canvas Sneakers for Running  |
| q024 | attribute | brown formal shoes genuine leather | 0.94 | 0.97 | 1.00 | Brown, Genuine Leather, Formal Shoes | good | Sohum Men's Brown Genuine Leather Formal Shoes, for Men |
| q025 | attribute | 65W usb-c charger | 0.88 | 1.00 | 1.00 | 65W, USB-C, Chargers | good | Sparkzen White 65W USB-C Mobile Charger - Fast Charging |
| q026 | attribute | 20000mAh power bank | 1.00 | 1.00 | 1.00 | 20000mAh, Power Banks | good | Connecta Power Bank 20000mAh / Connecta Black Power Ban |
| q027 | attribute | stainless steel water bottle 1 L | 0.83 | 1.00 | 1.00 | Stainless Steel, Water Bottles, 1 L, 1 L | good | Kalyaniware Pink Stainless Steel Water Bottle 1 L for O |
| q028 | attribute | cast iron tawa | 1.00 | 1.00 | 1.00 | Cast Iron, Tawa | good | SuruchiSpace Black Cast Iron Tawa / Black Cast Iron Taw |
| q029 | attribute | black full face helmet | 1.00 | 1.00 | 1.00 | Black, Full Face, Helmets | good | NirvaanGear Black Color ABS Plastic Full Face Helmet fo |
| q030 | attribute | slim fit black jeans | 0.97 | 0.96 | 1.00 | Black, Slim Fit, Jeans | good | Duniya Style Men's Slim Fit Black Denim Jeans for Mens |
| q031 | attribute | white cotton kurta for men | 1.00 | 0.76 | 1.00 | White, Cotton, Men, Kurtas | good | Niyati Wear Men's White Cotton Printed Kurtas / Casual  |
| q032 | attribute | red silk saree | 1.00 | 1.00 | 1.00 | Red, Silk, Sarees | good | Aaramyaa Women's Red Silk Embroidered Saree for Women / |
| q033 | attribute | kachi ghani mustard oil 1 L | 1.00 | 1.00 | 1.00 | Kachi Ghani, Mustard Oil, 1 L, 1 L | good | PragatiProvisions Mustard Oil / 1 L |
| q034 | attribute | wireless mouse | 0.64 | 1.00 | 1.00 | Wireless, Mouse | good | Fablez Wireless White Computer Mouse / Long Lasting Whi |
| q035 | attribute | toor dal 1 kg | 1.00 | 1.00 | 1.00 | Toor Dal, 1 kg | good | AashirvaadAvenue Toor Dal 1kg Pack, Pure Vegetarian, He |
| q036 | price | running shoes under 1000 | 0.38 | 0.92 | 1.00 | Under ₹1,000, Running Shoes | good | Aadivaan Men's White Synthetic Running Shoes for Men -  |
| q037 | price | bluetooth earbuds below 1500 | 0.63 | 0.98 | 1.00 | Under ₹1,500, Bluetooth Earbuds | good | Sparkzen Blue Bluetooth Earbuds / Long Lasting 40 Hours |
| q038 | price | men's t-shirt under 300 | 0.47 | 0.79 | 1.00 | Under ₹300, Men, T-Shirts or T-Shirts | good | Saveraa White Oversized Half Sleeve Printed Men's T-Shi |
| q039 | price | saree under rs 1000 | 0.65 | 1.00 | 1.00 | Under ₹1,000, Sarees | good | Jalvaar Women's Chiffon Saree - Yellow for Women, Free  |
| q040 | price | dash cam under 3000 | 0.48 | 1.00 | 1.00 | Under ₹3,000 | good | Ariyanix 1080p Black Dash Cam for Cars / Black Dash Cam |
| q041 | price | 20000mah power bank under 1500 | 0.67 | 1.00 | 1.00 | Under ₹1,500, 20000mAh, Power Banks | good | ChargeOn 20000mAh Grey Power Bank / Mobile Phone Portab |
| q042 | price | 5 L pressure cooker under 2000 | 0.81 | 1.00 | 1.00 | Under ₹2,000, 5 L, 5 L, Pressure Cookers | good | BhumiStore 5L Hard Anodised Black Pressure Cooker for F |
| q043 | price | laptop bag under 800 | 0.49 | 0.85 | 1.00 | Under ₹800, Laptop Bags | good | Sparkzen Grey Laptop Bag for Men - 15.6 Inch Laptop Bac |
| q044 | price | kurti between 500 and 1000 | 0.15 | 1.00 | 1.00 | ₹500 – ₹1,000 | good | Ragamaya Women's Mustard Georgette Kurti Kurta - Sleeve |
| q045 | price | car perfume under 300 | 0.55 | 1.00 | 1.00 | Under ₹300, Car Perfumes | good | KavyaKraft Luxury Jasmine Car Perfume / Car Freshener f |
| q046 | hinglish | 500 ke andar black shoes | 0.44 | 1.00 | 0.60 | Under ₹500, Black, Shoes | good | Aadivaan Black Canvas School Shoes / Kids School Shoes  |
| q047 | hinglish | kapde rakhne wala bag | 0.79 | 1.00 | 1.00 | Storage & Containers or Home Storage | good | Aahwan 4-Piece Beige Polyester Clothes Storage Organise |
| q048 | hinglish | ladkiyon ke liye kurti | 0.94 | 1.00 | 1.00 | Women | good | Ragamaya Women's Mustard Georgette Kurti Kurta - Sleeve |
| q049 | hinglish | sasta pressure cooker | 0.54 | 0.73 | 1.00 | Pressure Cookers, Lower prices first | good | Aahwan Aluminium Pressure Cooker 7.5 Litre Black for Ho |
| q050 | hinglish | gaadi ke liye phone stand | 0.33 | 0.38 | 0.27 | Car | good | Veloxo Car Phone Holder / Dashboard Mount Black Plastic |
| q051 | hinglish | chai patti 1 kg | 1.00 | 1.00 | 1.00 | Tea, 1 kg | good | NirvanaNourish 1 kg CTC Veg Tea Leaves for Chai Lovers |
| q052 | hinglish | gents chappal | 0.00 | 1.00 | 1.00 | Men, Kolhapuri Chappals | good | Saptak Grey Rubber Men's Sandals / Comfortable Beach Sl |
| q053 | hinglish | shaadi ke liye silk saree | 1.00 | 1.00 | 1.00 | Silk, Sarees | good | Kaalpaash Maroon Silk Saree for Women, Woven, Free Size |
| q054 | hinglish | khana banane ke bartan | 0.15 | 1.00 | 1.00 | Cookware | good | Aahwan 3 L Silver Aluminium Pressure Cooker / Heavy Dut |
| q055 | hinglish | mobile charge karne wala tar | 0.00 | 1.00 | 1.00 | Cables | good | PulseZone White 2m Lightning PVC Mobile Charging Cable |
| q056 | hinglish | sarson ka tel | 0.00 | 1.00 | 1.00 | Mustard Oil | good | AashirvaadAvenue Mustard Oil / 2 L |
| q057 | hinglish | 1000 se kam mein earbuds | 0.66 | 0.73 | 1.00 | Under ₹1,000, Bluetooth Earbuds | good | TechRush Grey Bluetooth Earbuds for 24 Hours Music Play |
| q058 | hinglish | bacchon ke school ke joote | 0.72 | 1.00 | 1.00 | Kids, School Shoes | good | Aadivaan White Kids School Shoes / Synthetic Leather Sh |
| q059 | nl | something to carry water to office | 0.93 | 1.00 | 0.95 |  | good | Saajni Copper Water Bottle / Silver 750 ml Water Bottle |
| q060 | nl | shoes for jogging in the morning | 0.82 | 1.00 | 1.00 | Shoes | good | Anantara Men's Black Sports Running Shoes / Lightweight |
| q061 | nl | comfortable footwear for women under 1000 | 0.67 | 1.00 | 1.00 | Under ₹1,000, Women, Footwear | good | Saptak Women's Tan Flats - UK 6, 7, 8, Fabric, Comforta |
| q062 | nl | fast charger for my phone | 0.94 | 1.00 | 1.00 | Chargers | good | Sparkzen 45W Black USB-C Mobile Charger - Fast Charging |
| q063 | nl | cover to protect my scooter from rain and dust | 1.00 | 1.00 | 1.00 | Cover | good | RohanRide Universal Fit Blue Bike Body Cover - Waterpro |
| q064 | nl | keep my car smelling fresh | 1.00 | 1.00 | 1.00 | Car | good | SavviRide Car Perfume for Men - Black - Lemon Fragrance |
| q065 | nl | oil for cooking | 1.00 | 1.00 | 1.00 |  | good | DishaDhaba 5 Litre Refined Sunflower Oil for Veg Diet / |
| q066 | nl | camera that records the road while driving | 1.00 | 1.00 | 1.00 | Dash Cameras | good | RohanRide 1080p Car Black Dash Cam for Safe Car Driving |

<!-- M3:BEGIN -->

## M3 — chat search

- Date: 2026-10-11 00:01 UTC · 25 conversations, 71 turns (`eval/conversations.jsonl`, marked needs_review)
- Chat model: see docker-compose.yml / FINDARO_CHAT_MODEL · judge: ollama:llama3.1:8b

| Target / metric | Result | |
|---|---|---|
| results event p95 ≤ 150 ms (rules path, client-measured) | 59 ms (n=57) | ✅ met |
| small-talk turns answered conversationally (results wait for one chat-LLM call) | 4 (results p50 1294 ms) | |
| first text token p95 ≤ 1200 ms | 6434 ms (p50 4205, n=68) | ❌ missed |
| first *model* token p95, server-side (before sentence checking) | 5948 ms (p50 3441) | |
| turn type accuracy | 97% (69/71) | |
| plan-assertion pass rate | 97% (36/37) | |
| per-turn nDCG@10 | 0.969 (n=57; turn 1 1.000, turn 2 0.954, turn 3+ 0.942) | |
| clarifier precision / recall (labelled turns) | 100% / 75% (asked on 8/71 turns; 0 where the label says don't ask) | |
| groundedness | not judged | |
| numeric errors = 0 (numbers not in any shown product's fields) | 0 (judge-flagged numeric claims: 0; sentences dropped by the slot checker: 89) | ✅ met |
| answers written by the model (rest: fallback when every sentence was dropped, or templates) | 54/71 (fallback 15) | |
| clarifier rate | 8/71 turns (11%) | |
| out-of-catalog chats: match_quality | good 2, none 4, weak 14 (none/weak 18/20; target ≥ 15) | ✅ met |

### Turn-type and plan failures

| conv | turn | user | expected | got | understood |
|---|---:|---|---|---|---|
| c18 | 2 | masala chai wali | refine | new | Spices & Masalas or Garam Masala, Tea |
| c20 | 2 | type c wala | refine | new |  |

### Out-of-catalog queries in chat

| query | match_quality | clarifier | answer |
|---|---|---|---|
| refrigerator | weak | Popular categories: | Sorry, we don't sell refrigerators. We have a wide range of home and kitchen products, including cookware, kit |
| washing machine | good | Which kind are you looking for? | The search results for "washing machine" are not relevant to the products listed, which are all clothing items |
| football | none | Popular categories: | We don't sell sports equipment, but we have a wide range of casual and formal wear that you might be intereste |
| lipstick | none | Popular categories: | We don't sell cosmetics, but we have a wide range of products for your daily needs. What are you shopping for  |
| gold necklace | weak | I couldn't find an exact match. Is one of these close? | No exact match. Closest: [FW-00169] |
| baby diapers | weak | Popular categories: | We don't sell baby diapers, but we have a wide range of products for kids and babies. What are you looking for |
| dog food | weak | Popular categories: | Sorry, we don't sell dog food. We're an online store that specializes in clothing, footwear, home and kitchen  |
| printer ink cartridge | weak | Popular categories: | Sorry, we don't sell printer ink cartridges. We do sell a variety of electronics accessories, though. Would yo |
| sofa set | weak | Popular categories: | We don't sell furniture, but we have a wide range of home decor items. What are you looking for today? |
| guitar strings | none | Popular categories: | Sorry, we don't sell musical instruments or accessories, but we have a wide range of products for various need |
| badminton racket | weak | Popular categories: | We don't sell sports equipment, but we have a variety of products for different needs. |
| face wash | weak | Popular categories: | We don't sell personal care products, but we have a wide range of household essentials and grocery items. |
| umbrella | none | Popular categories: | We don't sell umbrellas, but we have a wide range of products for your daily needs. What are you shopping for  |
| wrist watch | weak | Popular categories: | We don't sell wrist watches, but we have a wide range of mobile accessories, including phone cases and covers, |
| school textbooks | weak | Popular categories: | We don't sell school textbooks, but we have a wide range of products for kids, including school shoes and appa |
| ceiling fan | weak | Popular categories: | We don't sell ceiling fans, but we have a wide range of home appliances and kitchen essentials. |
| yoga mat | weak | Popular categories: | We don't have yoga mats in our collection, but we have a wide range of products for your daily needs. What are |
| sunglasses | weak | Popular categories: | We don't have sunglasses in our store. We have a wide range of products, including footwear, apparel, electron |
| aata chakki machine | weak | Exact match nahi mila. Inme se kuch chahiye? | Sorry bhai, search results not exactly match "aata chakki machine". 

 |
| laptop | good | Which kind are you looking for? | The DigiCraft Brown Laptop Bag [EL-00380] is in stock. The lowest priced laptop bag is [EL-00190] at ₹699. |

### All turns

| conv | turn | user | type | understood | nDCG | clarifier | results ms | first token ms | answer |
|---|---:|---|---|---|---:|---|---:|---:|---|
| c01 | 1 | running shoes for men | new | Men, Running Shoes | 1.00 |  | 40 | 3902 | The cheapest running shoes for men are [FW-00201] with a price of ₹799. The most expensive running s |
| c01 | 2 | cheaper ones | refine | Men, Under ₹2,199, Running Shoes, Lower prices first | 1.00 |  | 35 | 4288 | Top result: [FW-00201] |
| c01 | 3 | only black | refine | Men, Under ₹2,199, Black, Running Shoes, Lower prices first | 0.71 |  | 40 | 5504 | The products that match the search criteria "only black" are [FW-00181], [FW-00461], [FW-00302], [FW |
| c01 | 4 | is the second one lace-up? | question |  |  |  | 12 | 6730 | Yes, the second one, [FW-00181], is a lace-up running shoe. |
| c02 | 1 | ladies ke liye kurti chahiye | new | Women | 1.00 |  | 30 | 4288 |  [AP-00186] aur [AP-00256] dono mustard rang ke hain. [AP-00186] georgette material se banaya gaya h |
| c02 | 2 | 500 ke andar | refine | Women, Under ₹500 | 0.92 |  | 27 | 5313 | Sabse upar: [AP-00406] |
| c02 | 3 | pink nahi chahiye | refine | Women, Under ₹500, Not Pink | 0.83 |  | 59 | 4370 | Kaviya Kraft Women's Kurti / Maroon / Cotton / Full Sleeve / Print [AP-00406] is not pink, but its c |
| c03 | 1 | pressure cooker | new | Pressure Cookers | 1.00 |  | 22 | 5644 | Top result: [HK-00451] |
| c03 | 2 | a bigger one | refine | 7.5 L, Pressure Cookers | 1.00 |  | 37 | 4205 |  [HK-00231] is also the cheapest option. |
| c03 | 3 | which is the cheapest? | question |  |  |  | 4 | 6406 | The cheapest option is [HK-00231] with a price of 1099 INR. |
| c04 | 1 | saree under rs 1000 | new | Under ₹1,000, Sarees | 1.00 | Only 1 match under ₹1,000. Want to see options slightly over budget? | 38 | 4154 | Top result: [AP-00437] |
| c04 | 2 | Show slightly over budget | refine | Under ₹1,300, Sarees | 0.73 |  | 24 | 2017 | The lowest priced saree is [AP-00437] priced at ₹899. The highest priced saree is [AP-00277] priced  |
| c05 | 1 | shoes | new | Shoes | 1.00 |  | 34 | 3173 | The Sohum Kids White School Shoes [FW-00380] is a product for kids, available in white color. The lo |
| c05 | 2 | Running Shoes | refine | Running Shoes | 1.00 |  | 23 | 3648 | The Sohum White Synthetic Running Shoes for Men [FW-00101] is in stock. The Anantara Men's White Run |
| c05 | 3 | under 1500 | refine | Running Shoes, Under ₹1,500 | 0.98 |  | 19 | 3665 | The Sohum Men's Blue Running Shoes [FW-00011] is the cheapest option at ₹549. |
| c06 | 1 | water bottle | new | Water Bottles | 1.00 |  | 35 | 4575 | Top result: [HK-00267] |
| c06 | 2 | not plastic | refine | Not Plastic, Water Bottles | 1.00 |  | 26 | 6213 | The following water bottles are made of non-plastic materials: [HK-00267] is a copper water bottle,  |
| c06 | 3 | only copper | refine | Not Plastic, Copper, Water Bottles | 1.00 |  | 25 | 5061 | The following copper water bottles are available: [HK-00267], [HK-00167], [HK-00087], [HK-00137], [H |
| c07 | 1 | bluetooth earbuds | new | Bluetooth Earbuds | 1.00 |  | 33 | 3644 | The DigiCraft Blue Bluetooth Earbuds [EL-00156] are in stock and have a playback of 24 hours. The Sp |
| c07 | 2 | aur sasta | refine | Under ₹1,949, Bluetooth Earbuds, Lower prices first | 1.00 |  | 80 | 4044 | Aur sasta Bluetooth Earbuds, Lower prices first. Lowest price wala product [EL-00486] hai, jiska pri |
| c07 | 3 | sabse sasta kaunsa hai? | question |  |  |  | 12 | 6171 | Sabse sasta [EL-00486] hai, 899 rupaye mein. |
| c08 | 1 | power bank | new | Power Banks | 1.00 |  | 45 | 3604 | The Sparkzen High Capacity Black Power Bank [EL-00143] is in stock and has a rating of 3.7. The Conn |
| c08 | 2 | 20000mAh only | refine | 20000mAh, Power Banks | 1.00 |  | 25 | 4298 | [EL-00243] Connecta Power Bank, 
[EL-00283] DigiCraft Power Bank, 
[EL-00193] Proxima Power Bank, 
[ |
| c08 | 3 | does the first one support fast charging? | question |  |  |  | 12 | 7239 | The listing for [EL-00243] mentions that the power bank has a wattage of "10W", but it doesn't speci |
| c09 | 1 | sarson ka tel | new | Mustard Oil | 1.00 |  | 34 | 3885 | AashirvaadAvenue Mustard Oil [GR-00017] is available. DishaDhaba Mustard Oil [GR-00182] is the cheap |
| c09 | 2 | 5 L wala | refine | 5 L, Mustard Oil | 1.00 |  | 40 | 3498 | DishaDhaba Mustard Oil [GR-00182] 5 L wala hai aur yeh cold pressed hai. NirvanaNourish Mustard Oil  |
| c10 | 1 | hi | chitchat |  |  | Popular categories: | 6 | 6 | Hi! What are you shopping for today? Pick a category below, or just tell me what you need. |
| c10 | 2 | I need a helmet for my bike | new | Helmets, Bike | 1.00 |  | 21 | 5011 | Top result: [AU-00288] |
| c10 | 3 | full face | refine | Full Face, Helmets, Bike | 1.00 |  | 23 | 3846 | The KritiCraze Red Fibreglass Full Face Bike Helmet for Men - Large - Bike Helmet is the cheapest op |
| c10 | 4 | thanks! | chitchat |  |  |  | 7 | 7 | Happy to help! Want to refine these, or look for something else? |
| c11 | 1 | gents chappal | new | Men, Kolhapuri Chappals | 1.00 |  | 23 | 3872 | Arre bhai, maine dekha hai ki aapko gents chappal chahiye. Main aapko kuch options de raha hoon:



 |
| c11 | 2 | brown wala | refine | Men, Brown, Kolhapuri Chappals | 1.00 |  | 37 | 4490 |  [FW-00274] ki price ₹699 hai. [FW-00284] ki rating 4 hai. [FW-00274] in stock hai. |
| c12 | 1 | t-shirt for men | new | Men, T-Shirts or T-Shirts | 1.00 |  | 39 | 3223 | 
The first product, [AP-00461], is a Brown Cotton T-Shirt for Men from Ragamaya, priced at ₹799.

Th |
| c12 | 2 | oversized | refine | Men, Oversized, T-Shirts or T-Shirts | 1.00 |  | 22 | 4541 | Ragamaya Men's Oversized Cotton Striped Full Sleeve T-Shirt for Men - Brown [AP-00461] 
Prayaan Deni |
| c12 | 3 | under 500 | refine | Men, Oversized, Under ₹500, T-Shirts or T-Shirts | 0.85 |  | 47 | 2980 |  The lowest price is [AP-00451] at ₹249. |
| c13 | 1 | khana banane ke bartan | new | Cookware | 1.00 | Kaunsa type chahiye? | 40 | 3578 | Aapke khana banane ke bartan ke liye yeh products milte hain:

 Aahwan L Silver Aluminium Pressure C |
| c13 | 2 | Kadai | refine | Kadai | 1.00 |  | 36 | 4099 | The Kalyaniware Black Iron Kadai for Cooking [HK-00173] is in stock. |
| c13 | 3 | lohe ki | refine | Kadai, Iron | 1.00 |  | 36 | 3902 | Kalyaniware Black Iron Kadai for Cooking [HK-00173] is available. |
| c14 | 1 | car seat cover | new | Car, Seat Covers | 1.00 |  | 39 | 4629 | Top result: [AU-00211] |
| c14 | 2 | leatherette | refine | Leatherette, Car, Seat Covers | 1.00 |  | 34 | 4378 | The PulsarPro Tan Custom Fit Leatherette Car Seat Cover for Car is in stock and has a custom fit. |
| c14 | 3 | what colours does the first one come in? | question |  |  |  | 10 | 6434 | The PulsarPro Tan Custom Fit Leatherette Car Seat Cover for Car comes in Tan. |
| c15 | 1 | atta | new | Atta & Flours or Whole Wheat Atta | 1.00 |  | 52 | 4940 |  The most expensive Whole Wheat Atta is [GR-00331] with a price of ₹449. |
| c15 | 2 | smaller pack | refine | 1 kg or 2 kg, Atta & Flours or Whole Wheat Atta | 1.00 |  | 31 | 5422 | The products that match your search for smaller packs of Whole Wheat Atta are [GR-00023], [GR-00177] |
| c16 | 1 | bacchon ke school ke joote | new | Kids, School Shoes | 1.00 |  | 41 | 3925 | Bachchon ke school ke jootey mil gaye hain. Sabhi jootey bachchon ke liye hai aur school ke liye. In |
| c16 | 2 | white wale | refine | Kids, White, School Shoes | 1.00 |  | 35 | 4341 | Aapke search results mein kuch achhe shoes hain. [FW-00040] aur [FW-00380] dono white, kids, aur sch |
| c16 | 3 | velcro wale? | refine | Kids, White, Velcro, School Shoes | 1.00 |  | 38 | 4385 | Aapke vichar ke anusaar, yeh sab products aapke liye upyogi ho sakte hain. 

Aapke liye sabse sasta  |
| c17 | 1 | laptop bag | new | Laptop Bags | 1.00 |  | 27 | 4296 | The Sparkzen Men's Laptop Bag [EL-00210] is a Navy Blue Polyester Laptop Bag for Men with a price of |
| c17 | 2 | for a 15.6 inch laptop | refine | 15.6 inch, Laptop Bags | 1.00 |  | 22 | 4023 | The DigiCraft Brown Laptop Bag [EL-00380] is the most expensive option at ₹1,899. |
| c17 | 3 | now show me wireless mouse | new | Wireless, Mouse | 1.00 |  | 33 | 4662 | Top result: [EL-00268] |
| c18 | 1 | chai patti | new | Tea | 1.00 |  | 27 | 3469 | Chai patti mil gayi hai! DishaDhaba Chai Patti for Men - Veg Leaf Tea [GR-00307] sabse sasta hai, pr |
| c18 | 2 | masala chai wali | new ✗ | Spices & Masalas or Garam Masala, Tea ✗ | 0.99 |  | 30 | 3611 | Arre, yeh chai masala wali products hai. |
| c18 | 3 | isme sabse badi packing kaunsi hai? | question |  |  |  | 12 | 7044 | Main iska pakka jawab nahi de paaya; upar product details mein seller ki di hui saari jaankari hai. |
| c19 | 1 | refrigerator | new |  |  | Popular categories: | 2816 | 2816 | Sorry, we don't sell refrigerators. We have a wide range of home appliances, though. search: null |
| c19 | 2 | ok what about an electric kettle | new | Electric Kettles | 1.00 |  | 30 | 4957 | Top result: [HK-00128] |
| c20 | 1 | mobile charge karne wala tar | new | Cables | 1.00 |  | 59 | 3320 | Mobile charge karne wala tar milte hain. Sabhi taron ki quality acchi hai. Sabse kam price wala tar  |
| c20 | 2 | type c wala | new ✗ |  | 0.63 | Kaunsa type chahiye? | 46 | 4919 |  PulseZone White Braided Nylon USB-C to USB-C Long Mobile Charging Cable [EL-00342] bhi hai, jismein |
| c20 | 3 | 2m lamba chahiye | refine | 2m | 1.00 |  | 39 | 4938 |  Sabse sasta cable [EL-00212] hai, jo ₹199 rupaye mein milta hai. |
| c21 | 1 | silk saree | new | Silk, Sarees | 1.00 |  | 40 | 5058 | Top result: [AP-00167] |
| c21 | 2 | red or maroon | refine | Silk, Red or Maroon, Sarees | 0.63 |  | 38 | 2474 | Top result: [AP-00347] |
| c21 | 3 | is the first one embroidered? | question |  |  |  | 10 | 2507 | I couldn't answer that reliably; the product details show everything the seller listed. |
| c22 | 1 | dal | new |  | 1.00 | Which kind are you looking for? | 31 | 4086 |  The cheapest option is [GR-00280] SampoornaStore Moong Dal. |
| c22 | 2 | Moong Dal | refine | Moong Dal | 1.00 |  | 26 | 3911 | The SampoornaStore Moong Dal [GR-00280] is the cheapest option at ₹149. The Aashirvaad Avenue Moong  |
| c22 | 3 | 1 kg | refine | Moong Dal, 1 kg | 1.00 |  | 19 | 5267 | The products that match the search criteria of "1 kg" Moong Dal are [GR-00280], [GR-00379], [GR-0041 |
| c23 | 1 | dash cam | new |  | 1.00 |  | 25 | 4760 | Top result: [AU-00127] |
| c23 | 2 | 4K only, just show | refine | 4K | 1.00 |  | 35 | 4094 |  [AU-00067] is the cheapest option at ₹2,299. |
| c23 | 3 | does it have night vision? | question |  |  |  | 8 | 5928 | Only [AU-00487] and [AU-00157] have night vision mentioned in their descriptions. |
| c24 | 1 | jeans | new | Jeans | 1.00 |  | 30 | 4191 | Top result: [AP-00283] |
| c24 | 2 | slim fit, black nahi | refine | Slim Fit, Not Black, Jeans | 1.00 |  | 33 | 3695 | 


 [AP-00343] Sparsh Clothing Grey Slim Fit Men's Jeans, which is available in the color Grey.

The |
| c25 | 1 | football | new |  |  | Popular categories: | 1150 | 1150 | We don't sell sports equipment, but we have a wide range of casual and formal footwear for men and w |
| c25 | 2 | how are you | chitchat |  |  | Popular categories: | 1294 | 1295 | I'm doing well, thank you for asking! We have a lot of great products to help you with your shopping |
| c25 | 3 | show me yoga mats | new | Storage & Containers, Container Sets |  |  | 2744 | 2744 | We don't sell yoga mats, but we have a variety of home and kitchen products, including storage solut |

### M4 re-measurement (2026-10-08): chat on local Ollama, groundedness reviewed by hand

**Setup.** OpenAI credits ran out during M4, so this run uses local `llama3.1:8b` through Ollama for answers
and unclear-turn classification. That is free, but slower and weaker than gpt-4.1-mini. No paid API calls were
made. Groundedness wasn't judged by an LLM: I (Claude, the author of this system) reviewed all 68 non-chit-chat
answers by hand against the fields of the products on screen. Claim-by-claim verdicts are in
`eval/chat_review_m4.md`.

| Target | Result | |
|---|---|---|
| Groundedness ≥ 97% (every claim supported by the shown products' fields) | **66/68 = 97.1%** (48/50 model-written answers, 18/18 fallbacks) | ✅ met, just |
| 0 numeric errors | **0**: every number comes from a server-filled slot | ✅ met |
| Clarifier rate (question only for category, budget, weak match) | 8/71 turns (11%, was 19/71); recall 75%, precision 100% | |
| Negation scope ("slim fit, black nahi") | c24 nDCG 0.33 → 1.00; tests cover English and Hinglish forms | ✅ |
| Results event p95 ≤ 150 ms | 63 ms | ✅ met |
| First text token p95 ≤ 1.2 s | 6.7 s (local 8B model; the target assumed Haiku) | ❌ missed |

**How the numbers are made safe.**
- The model writes `{price:ID}`-style slots, and the server fills them from that product.
- Every sentence is checked before it streams, and dropped whole if it:
  - contains a number the model wrote itself;
  - puts a slot on a product the sentence doesn't cite;
  - names a product type that doesn't fit the cited product;
  - names an attribute value the cited product doesn't have, or another product's brand;
  - makes an uncited claim;
  - makes an "all/sabhi/both" claim that isn't true for every product it covers;
  - makes a stock claim that isn't true;
  - makes a comparison (English or Hindi) not backed by the fact computed in code.
- All checks run in code at no cost; `tests/test_slots.py` has a test for each.

**The two remaining failures** are both broad claims the checks don't parse:
- "sabhi cable ke price alag-alag hain" (every cable has a different price): three cost ₹549;
- "the products are all vegetarian and available": one is out of stock.

**Caveats.**
- *Checks built from the eval itself.* Most checks were written after reading failures on these same 25
  conversations, so 97% is a dev-set number. Expect lower on new conversations.
- *Fallbacks.* 18 of 68 answers are the plain fallback ("Top result: [ID]"), used when every sentence the 8B model
  wrote was dropped. They're grounded, but not helpful.
- *Not independent.* The reviewer is the system's author. The per-answer file exists so a person can spot-check it.
- *The conversations are still `needs_review`.*

<!-- M3:END -->
