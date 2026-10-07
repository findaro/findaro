# zerch — AI search as a service

Read this first. It is the source of truth for scope and rules across sessions.

## Product

Developers connect their catalog, call one API (or drop in a JS widget), and get AI search:
natural-language queries, Indian-English/Hinglish understanding, filters inferred from the query,
and later a chat-style refinement mode. Open source (Apache-2.0) from day one; hosted service later.

## Milestones

| | Milestone | Status |
|---|---|---|
| **M1** | Core: projects/keys, ingestion, schema inference, hybrid search, demo catalog, eval baseline | in progress |
| M2 | AI query understanding (filters/price/attributes inferred from the query, Hinglish normalisation) | not started |
| M3 | Chat search (conversational refinement over the M2 query representation) | not started |
| M4 | JS SDK / drop-in widget (uses the browser-safe `search_key`) | not started |

Do not build M2–M4 early, but do not make choices that block them:
- Search request/response shapes are versioned (`/v1`) and additive. M2 will add a parsed-query
  representation that compiles to the same `filters`/`sort` structure M1 accepts.
- The LLM provider interface (`zerch.llm`) exists in M1 but is **not** used in the search hot path.
- `search_key` is browser-safe (read-only, search only, CORS allowed) so M4 can ship without changes.
- `eval/` is the gate: M2 must beat `eval/report.md` (the M1 baseline).

## Stack

- Python 3.12, FastAPI, uv (`uv sync`, `uv run ...`)
- OpenSearch 3.x (hybrid: BM25 + k-NN, fused with RRF in the app); custom image adds `analysis-icu`
- Postgres: projects, keys (hashed), schemas, ingest jobs + payloads
- Redis: search/embedding cache, per-key rate limit
- Embeddings: local `intfloat/multilingual-e5-small` behind `zerch.embeddings.Embedder`
- LLM: `zerch.llm` provider interface (Ollama + Anthropic). Used by scripts only in M1.
- docker compose for everything: `docker compose up -d --build`

## Rules

- **Engine code is domain-agnostic; no hardcoded verticals.** Nothing under `src/zerch/` may
  mention products, shoes, prices-in-INR, categories of any specific catalog, etc. Field roles
  (title, price, facet, category...) are inferred from data and overridable via the schema API.
  Vertical knowledge lives only in `scripts/`, `data/`, `eval/` (demo material).
  Language-level resources (stopwords, Hinglish spelling normalisation) are allowed; they are not verticals.
- No real scraped data anywhere in the repo. Demo data is synthetic (`scripts/gen_demo_catalog.py`).
- Apache-2.0. Don't add dependencies with incompatible licenses.
- Keep the search hot path free of network calls other than OpenSearch/Redis (target p95 < 100ms @ 10k docs).

## Layout

- `src/zerch/` — service (`api/`, `index/`, `search/`, `ingest/`, `schema/`, `embeddings/`, `llm/`)
- `src/zerch/worker.py` — ingest job worker (separate compose service)
- `scripts/` — demo catalog generator, benchmark
- `data/` — generated demo catalog (committed)
- `eval/` — queries, runner, report (baseline)
- `tests/` — pytest; needs compose services up (`docker compose up -d postgres opensearch redis`)

## Out of scope (M1)

Query understanding/LLM in search path, chat, JS SDK, autocomplete, recommendations, personalization,
analytics, dashboard/UI, user accounts, billing, rate limiting beyond a simple per-key limit,
DB/Shopify connectors, image/voice search, deployment/cloud infra, multi-region.

## Tracking

Notion Global Todo row "AI search SaaS: M1" (session "Claude Code: ai-search M1") if the Notion MCP is
authorised; otherwise `TRACKING.md` in this repo.
