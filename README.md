# zerch

Open-source AI search as a service. Push your catalog as JSON or CSV and call one search endpoint.
You get hybrid retrieval (BM25 + multilingual vectors), typo tolerance, Hinglish-friendly matching, filters,
facets and highlighting. You don't need to define a schema: zerch infers field roles from your data.

Status: **M1 (core)**. Query understanding (M2), chat search (M3) and a JS SDK (M4) come next; see `CLAUDE.md`.
License: Apache-2.0.

## 5-minute quickstart

Requirements: Docker with about 4 GB of memory for containers, plus `curl` and `jq`.

```bash
git clone <this repo> zerch && cd zerch
docker compose up -d --build        # API on :8000, plus worker, OpenSearch, Postgres, Redis
curl -s localhost:8000/healthz      # {"status":"ok"} once the API is up (the first build takes a few minutes)
```

**1. Create a project.** The response contains two keys. The `admin_key` manages data, so keep it on the server.
The `search_key` can only search, so it is safe to use in browsers.

```bash
curl -s -X POST localhost:8000/v1/projects -H 'content-type: application/json' -d '{"name":"demo"}' | tee project.json
PID=$(jq -r .project_id project.json); ADMIN=$(jq -r .admin_key project.json); SEARCH=$(jq -r .search_key project.json)
```

**2. Import the demo catalog** (3,000 synthetic Indian e-commerce products). The import runs as an async job:

```bash
curl -s -X POST localhost:8000/v1/projects/$PID/import -H "authorization: Bearer $ADMIN" \
  -F file=@data/demo_catalog.jsonl | tee job.json
curl -s localhost:8000$(jq -r .status_url job.json) -H "authorization: Bearer $ADMIN" | jq '{status, succeeded, failed}'
```

Repeat the status call until `status` is `succeeded`. It takes about 30 seconds, most of it spent embedding.

**3. Look at the inferred schema:**

```bash
curl -s localhost:8000/v1/projects/$PID/schema -H "authorization: Bearer $ADMIN" | jq -c '.schema.fields[] | {name, role}'
```

**4. Search:**

```bash
curl -s -X POST localhost:8000/v1/search -H "authorization: Bearer $SEARCH" -H 'content-type: application/json' \
  -d '{"query": "black running shoes", "filters": {"price": {"lte": 1500}}, "size": 5}' \
  | jq '{total, hits: [.hits[] | {id, title: .document.title, price: .document.price}], colors: .facets.color.values[:5]}'

# typos, Hinglish, Devanagari
curl -s -X POST localhost:8000/v1/search -H "authorization: Bearer $SEARCH" -H 'content-type: application/json' \
  -d '{"query": "presure coker"}' | jq '[.hits[:3][].document.title]'
curl -s -X POST localhost:8000/v1/search -H "authorization: Bearer $SEARCH" -H 'content-type: application/json' \
  -d '{"query": "kapde rakhne wala bag"}' | jq '[.hits[:3][].document.title]'
```

## API

All endpoints take `Authorization: Bearer <key>`. The `X-Zerch-Key: <key>` header works too.

| Method | Path | Key | |
|---|---|---|---|
| POST | `/v1/projects` | bootstrap token, if `ZERCH_BOOTSTRAP_TOKEN` is set | → `project_id`, `admin_key`, `search_key` |
| GET / DELETE | `/v1/projects/{id}` | admin | project info (document count, schema state) / delete everything |
| POST | `/v1/projects/{id}/documents` | admin | JSON array (or `{"documents": [...]}`); upserts by id; up to 10k per request → job |
| POST | `/v1/projects/{id}/import` | admin | multipart `file` in `.csv`, `.jsonl` or `.json` format, up to 50 MB → job |
| DELETE | `/v1/projects/{id}/documents/{doc_id}` | admin | → job |
| POST | `/v1/projects/{id}/documents/delete` | admin | `{"ids": [...]}` → job |
| GET | `/v1/projects/{id}/documents/{doc_id}` | admin | stored document |
| GET | `/v1/projects/{id}/jobs[/{job_id}]` | admin | job status: `queued`, `running`, `succeeded`, `completed_with_errors` or `failed`, plus row errors |
| GET / PUT | `/v1/projects/{id}/schema` | admin | view or override field roles. PUT starts a background reindex. |
| POST | `/v1/search` | search or admin | see below |

### Search

```json
{
  "query": "cotton kurta",
  "filters": {
    "color": ["White", "Cream"],
    "brand": {"not": "Acme"},
    "price": {"gte": 300, "lte": 1500},
    "category": "Apparel > Men",
    "in_stock": true
  },
  "sort": "price:asc",
  "page": 1, "size": 20,
  "facets": ["color", "brand", "price"],
  "highlight": true
}
```

Filter rules:
- String filters are case-insensitive.
- A list matches any of its values.
- A category filter matches that path and everything below it.
- `sort` accepts `"field:asc"`, `"-field"`, or `[{"field": ..., "order": ...}]`. Leave it out to sort by relevance.

The response contains `total`, `hits[]` (`id`, `score`, `document`, `highlights`) and `facets`. Facets are
term counts for facet, category and boolean fields, and min/max stats for numeric fields. The response also has
`took_ms` and `cached`. Results are cached in Redis for 60 s per data version. Send `Cache-Control: no-cache` to
bypass the cache. Each key is limited to 50 requests per second (`ZERCH_RATE_LIMIT_PER_SECOND`).

### Schema roles

On first ingest, zerch infers one role per field from the field names and value statistics. Fields that first
appear in later ingests are added automatically.

| role | indexed as | used for |
|---|---|---|
| `id` | keyword | upsert key, exact lookup |
| `title`, `description`, `text` | analysed text (weights 3 / 1 / 0.5) | search, highlighting, embeddings |
| `facet` | keyword + text | search, filters, facet counts (low-cardinality strings, `;`-lists in CSV) |
| `keyword` | keyword + text | search and filters, no facet counts (high-cardinality short strings) |
| `numeric`, `price` | double | range filters, sorting, min/max stats |
| `currency` | keyword | filters |
| `category` | path + prefixes | hierarchical filter and facets (`A > B > C`, `A / B`) |
| `boolean` | boolean | filters, facets |
| `image_url`, `url`, `ignore` | not indexed | returned in documents |

To override the inferred roles, send `PUT /schema` with the same `fields` list that GET returns. Each entry can set
`role`, `weight`, `searchable`, `filterable`, `facet` and `sortable`. The change is applied by a reindex into a
new index, followed by an atomic alias swap. Search keeps working throughout.

## How retrieval works

- **Lexical (BM25):** a cross-field match over all searchable fields, a fuzzy match (`AUTO` edit distance) on a
  catch-all field, a title phrase boost, and an exact id lookup. Analysis uses an ICU tokenizer and
  Devanagari→Latin transliteration, so `जूते` matches `joote`. It also applies a light English stemmer and
  removes English and romanised-Hindi filler words such as `ke`, `wala` and `ke liye`.
- **Phonetic subfield:** at low weight, normalises romanised Hindi spelling variants, so joota, juta and jootey
  match each other, and so do chappal and chapal.
- **Vector:** `intfloat/multilingual-e5-small` embeddings run locally on CPU and are searched with HNSW on
  OpenSearch's Lucene engine. The vector search uses the same filters.
- **Fusion:** Reciprocal Rank Fusion (k=60) over the top 100 results from each retriever. Vector candidates
  scoring well below the best vector hit are dropped, so `total`, facets and sorted results reflect real matches.

## Development

```bash
uv sync
docker compose up -d postgres opensearch redis
uv run pytest                                 # integration tests use their own DB/index prefix and a hash embedder
uv run uvicorn zerch.main:app --reload        # API on the host (ZERCH_* env vars, see src/zerch/config.py)
uv run python -m zerch.worker                 # ingest worker
```

Run a single worker in M1. Jobs for a project run in order.

### Demo data and evaluation

- `scripts/gen_demo_catalog.py` regenerates `data/demo_catalog.jsonl` and `.csv`. It needs Ollama (`llama3.1:8b`)
  or `--provider anthropic` with `ZERCH_ANTHROPIC_API_KEY`. Structured attributes are sampled from a
  taxonomy, and the LLM writes the brand names, titles and descriptions. All brands are invented, and nothing in
  the repo is scraped.
- `eval/build_queries.py` builds `eval/queries.jsonl`. Each query's relevant ids come from a predicate over the
  catalog's attributes.
- `uv run python eval/run.py --setup` imports the catalog into a new project, then writes `eval/report.md` with
  nDCG@10, recall@20, the zero-result rate and latency. That report is the **M1 baseline** that M2 must beat.
- `uv run python scripts/bench.py` runs the 10k-document latency benchmark and writes `eval/latency_10k.md`.
