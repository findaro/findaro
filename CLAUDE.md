# zerch — AI search as a service

Read this first. It is the source of truth for scope and rules across sessions.

## Product

Developers connect their catalog, call one API (or drop in a JS widget), and get AI search:
natural-language queries, Indian-English/Hinglish understanding, filters inferred from the query,
a chat-style refinement mode, a headless SDK and a drop-in widget. Open source (Apache-2.0); hosted service later.

## Milestones

| | Milestone | Status |
|---|---|---|
| M1 | Core: projects/keys, ingestion, schema inference, hybrid search, demo catalog, eval baseline | done |
| M2 | AI query understanding (filters/price/attributes inferred from the query, Hinglish normalisation) | done |
| M3 | Chat search (conversational refinement over the M2 query representation) | done (conversations need review) |
| M4 | JS SDK / drop-in widget (uses the browser-safe `search_key`) | done |

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
- `/v1/chat` SSE event sequence (session, plan, results, clarify?, text*, done) and the `PatchOp` list
  (`patch`) used by chips, pills and clarifier chips. `plan_patch`/`apply` is the older form, kept working.
- Chat answers must stay grounded: the model only sees products on screen, numbers come from server-filled
  slots, comparisons are computed in code, and every sentence is checked (`zerch.chat.slots`) before it streams.
- `eval/` is the gate: changes must not regress `eval/report.md` against `eval/baselines/m1.json`.

## Stack

- Python 3.12, FastAPI, uv (`uv sync`, `uv run ...`)
- OpenSearch 3.x (hybrid: BM25 + k-NN, fused with RRF in the app); custom image adds `analysis-icu`
- Postgres: projects, keys (hashed), schemas, ingest jobs + payloads
- Redis: search/embedding cache, per-key rate limit
- Embeddings: local `intfloat/multilingual-e5-small` behind `zerch.embeddings.Embedder`
- LLM: `zerch.llm` provider interface (Ollama, Anthropic, OpenAI). Local Ollama by default for the M2 planner and
  M3 chat. Paid providers (OpenAI/Anthropic) only when explicitly set via ZERCH_CHAT_PROVIDER / ZERCH_PLANNER_PROVIDER;
  never spend paid API calls on evals, judging or data generation without asking (review eval output in-session).
- docker compose for everything: `docker compose up -d --build`

## Rules

- **Engine code is domain-agnostic; no hardcoded verticals.** Nothing under `src/zerch/` may
  mention products, shoes, prices-in-INR, categories of any specific catalog, etc. Field roles
  (title, price, facet, category...) are inferred from data and overridable via the schema API.
  Vertical knowledge lives only in `scripts/`, `data/`, `eval/` (demo material).
  Language-level resources (stopwords, Hinglish spelling normalisation, `packs/locales/*.yaml`) are allowed;
  they are not verticals. Query understanding gets catalog knowledge (colours, categories, brands) only from the
  per-project value dictionary built from the data (`zerch.understand.dictionary`).
- Eval hygiene: never tune on `eval/holdout.jsonl`. `eval/report.md` compares against `eval/baselines/m1.json`.
- No real scraped data anywhere in the repo. Demo data is synthetic (`scripts/gen_demo_catalog.py`).
- Apache-2.0. Don't add dependencies with incompatible licenses.
- Keep the search hot path free of network calls other than OpenSearch/Redis (target p95 < 100ms @ 10k docs).
  The one exception is the M2 planner LLM: conditional, timeout-bounded, cached.

## Layout

- `src/zerch/` — service (`api/`, `index/`, `search/`, `ingest/`, `schema/`, `embeddings/`, `llm/`, `understand/`,
  `chat/`)
- `packs/locales/` — language packs for query understanding (en, hi-en)
- `src/zerch/worker.py` — ingest job worker (separate compose service)
- `scripts/` — demo setup (`demo_setup.py`), chat CLI, OpenAPI export, demo catalog generator, benchmark
- `data/` — generated demo catalog (committed)
- `eval/` — queries, conversations, runners, report (see `eval/README.md`)
- `tests/` — pytest; needs compose services up (`docker compose up -d postgres opensearch redis`)
- `packages/sdk` (`@zerch/sdk`, headless TS client, types generated from `packages/sdk/openapi.json`),
  `packages/widget` (`<zerch-search>`), `examples/plain-html`, `examples/react`, `e2e/` (Playwright)
- JS budgets (enforced by `npm run size`): SDK ≤ 10 KB gz, widget incl. SDK ≤ 40 KB gz. Zero runtime deps.

## Not built yet

Autocomplete, recommendations, personalization, analytics/click tracking, admin dashboard, end-user accounts,
billing, DB/Shopify connectors, image/voice search, cloud deployment, multi-region, npm/CDN publishing.

## Tracking

Notion Global Todo (one row per milestone) if the Notion MCP is authorised; otherwise `TRACKING.md` in this repo.
