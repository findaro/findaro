# Project history

A short record of how zerch was built, milestone by milestone. Numbers come from `eval/report.md` (and the files
it links); see `eval/README.md` for how they are measured. All measurements below were taken on local models
(Ollama) unless stated otherwise.

| | Milestone | Highlights |
|---|---|---|
| M1 | Core | Projects and keys, async ingestion, schema inference, hybrid search (BM25 + k-NN, RRF), synthetic demo catalog (3,000 products), eval baseline |
| M2 | Query understanding | Prices, attributes, categories and Hinglish inferred from the query; LLM planner as a timeout-bounded fallback |
| M3 | Chat search | `/v1/chat` over SSE: conversational refinement on top of the M2 plan, clarifying chips |
| M4 | SDK and widget | `@zerch/sdk`, `<zerch-search>`, allowed origins, plan patches, OpenAPI with chat events, Playwright e2e |
| M5 | Product conversation | `product_ids` on `/v1/chat`, labeled general know-how, product drawer in the widget |

## M1: core (2026-10-08)

Stack, API, ingestion, schema inference, hybrid search, a 3,000-product synthetic catalog and the eval baseline
(`eval/baselines/m1.json`, nDCG@10 0.808 on the reviewed set; original report in `eval/report_m1.md`). Latency at
10k documents: server p95 10 ms with warm query embeddings, 65 ms with a cold embedding (`eval/latency_10k.md`).
The Hinglish and natural-language eval queries were reviewed by hand (`eval/reviews.json`).

## M2: query understanding (2026-10-08)

Rules plus locale packs plus a per-project value dictionary, with an LLM planner behind a timeout and a cache.
Added the `understood` and `debug` blocks, backfill, relaxation and `match_quality`. nDCG@10 0.808 → 0.959
(price 0.90, Hinglish 0.91); no segment regressed. Because the Hinglish lexicon was written with the eval visible,
an independent holdout (`eval/holdout.jsonl`, written by a different LLM and never tuned on) is reported
separately: nDCG@10 0.818 vs 0.540 for M1.

## M3: chat search (2026-10-08)

`/v1/chat` streams `session`, `plan`, `results`, `clarify`, `text` and `done`. Results event p95 24 ms; turn-type
accuracy 99%, plan assertions 97%, per-turn nDCG@10 0.935, clarifier precision/recall 100%/75%. The scripted
conversations (`eval/conversations.jsonl`) are still marked `needs_review`.

## M4: SDK, widget and grounded answers (2026-10-08)

Number slots filled by the server, scoped negation, a tighter clarifier policy, allowed origins, plan patches,
OpenAPI with chat events, `@zerch/sdk`, `<zerch-search>`, plain-HTML and React examples, Playwright e2e and
bundle-size budgets. Re-measured on local `llama3.1:8b` with no paid calls: groundedness 66/68 = 97.1%, 0 numeric
errors, clarifiers on 8/71 turns (hand review in `eval/chat_review_m4.md`). The first-token target was missed on
the local 8B model.

A follow-up audit added planner call caps (shared in-flight calls, at most 2 concurrent, no LLM while typing),
kept SKU-like codes away from the LLM, sanitised widget links, handled expired chat sessions and bounded request
sizes.

## M5: product conversation (2026-10-11)

Chat about one product the way a shopper asks on a product page. `product_ids` on `/v1/chat`, labeled general
know-how (`text.part = "general"`), the widget's product drawer, synthetic catalog enrichment
(`scripts/enrich_demo_catalog.py`) and new sentence checks (suitability verdicts, after-sale promises,
catalog-wide values). Hand review: 0/48 false product claims (`eval/product_chat_review_m5.md`). Search gate held
(nDCG@10 0.966).

## Conversational chat and query log (2026-10-11)

Fixes from a real demo conversation: product-type words inside compound categories ("slippers", "shoes"), price
caps from refinements like "increase it to 2000", budget clarifiers on weak matches, and full product titles
counted as citations (search nDCG@10 0.966 → 0.970). Added small talk answered by the chat model with a suggested
search, suggestion chips (`clarify.reason = "suggest"`) and the JSONL query log (`scripts/queries.py`).
