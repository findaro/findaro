## What and why

<!-- What does this change, and why? Link the issue if there is one. -->

## How it was tested

<!-- Tests added or run, manual checks. -->

## Checklist

- [ ] `uv run ruff check .` and `uv run pytest` pass
- [ ] `npm run check` passes (if JS, the API models or `openapi.json` changed)
- [ ] API model changes: `scripts/export_openapi.py` + `npm run gen:types` run and committed; `/v1` changes are additive
- [ ] Retrieval / ranking / query-understanding changes: `eval/run.py` shows no regression vs `eval/baselines/m1.json` (numbers below); nothing tuned on `eval/holdout.jsonl`
- [ ] No vertical-specific logic under `src/zerch/`; no real scraped or customer data
- [ ] No paid LLM API calls added to search, tests or evals
- [ ] Docs (README / CONTRIBUTING) updated if behaviour changed

<!-- Eval before/after (if applicable): -->
