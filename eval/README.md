# Eval

| File | What |
|---|---|
| `queries.jsonl` | Main set (66 queries). Built by `build_queries.py` from the demo catalog; relevance comes from attribute predicates. Rohit reviewed the Hinglish/NL ones (`reviews.json`). |
| `negatives.jsonl` | Out-of-catalog queries (nothing relevant exists). Used to calibrate the "no match" floor and to report how often the engine correctly says so. |
| `holdout.jsonl` | 20 Hinglish queries written by a different LLM (`gen_holdout.py`), which never saw the lexicon or the main set. **Never used for tuning** (lexicon, thresholds, prompts). Marked `needs_review`; replace or extend them with human-written ones. |
| `llm_queries.jsonl` | 10 queries with words the rules can't read, to exercise the LLM planner path. |
| `conversations.jsonl` | 25 scripted chat conversations (71 turns) with per-turn expectations: turn type, required/forbidden plan filters, relevance predicate, whether a clarifier should appear. Marked `needs_review`. |
| `reviews.json` | Rohit's review decisions for the Hinglish/NL queries in the main set. |
| `baselines/m1.json` | Per-query M1 results on the reviewed set, the reference later milestones are compared against. `report_m1.md` is the original M1 report. |
| `build_queries.py` | Builds `queries.jsonl` (relevant ids from predicates over the catalog, applying `reviews.json`). |
| `run.py` | Search eval against a live API; writes `report.md` (keeps the chat section). Pass the admin key to also time uncached LLM planner calls. |
| `run_chat.py` | Chat eval over `conversations.jsonl` + negatives; writes the chat section of `report.md` and every answer to `results/`. `--judge` adds an LLM groundedness judge (local Ollama by default). |
| `run_product_chat.py` | Product-conversation eval (M5): 12 demo products × 4 questions via `/v1/chat` with `product_ids`; automatic checks plus every answer saved to `results/` for hand review. Local models only. |
| `product_chat_review_m5.md` | Hand review of every answer from the M5 run (0/48 false product claims). |
| `chat_review_m4.md` | Hand review of every chat answer from the M4 run (groundedness 66/68). |
| `gen_holdout.py` | Generates holdout queries with an LLM (local Ollama by default). |
| `calibrate_floor.py` | Picks `ZERCH_MATCH_FLOOR` from `queries.jsonl` + `negatives.jsonl`. |

None of these scripts call a paid LLM API unless you pass a paid provider explicitly.

## Holdout format

One JSON object per line, same shape as `queries.jsonl` minus the generated fields:

```json
{"id": "h001", "query": "barish ke liye joote", "type": "hinglish", "predicate": {"cat": "Footwear", "material": ["Rubber", "EVA"]}}
```

- `predicate.cat`: a category path prefix (or a list of them) from `data/demo_catalog.jsonl`.
- Other keys: any catalog attribute (`color`, `material`, `gender`, `weight`, ...); a list means "any of".
- `price_max` / `price_min`: rupee bounds.
- `type`: one of `plain`, `typo`, `attribute`, `price`, `hinglish`, `nl`.

`run.py` grades holdout queries with the same predicate rules as the main set (2 = full match, 1 = right category).
