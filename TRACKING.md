# Tracking

Notion MCP was not authorised in the session, so tracking lives here.

| Item | Session | Status |
|---|---|---|
| AI search SaaS: M1 | Claude Code: ai-search M1 | Waiting on Rohit (eval queries to review) |

## M1 status (2026-10-08)

Done: stack, API, ingest, schema inference, hybrid search, demo catalog (3,000), eval baseline
(`eval/report.md`, nDCG@10 0.818), 10k latency (server p95 10 ms warm / 65 ms cold embedding), 58 tests.

Waiting on Rohit: review the 21 `needs_review` queries in `eval/queries.jsonl` (Hinglish + NL predicates).
