# Contributing to findaro

Thanks for your interest! Bug reports, docs fixes, language-pack improvements and code are all welcome. For
anything larger than a small fix, please open an issue first so we can agree on the approach.

## Development setup

You need Docker (about 4 GB of memory for containers), [uv](https://docs.astral.sh/uv/) with Python 3.12, and
Node.js 20 or newer. [Ollama](https://ollama.com) is optional (only for chat answers and the LLM planner).

```bash
uv sync                                          # Python deps, including dev tools (pytest, ruff)
docker compose up -d postgres opensearch redis   # backing services for tests and local dev
uv run uvicorn findaro.main:app --reload           # API on :8000 (FINDARO_* env vars, see src/findaro/config.py)
uv run python -m findaro.worker                    # ingest worker
```

Or run everything in containers with `docker compose up -d --build` (API, worker, services and the demo page on
:8080). OpenSearch uses a custom image (`docker/opensearch`) that adds the `analysis-icu` plugin.

## Checks to run before opening a PR

```bash
uv run ruff check .        # lint (line length 120)
uv run pytest              # integration tests; need postgres, opensearch and redis from compose
npm ci && npm run check    # JS: generate SDK types, typecheck, build, bundle-size budgets
npm run e2e                # Playwright (optional locally; needs the full stack: docker compose up -d --build)
```

- Tests use their own database (`findaro_test`), Redis DB 15, a separate index prefix and a deterministic hash
  embedder, so they don't touch your dev data and don't download a model. They never call a real LLM.
- **Bundle budgets** (`npm run size`): SDK ≤ 10 KB gzipped, widget including the SDK ≤ 40 KB gzipped. Zero runtime
  dependencies in both packages.
- **API changes:** if you change request or response models, regenerate the spec and types and commit both:
  `uv run python scripts/export_openapi.py && npm run gen:types`. CI fails if they are out of date.

## The eval gate

Search quality is measured, not eyeballed. `eval/` holds the query sets, runners and the current report.

- Changes to retrieval, ranking or query understanding must not regress `eval/report.md` against the baseline in
  `eval/baselines/m1.json`. Run `uv run python eval/run.py --setup` with the stack up and include the before/after
  numbers in your PR.
- Never tune anything (lexicon, thresholds, prompts) on `eval/holdout.jsonl`. It exists to give an honest number.
- Chat changes: `uv run python eval/run_chat.py --search-key ...` (see `eval/README.md`).
- Eval scripts use local models by default. Don't run evals, judging or data generation against paid LLM APIs in
  shared CI or without the maintainers agreeing to it.

## Project rules

- **The engine is domain-agnostic.** Nothing under `src/findaro/` may mention a specific vertical: no products,
  shoes, INR prices or categories of any particular catalog. Field roles are inferred from data and can be
  overridden through the schema API. Vertical knowledge lives only in `scripts/`, `data/` and `eval/` (demo
  material). Language-level resources (stopwords, Hinglish spelling normalisation, `packs/locales/*.yaml`) are
  fine; they are not verticals.
- **LLMs stay off the hot path.** Search may only call the query-planner LLM conditionally, behind a timeout, with
  the rules plan as a fallback. Never add an unconditional LLM or network call to search (target p95 < 100 ms at
  10k documents).
- **Contracts change additively.** `/v1` request and response shapes, the `understood` block and the chat SSE
  event sequence are what the SDK and widget build on.
- **Chat answers stay grounded.** Numbers come from server-filled slots and every sentence is checked before it
  streams; see the Chat section of the README.
- **No real scraped data.** Demo data is synthetic (`scripts/gen_demo_catalog.py`, `scripts/enrich_demo_catalog.py`)
  with invented brands. Don't commit real catalogs, customer data or query logs.
- **Licensing.** findaro is Apache-2.0. Only add dependencies with compatible licenses (no GPL/AGPL), and keep the JS
  packages free of runtime dependencies.

## Pull requests

1. Fork, create a branch, make your change with tests.
2. Run the checks above. Keep commits focused; we use [Conventional Commits](https://www.conventionalcommits.org/)
   style messages (`feat:`, `fix:`, `docs:`, ...).
3. Open a PR and fill in the template. CI must pass.

No CLA or DCO sign-off is required. By submitting a contribution you agree that it is licensed under the
project's Apache-2.0 license (section 5 of the license).

Please follow the [Code of Conduct](CODE_OF_CONDUCT.md). For security issues, see [SECURITY.md](SECURITY.md)
instead of opening a public issue.
