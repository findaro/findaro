# Eval

| File | What |
|---|---|
| `queries.jsonl` | Main set (66 queries). Built by `build_queries.py` from the demo catalog; relevance comes from attribute predicates. Rohit reviewed the Hinglish/NL ones (`reviews.json`). |
| `negatives.jsonl` | Out-of-catalog queries (nothing relevant exists). Used to calibrate the "no match" floor and to report how often the engine correctly says so. |
| `holdout.jsonl` | Held-out queries written by a human, **never used for tuning** (lexicon, thresholds, prompts). Reported separately when non-empty. |
| `baselines/m1.json` | Per-query M1 results on the reviewed set, the reference M2 is compared against. |
| `run.py` | Runs everything against a live API and writes `report.md`. |
| `calibrate_floor.py` | Picks `ZERCH_MATCH_FLOOR` from `queries.jsonl` + `negatives.jsonl`. |

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
