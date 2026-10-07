# Tracking

Notion MCP was not authorised in the session, so tracking lives here.

| Item | Session | Status |
|---|---|---|
| AI search SaaS: M1 | Claude Code: ai-search M1 | Done (eval queries reviewed 2026-10-07) |
| AI search SaaS: M2 | Claude Code: ai-search M2 | Done — waiting on Rohit for holdout queries |

## M1 status (2026-10-08)

Done: stack, API, ingest, schema inference, hybrid search, demo catalog (3,000), eval baseline
(`eval/report.md`, nDCG@10 0.818), 10k latency (server p95 10 ms warm / 65 ms cold embedding), 58 tests.

Waiting on Rohit: review the 21 `needs_review` queries in `eval/queries.jsonl` (Hinglish + NL predicates).

## M2 status (2026-10-08)

Done: query understanding (rules + locale packs + per-project value dictionary + LLM planner with timeout/cache),
`understood`/`debug` API, backfill, relaxation, match_quality. eval/report.md: nDCG@10 0.808 → 0.959; price 0.90,
hinglish 0.91, no segment regressed; rules p95 ~11 ms warm (66 ms with a cold query embedding).

Waiting on Rohit:
- ~20 holdout queries in `eval/holdout.jsonl` (format in `eval/README.md`). Hinglish score is an upper bound
  until then (lexicon was written with the eval visible).
- Optional: `ZERCH_ANTHROPIC_API_KEY` to measure the planner on Claude Haiku (local llama3.2:3b times out).
