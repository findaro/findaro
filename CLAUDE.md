# findaro — AI search as a service

Read this first. It is the source of truth for scope and rules across sessions.

## Product

Developers connect their catalog, call one API (or drop in a JS widget), and get AI search:
natural-language queries, Indian-English/Hinglish understanding, filters inferred from the query,
a chat-style refinement mode, a headless SDK and a drop-in widget. Open source (Apache-2.0) at
github.com/findaro/findaro; hosted beta at https://findaro.fortwinai.com (API https://findaro-api.fortwinai.com).

## Milestones

| | Milestone | Status |
|---|---|---|
| M1 | Core: projects/keys, ingestion, schema inference, hybrid search, demo catalog, eval baseline | done |
| M2 | AI query understanding (filters/price/attributes inferred from the query, Hinglish normalisation) | done |
| M3 | Chat search (conversational refinement over the M2 query representation) | done (conversations need review) |
| M4 | JS SDK / drop-in widget (uses the browser-safe `search_key`) | done |
| M5 | Product conversation (`product_ids` on `/v1/chat`, labeled general know-how, widget product drawer) | done |
| M6 | Hosted beta: usage metering and plan limits, website and live demo, AI Mode / unified widget, deploy (single box + Cloudflare edge) | done |

## Contracts (change additively only)

- Search request/response shapes are versioned (`/v1`). The query plan compiles to the same `filters`/`sort`
  structure explicit requests use.
- The `understood` block (chips with `remove` patches, relaxations, match_quality, close_matches), `pills` and
  `display` are what the widget and SDK build on.
- The LLM is used in search only by the M2 planner, only when the rules plan can't account for some words, and
  behind a timeout with the rules plan as fallback. Never put an LLM call on the path unconditionally.
- The LLM planner is capped: identical in-flight queries share a call, at most 2 run at once, and requests with
  `llm: false` (search-as-you-type) never call it.
- `search_key` is browser-safe (read-only, search only); browser origins are checked against the project's
  `allowed_origins`; admin keys are refused from browsers.
- `/v1/chat` SSE event sequence (session, plan, results, clarify?, text*, done); `text.part` is `answer` (facts
  from the listing) or `general` (labeled know-how, never a claim about the product) and the `PatchOp` list
  (`patch`) used by chips, pills and clarifier chips. `plan_patch`/`apply` is the older form, kept working.
- Chat small talk (`done.reason` = `conversation`): one chat-LLM call, only for turns whose words name nothing in the
  catalog and whose search found no good match; its suggested search runs through the normal planner. Suggestion
  chips are `clarify` events with `reason: "suggest"` and an empty `patch` (send the label as the message).
- Chat answers must stay grounded: the model only sees products on screen, numbers come from server-filled
  slots, comparisons are computed in code, and every sentence is checked (`findaro.chat.slots`) before it streams.
- Hits carry `requirements` (met / unmet / unknown understood constraints); chat `clarify` has `reason: "next"` for
  one-click refinements; usage and limits live under `/v1/projects/{id}/usage` and the operator API
  (`/v1/operator/*`, bootstrap token only).
- `eval/` is the gate: changes must not regress `eval/report.md` against `eval/baselines/m1.json`.

## Stack

- Python 3.12, FastAPI, uv (`uv sync`, `uv run ...`)
- OpenSearch 3.x (hybrid: BM25 + k-NN, fused with RRF in the app); custom image adds `analysis-icu`
- Postgres: projects, keys (hashed), schemas, ingest jobs + payloads
- Redis: search/embedding cache, per-key rate limit
- Embeddings: local `intfloat/multilingual-e5-small` behind `findaro.embeddings.Embedder`
- LLM: `findaro.llm` provider interface (Ollama, Anthropic, OpenAI). Local Ollama by default for the M2 planner and
  M3 chat. Paid providers (OpenAI/Anthropic) only when explicitly set via FINDARO_CHAT_PROVIDER / FINDARO_PLANNER_PROVIDER;
  never spend paid API calls on evals, judging or data generation without asking (review eval output in-session).
- docker compose for everything: `docker compose up -d --build`

## Rules

- **Engine code is domain-agnostic; no hardcoded verticals.** Nothing under `src/findaro/` may
  mention products, shoes, prices-in-INR, categories of any specific catalog, etc. Field roles
  (title, price, facet, category...) are inferred from data and overridable via the schema API.
  Vertical knowledge lives only in `scripts/`, `data/`, `eval/` (demo material).
  Language-level resources (stopwords, Hinglish spelling normalisation, `packs/locales/*.yaml`) are allowed;
  they are not verticals. Query understanding gets catalog knowledge (colours, categories, brands) only from the
  per-project value dictionary built from the data (`findaro.understand.dictionary`).
- Eval hygiene: never tune on `eval/holdout.jsonl`. `eval/report.md` compares against `eval/baselines/m1.json`.
- No real scraped data anywhere in the repo. Demo data is synthetic (`scripts/gen_demo_catalog.py`).
- Apache-2.0. Don't add dependencies with incompatible licenses.
- Keep the search hot path free of network calls other than OpenSearch/Redis (target p95 < 100ms @ 10k docs).
  The one exception is the M2 planner LLM: conditional, timeout-bounded, cached.

## Layout

- `src/findaro/` — service (`api/`, `index/`, `search/`, `ingest/`, `schema/`, `embeddings/`, `llm/`, `understand/`,
  `chat/`)
- `packs/locales/` — language packs for query understanding (en, hi-en)
- `src/findaro/worker.py` — ingest job worker (separate compose service)
- `src/findaro/querylog.py` — optional JSONL query log (`FINDARO_QUERY_LOG`; compose writes `logs/queries.jsonl`, read
  with `scripts/queries.py`)
- `scripts/` — demo setup (`demo_setup.py`), chat CLI, OpenAPI export, demo catalog generator, benchmark
- `data/` — generated demo catalog (committed)
- `eval/` — queries, conversations, runners, report (see `eval/README.md`)
- `tests/` — pytest; needs compose services up (`docker compose up -d postgres opensearch redis`)
- `packages/sdk` (`@findaro/sdk`, headless TS client, types generated from `packages/sdk/openapi.json`),
  `packages/widget` (`<findaro-search>`), `examples/plain-html`, `examples/react`, `e2e/` (Playwright)
- `site/` — website and docs (static `public/`, rendered with placeholders at deploy) plus a small server for the
  request-access form (`site/server/`)
- `deploy/app-a1/` — single-box deploy (compose, Caddy, backups, demo project, site render);
  `deploy/cloudflare/` — the edge Worker in front of it
- `docs/` — milestone history (`history.md`) and the product brief
- JS budgets (enforced by `npm run size`): SDK ≤ 10 KB gz, widget incl. SDK ≤ 40 KB gz. Zero runtime deps.

## Not built yet

Autocomplete, recommendations, personalization, analytics/click tracking, admin dashboard, end-user accounts,
billing, DB/Shopify connectors, image/voice search, cloud deployment, multi-region, npm/CDN publishing.

## Tracking

Milestone history lives in `docs/history.md`; open work is tracked in GitHub issues. Session notes and personal
trackers stay out of the repo.
