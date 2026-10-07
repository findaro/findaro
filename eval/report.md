# Eval report — M1 baseline

- Date: 2026-10-07 20:22 UTC · commit `26e8d41`
- Catalog: `data/demo_catalog.jsonl` (3000 docs) · 66 queries (`eval/queries.jsonl`)
- Machine: arm64 Darwin · API at http://localhost:8000
- Retrieval: BM25 (cross-field + fuzzy + phonetic) ∥ k-NN (multilingual-e5-small), RRF fusion. No query understanding (M2).

## Summary

| Segment | Queries | nDCG@10 | Recall@20 | Zero-result rate |
|---|---:|---:|---:|---:|
| **All** | 66 | **0.818** | **0.804** | 0.0% |
| plain | 10 | 1.000 | 1.000 | 0.0% |
| typo | 11 | 1.000 | 1.000 | 0.0% |
| attribute | 14 | 0.938 | 0.989 | 0.0% |
| price | 10 | 0.529 | 0.424 | 0.0% |
| hinglish | 13 | 0.556 | 0.527 | 0.0% |
| nl | 8 | 0.920 | 0.894 | 0.0% |

## Notes on this baseline

- **Where M1 is weak, and what M2 has to fix.** Price-constrained queries score 0.53 nDCG@10 and Hinglish
  queries 0.56. M1 does not parse "under 1000", "500 ke andar" or "sasta" into filters, so it ranks the right
  product type but ignores the price constraint. Hinglish words that the vector model doesn't know (`sarson ka
  tel`, `tar`, `gents chappal`) miss completely.
- **Zero-result rate is 0%** because the vector retriever always returns its nearest neighbours. Low-confidence
  queries therefore show weak results instead of an empty page. M2 should decide when to return nothing.
- **Label noise.** Ground truth comes from the generator's structured attributes, not from the LLM-written
  titles. A small fraction of titles drift: for example, 4 of 100 chargers are titled as "charging cable".
  Expect a few points of noise per query.
- **Needs review (⚑).** 21 Hinglish and natural-language queries carry `needs_review: true` in
  `eval/queries.jsonl`. Please check that each predicate matches what the query means before M2 is measured
  against them.
- Latency at 10k documents is in `eval/latency_10k.md`: server p95 10 ms with query embeddings warm, and 65 ms
  when the query embedding has to be computed (CPU e5-small inside Docker).

## Latency (uncached, sequential)

| | p50 | p95 | p99 |
|---|---:|---:|---:|
| Server `took_ms` | 5.6 ms | 9.6 ms | 15.7 ms |
| Client wall time | 7.9 ms | 12.4 ms | 24.5 ms |

330 timed requests (5 per query) at 3000 docs. See `eval/latency_10k.md` for the 10k-document benchmark (`scripts/bench.py`).

## Per query

| id | type | query | nDCG@10 | R@20 | #rel | total | top result |
|---|---|---|---:|---:|---:|---:|---|
| q001 | plain | pressure cooker | 1.00 | 1.00 | 50 | 50 | Dunedar 7.5 L Black Aluminium Pressure Cooker |
| q002 | plain | bluetooth earbuds | 1.00 | 1.00 | 50 | 54 | DigiCraft Blue Bluetooth Earbuds / 24 Hours Playback / Wireless Earbud |
| q003 | plain | kolhapuri chappals | 1.00 | 1.00 | 50 | 50 | Aadivaan Women's Tan Kolhapuri Chappals - Best Quality Kolhapuri Chapp |
| q004 | plain | car seat cover | 1.00 | 1.00 | 50 | 54 | Dhruvix Red Car Seat Cover / Velvet Universal Fit Car Seat Cover |
| q005 | plain | garam masala | 1.00 | 1.00 | 45 | 56 | SaralSpice 200g Garam Masala Powder for Veg - Garam Masala for Cooking |
| q006 | plain | desi ghee | 1.00 | 1.00 | 45 | 44 | DishaDhaba 500 ml Desi Ghee for Veg Diet - Pure Buffalo Ghee |
| q007 | plain | leggings | 1.00 | 1.00 | 50 | 52 | Ragamaya Women's White Leggings for Women, Cotton Lycra Leggings Pack  |
| q008 | plain | electric kettle | 1.00 | 1.00 | 50 | 50 | Nirvana Nest Black 1.8L 1200W Electric Kettle Plastic / Fast Boiling E |
| q009 | plain | dinner set | 1.00 | 1.00 | 50 | 50 | Aahwan Multicolor 24-Piece Stainless Steel Dinner Set / Complete Dinne |
| q010 | plain | neckband | 1.00 | 1.00 | 50 | 50 | ChargeOn Grey Neckband for Men and Women - 30 Hours Playback |
| q011 | typo | presure cooker | 1.00 | 1.00 | 50 | 67 | BhumiStore 3 L Silver Aluminium Pressure Cooker |
| q012 | typo | wirless earbuds | 1.00 | 1.00 | 50 | 105 | Fablez White Bluetooth Earbuds for Men, 50 Hours Playback, Latest Wire |
| q013 | typo | kolapuri chappal | 1.00 | 1.00 | 50 | 50 | Aadivaan Women's Tan Kolhapuri Chappals - Best Quality Kolhapuri Chapp |
| q014 | typo | car seet cover | 1.00 | 1.00 | 50 | 55 | Dhruvix Red Car Seat Cover / Velvet Universal Fit Car Seat Cover |
| q015 | typo | garam masla | 1.00 | 1.00 | 45 | 59 | SaralSpice 200g Garam Masala Powder for Veg - Garam Masala for Cooking |
| q016 | typo | bluetoth neckband | 1.00 | 1.00 | 50 | 25 | TechRush Blue Bluetooth Neckband for Music, 20 hours Playback, Blue |
| q017 | typo | basmathi rice | 1.00 | 1.00 | 46 | 46 | HariyaliHub 1 kg Basmati Rice for Daily Cooking / Long Grain Basmati R |
| q018 | typo | runing shoes | 1.00 | 1.00 | 50 | 65 | VedaVibes White Men's Running Shoes for Men / Lightweight Running Shoe |
| q019 | typo | electrik kettle | 1.00 | 1.00 | 50 | 50 | SuruchiSpace White 1.5 L Electric Kettle, Best Quality Electric Kettle |
| q020 | typo | helmat for bike | 1.00 | 1.00 | 50 | 50 | RohanRide Blue Bike Helmet / ABS Plastic Bike Helmet for Men, Open Fac |
| q021 | typo | lether formal shoes | 1.00 | 1.00 | 50 | 119 | Sohum Men's Brown Slip-On Formal Shoes / Brown Synthetic Leather Forma |
| q022 | attribute | black running shoes for men | 0.92 | 1.00 | 7 | 67 | Sohum Men's Black Black Men's Running Shoes / Black Running Shoes for  |
| q023 | attribute | white canvas sneakers men | 0.96 | 1.00 | 4 | 20 | Nirmaan Men's Casual White Canvas Sneakers for Running / Walking Shoes |
| q024 | attribute | brown formal shoes genuine leather | 0.94 | 1.00 | 5 | 35 | Sohum Men's Brown Genuine Leather Formal Shoes, for Men, UK 8 & 9 |
| q025 | attribute | 65W usb-c charger | 0.88 | 1.00 | 2 | 80 | Sparkzen White 65W USB-C Mobile Charger - Fast Charging |
| q026 | attribute | 20000mAh power bank | 1.00 | 1.00 | 17 | 51 | Connecta Power Bank 20000mAh / Connecta Black Power Bank 20000mAh for  |
| q027 | attribute | stainless steel water bottle 1 L | 0.83 | 1.00 | 5 | 72 | Aahwan Stainless Steel Water Bottle 1.5 L Silver for Office School Gym |
| q028 | attribute | cast iron tawa | 1.00 | 1.00 | 13 | 50 | SuruchiSpace Black Cast Iron Tawa / Black Cast Iron Tawa 28 cm for Ind |
| q029 | attribute | black full face helmet | 1.00 | 1.00 | 1 | 25 | NirvaanGear Black Color ABS Plastic Full Face Helmet for Bikes / M - L |
| q030 | attribute | slim fit black jeans | 0.97 | 1.00 | 2 | 37 | Duniya Style Men's Slim Fit Black Denim Jeans for Mens |
| q031 | attribute | white cotton kurta for men | 1.00 | 1.00 | 3 | 34 | Niyati Wear Men's White Cotton Printed Kurtas / Casual Wear for Men |
| q032 | attribute | red silk saree | 1.00 | 1.00 | 1 | 15 | Aaramyaa Women's Red Silk Embroidered Saree for Women / Free Size / Fe |
| q033 | attribute | kachi ghani mustard oil 1 L | 1.00 | 1.00 | 7 | 24 | DishaDhaba Mustard Oil / 1 L |
| q034 | attribute | wireless mouse | 0.64 | 0.85 | 13 | 39 | Fablez Wireless White Computer Mouse / Long Lasting White Computer Wir |
| q035 | attribute | toor dal 1 kg | 1.00 | 1.00 | 14 | 62 | Aashirvaad Avenue Toor Dal 1 kg - Best Quality Toor Dal for Daily Cook |
| q036 | price | running shoes under 1000 | 0.38 | 0.00 | 7 | 105 | Kalyanx Men's Black Running Mesh Lace-Up Sports Shoes for Running - UK |
| q037 | price | bluetooth earbuds below 1500 | 0.63 | 0.44 | 9 | 82 | Sparkzen Blue Bluetooth Earbuds / Long Lasting 40 Hours Playback / Wir |
| q038 | price | men's t-shirt under 300 | 0.47 | 0.25 | 4 | 100 | Duniya Style Grey Oversized Men's T-Shirt / Cotton Blend Print Full Sl |
| q039 | price | saree under rs 1000 | 0.65 | 0.00 | 1 | 100 | Kaalpaash Women's Purple Georgette Woven Saree for Ladies - Free Size |
| q040 | price | dash cam under 3000 | 0.48 | 0.31 | 16 | 50 | Dhruvix 2K Dash Cam for Cars - Black, Car Dash Camera, Parking Monitor |
| q041 | price | 20000mah power bank under 1500 | 0.67 | 1.00 | 8 | 50 | Connecta Power Bank 20000mAh / Connecta Black Power Bank 20000mAh for  |
| q042 | price | 5 L pressure cooker under 2000 | 0.81 | 1.00 | 1 | 100 | Dunedar 7.5 L Black Aluminium Pressure Cooker |
| q043 | price | laptop bag under 800 | 0.49 | 0.60 | 5 | 51 | DigiCraft Grey Laptop Bag for Men / 17 Inch Laptop Tote Bag, Office Sc |
| q044 | price | kurti between 500 and 1000 | 0.15 | 0.17 | 12 | 113 | Kirti Kitchen Moong Dal 500 g - Best Quality Moong Dal for Daily Cooki |
| q045 | price | car perfume under 300 | 0.55 | 0.47 | 15 | 50 | KritiCraze Jasmine Car Perfume, 100ml, Transparent, Best Car Perfume f |
| q046 | hinglish ⚑ | 500 ke andar black shoes | 0.44 | 0.25 | 23 | 132 | Anantara Men's Black Sports Running Shoes / Lightweight Walking Shoes  |
| q047 | hinglish ⚑ | kapde rakhne wala bag | 0.79 | 0.70 | 50 | 100 | Saajni Beige Non-Woven Pack of 2 Clothes Storage Organiser Bag for Hom |
| q048 | hinglish ⚑ | ladkiyon ke liye kurti | 0.94 | 0.85 | 50 | 100 | Kaviya Kraft Women's Printed Pink Rayon 3/4 Sleeve Kurti Kurta for Fes |
| q049 | hinglish ⚑ | sasta pressure cooker | 0.54 | 0.43 | 14 | 51 | BhumiStore 5 Litre Stainless Steel Pressure Cooker Black |
| q050 | hinglish ⚑ | gaadi ke liye phone stand | 1.00 | 1.00 | 50 | 100 | Veloxo Car Phone Holder / Dashboard Mount Black Plastic Phone Stand |
| q051 | hinglish ⚑ | chai patti 1 kg | 1.00 | 1.00 | 15 | 37 | AashirvaadAvenue Chai Patti / 1 kg |
| q052 | hinglish ⚑ | gents chappal | 0.00 | 0.00 | 100 | 70 | Dhanvi Women's Gold Genuine Leather Kolhapuri Chappals - Lace-Up, Comf |
| q053 | hinglish ⚑ | shaadi ke liye silk saree | 1.00 | 1.00 | 11 | 100 | Kaalpaash Maroon Silk Saree for Women, Woven, Free Size |
| q054 | hinglish ⚑ | khana banane ke bartan | 0.15 | 0.25 | 150 | 100 | ChandrakalaChoice Extra Long Grain Basmati Rice 5kg / Pure Veg Food Gr |
| q055 | hinglish ⚑ | mobile charge karne wala tar | 0.00 | 0.00 | 50 | 137 | KritiKraft Black 18W USB-C Mobile Fast Charging Cable for Mobile (Blac |
| q056 | hinglish ⚑ | sarson ka tel | 0.00 | 0.00 | 45 | 100 | Sparkzen Red Lightning Connector 2m Length Long Mobile Cable for Andro |
| q057 | hinglish ⚑ | 1000 se kam mein earbuds | 0.66 | 0.67 | 3 | 100 | KritiKraft Wireless Blue Earbuds for Men, Long Play Bluetooth Music, 2 |
| q058 | hinglish ⚑ | bacchon ke school ke joote | 0.72 | 0.70 | 50 | 100 | Aahvaan Men's Laptop Bag / Black, 14 Inch Laptop Computer Backpack for |
| q059 | nl ⚑ | something to carry water to office | 0.93 | 0.95 | 50 | 78 | Dunedar Blue Water Bottle / 1 Litre Plastic Water Bottle for Office Sc |
| q060 | nl ⚑ | shoes for jogging in the morning | 0.82 | 0.75 | 50 | 104 | Anantara Men's Black Sports Running Shoes / Lightweight Walking Shoes  |
| q061 | nl ⚑ | comfortable footwear for women under 1000 | 0.67 | 0.70 | 111 | 118 | Kalyanx Women's Pink Bellies Flats / Comfortable Walking Shoes for Wom |
| q062 | nl ⚑ | fast charger for my phone | 0.94 | 0.75 | 50 | 95 | Sparkzen 45W Black USB-C Mobile Charger - Fast Charging for All Phones |
| q063 | nl ⚑ | cover to protect my scooter from rain and dust | 1.00 | 1.00 | 50 | 84 | RohanRide Universal Fit Blue Bike Body Cover - Waterproof Bike Cover |
| q064 | nl ⚑ | keep my car smelling fresh | 1.00 | 1.00 | 50 | 50 | Veloxo Car Perfume - Jasmine Scented Car Air Freshener for Cars |
| q065 | nl ⚑ | oil for cooking | 1.00 | 1.00 | 90 | 102 | DishaDhaba 5 Litre Refined Sunflower Oil for Veg Diet / Pure Edible Oi |
| q066 | nl ⚑ | camera that records the road while driving | 1.00 | 1.00 | 50 | 50 | KavyaKraft Car Dash Cam Recorder / 1080p Video Recording, Black, Car D |

⚑ = query/predicate marked `needs_review` in `eval/queries.jsonl`.
