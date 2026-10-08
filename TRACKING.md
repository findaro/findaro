# Tracking

Notion MCP was not authorised in the session, so tracking lives here.

| Item | Session | Status |
|---|---|---|
| AI search SaaS: M1 | Claude Code: ai-search M1 | Done (eval queries reviewed 2026-10-07) |
| AI search SaaS: M2 | Claude Code: ai-search M2 | Done (holdout: nDCG@10 0.818, written by gpt-5.5) |
| AI search SaaS: M3 | Claude Code: ai-search M3 | Waiting on Rohit (review eval/conversations.jsonl) |

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

## M3 status (2026-10-08)

Gate not passed: `ZERCH_ANTHROPIC_API_KEY` is not set (only `OPENAI_API_KEY` is in `.env`). Per the M3 brief,
work stopped before starting. Holdout step from the gate is done: M2 on `eval/holdout.jsonl` = nDCG@10 0.818
(M1 0.540), recorded in eval/report.md.

Waiting on Rohit: an Anthropic key, or approval to run M3 on an OpenAI model instead of claude-haiku-4-5.
Update: Rohit approved running M3 on an OpenAI model instead of claude-haiku-4-5. M3 in progress.

## M3 done (2026-10-08)

/v1/chat streams session/plan/results/clarify/text/done. Targets: results p95 24 ms (≤150), first token p95
~1.1 s (≤1.2 s) on gpt-4.1-mini, out-of-catalog none/weak 18/20 (≥15). Turn type 99%, plan assertions 97%,
per-turn nDCG@10 0.935, clarifier P/R 100%/75%, groundedness 90% (gpt-5.5 judge). Details in eval/report.md (M3).

Waiting on Rohit: review the 25 conversations (`eval/conversations.jsonl`, needs_review) and whether
attribute clarifiers on bare queries ("Any preference for color?") are wanted.
