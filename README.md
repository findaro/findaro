# zerch

Open-source AI search as a service. Push your catalog as JSON or CSV and call one search endpoint.
You get hybrid retrieval (BM25 + multilingual vectors), typo tolerance, Hinglish-friendly matching, filters,
facets and highlighting. You don't need to define a schema: zerch infers field roles from your data.

It also understands queries ("kaale joote 1000 ke andar" becomes black shoes under ₹1,000), has a
conversational chat mode with grounded answers, and comes with a drop-in widget (`<zerch-search>`) and a headless
TypeScript SDK (`@zerch/sdk`). Everything runs locally: the AI parts use [Ollama](https://ollama.com) by default,
and paid LLM APIs are only used if you configure them.

License: Apache-2.0.

## Run the demo

**Prerequisites:**
- Docker, with about 4 GB of memory for containers;
- [uv](https://docs.astral.sh/uv/) (Python 3.12) and Node.js 20 or newer;
- [Ollama](https://ollama.com), with the two local models:

  ```bash
  ollama pull llama3.1:8b    # chat answers
  ollama pull llama3.2:3b    # query planner, for words the rules can't read
  ```

  Without Ollama, search still works fully and chat answers fall back to plain one-line templates.

**Start it:**

```bash
git clone https://github.com/rohitsaini1196/zerch && cd zerch
docker compose up -d --build                    # API :8000, worker, OpenSearch, Postgres, Redis, demo page :8080
npm install && npm run build                    # builds the SDK and the widget
uv run python scripts/demo_setup.py             # waits for the API, imports the demo catalog, warms the models
```

Open http://localhost:8080/demo.html. Things to try:
- Search: `kaale joote 1000 ke andar`, then remove the "Black" chip;
- Search: `presure coker` (typo), `sarson ka tel` (Hinglish), or `guitar strings` (nothing matches, said honestly);
- Ask AI: `saree under 1000`, then tap "Show slightly over budget";
- Ask AI: `running shoes for men`, then `only black`, then `is the second one lace-up?`.

The first build takes a few minutes. Chat answers take a few seconds on the local 8B model.

## Integrate in 5 minutes (script tag)

1. Create a project and import your catalog (see the API quickstart below), and keep the **search key**. It's
   browser-safe: read-only, search and chat only.
2. Allow your site's origin. localhost always works (`ZERCH_ALLOW_LOCALHOST_ORIGINS=false` turns that off for
   production).

   ```bash
   curl -X PUT localhost:8000/v1/projects/$PID/settings -H "authorization: Bearer $ADMIN" \
     -H 'content-type: application/json' -d '{"allowed_origins": ["https://shop.example.com"]}'
   ```
3. Add one script tag and one element to any page:

   ```html
   <script src="zerch-widget.js" data-project="prj_…" data-key="zk_search_…" data-base-url="https://api.example.com" defer></script>
   <zerch-search></zerch-search>
   ```

Build the widget with `npm install && npm run build`; the file is `packages/widget/dist/zerch-widget.js`, 7.9 KB
gzipped with the SDK included. It gives you:
- one search box with a **Search / Ask AI** toggle;
- understood chips ("Under ₹1,000", "Black") that can be removed;
- facet pills for refining, behind a "Filters" button;
- a product grid (image, title, price, rating);
- an AI panel with a streamed answer, inline product cards for the products it cites, clarifier chips (such as
  "Show slightly over budget"), and a clear no-match state.

The demo page above is `examples/plain-html/index.html` with the demo project's keys filled in.

**Customise:**

```html
<style>
  zerch-search { --zerch-accent: #2563eb; --zerch-radius: 6px; --zerch-font: Inter, sans-serif; --zerch-card-min: 180px; }
</style>
<zerch-search locale="hi-en" mode="ai" size="24"></zerch-search>
<script>
  const el = document.querySelector("zerch-search");
  el.onProductClick = (hit) => location.assign(`/p/${hit.id}`);               // replaces opening the product URL
  el.renderProduct = (hit, { display, formatPrice }) => {                     // your own card: return an element
    const card = document.createElement("div");                              // (textContent keeps catalog data safe;
    card.className = "my-card";                                               // if you return an HTML string,
    card.textContent = `${hit.document[display.title]} · ${formatPrice(hit.document[display.price])}`;
    return card;                                                              // escape document fields yourself)
  };
  el.strings = { placeholder: "Search 10,000 products…" };                    // any UI text; locale="hi-en" for Hinglish
  el.addEventListener("zerch:results", (e) => console.log(e.detail.total));  // also zerch:product-click, zerch:error
</script>
```

- **Attributes:** `project`, `key`, `base-url` (override the script tag), `mode` (`search` | `ai`), `locale`
  (`en` | `hi-en`), `placeholder`, `size`, `theme` (`light` | `dark`; default follows `prefers-color-scheme`).
- **Behaviour:** the widget is mobile-first and keyboard accessible: the mode toggle is a radio group, Enter
  searches and Escape clears, and the conversation is an ARIA live log.
- **Safety:** product links from catalog data are only followed if they are `http(s)`. Search-as-you-type never
  calls the LLM planner; only a submitted search can.

## Headless (npm)

`@zerch/sdk` is a typed client with zero dependencies (1.5 KB gzipped, ESM + UMD). Its types are generated from
the API's OpenAPI spec (`packages/sdk/openapi.json`, regenerated by `scripts/export_openapi.py` and
`npm run gen:types`).

```ts
import { createClient, debounce } from "@zerch/sdk";

const zerch = createClient({ projectId: "prj_…", searchKey: "zk_search_…", baseUrl: "http://localhost:8000" });

const res = await zerch.search("kaale joote 1000 ke andar");          // typed SearchResponse
res.understood?.chips;  // [{ label: "Under ₹1,000", remove: [...] }, { label: "Black", remove: [...] }]
await zerch.search({ query: res.query, patch: res.understood!.chips[1].remove });   // drop "Black"

// chat: iterate events, use callbacks, or await .result
const turn = zerch.chat("sasta wala", { sessionId, onText: (_, full) => render(full) });
for await (const ev of turn) if (ev.type === "results") showProducts(ev.data.items);
const { sessionId: next, clarify } = await turn.result;

const searchAsYouType = debounce((q: string) => zerch.search(q), 250);
```

- **Cancellation:** a new `search()` (or `chat()`) cancels the client's previous in-flight one; pass
  `{ cancelPrevious: false }` to keep it.
- **Retries:** network errors are retried once.
- **Errors:** API errors throw a `ZerchError` with `status` and `code`.
- **Example:** `examples/react/` is a 40-line Vite + React app that uses only the SDK.

## 5-minute quickstart (API)

Requirements: Docker with about 4 GB of memory for containers, plus `curl` and `jq`. Ollama is optional here (see
[Run the demo](#run-the-demo)).

```bash
git clone https://github.com/rohitsaini1196/zerch && cd zerch
docker compose up -d --build        # API on :8000, plus worker, OpenSearch, Postgres, Redis
curl -s localhost:8000/healthz      # {"status":"ok"} once the API is up (the first build takes a few minutes)
```

**1. Create a project.** Set `ZERCH_BOOTSTRAP_TOKEN` on any API others can reach; otherwise anyone can create
projects (the API logs a warning). The response contains two keys. The `admin_key` manages data, so keep it on the server.
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
| PUT | `/v1/projects/{id}/settings` | admin | `{"allowed_origins": ["https://shop.example.com", "https://*.example.com"]}`: which browser origins may use the search key |
| POST | `/v1/search` | search or admin | see below |
| POST | `/v1/chat` | search or admin | Server-Sent Events, see below |
| GET | `/openapi.json` | none | OpenAPI spec, including the chat event payloads |

**Browser use:**
- Requests carrying an `Origin` header are accepted only from the project's `allowed_origins`; localhost always
  works unless `ZERCH_ALLOW_LOCALHOST_ORIGINS=false`.
- Admin keys are refused from browsers.
- Server-to-server calls, which send no `Origin`, aren't affected.

**Plan patches:** `/v1/search` and `/v1/chat` accept `patch`, a list of edits applied to the understood plan, so
a UI can change filters without a new natural-language query:
- `{"op": "remove_filter", "field": "color", "value": "Black"}`
- `{"op": "add_filter", "field": "material", "value": "Copper"}`
- `{"op": "exclude", "field": "color", "value": "Pink"}`
- `{"op": "set_price_range", "lte": 1500}` (no bounds removes the range)
- `{"op": "set_sort", "field": "price", "order": "asc"}`

Every understood chip carries its own `remove` patch, every facet pill value its `patch`, and every clarifier chip
its `patch`. Search responses also include:
- `pills`: refinement choices for the attributes that split the current results;
- `display`: which fields hold a card's title, price, image, rating and currency.

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
  "highlight": true,
  "understand": true,
  "debug": false
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

### Query understanding (`understand`, on by default)

Before retrieval, the engine turns the query into a plan built only from this project's own fields and values.
It recognises:
- **Prices**, in English and Hinglish: "under 500", "500 ke andar", "1000 se kam", "between 500 and 1000",
  "₹500-₹1000", "1.5k".
- **Quantities**: "5 L", "65W" and "500 g" are matched as quantities, never as prices.
- **Attribute values** from the catalog: colours, materials, audience, sizes, brands.
- **Category names.**
- **Cheap or premium intent**: "sasta", "premium".
- **Hinglish words**, translated through the locale packs (`packs/locales/*.yaml`).

What it understood comes back in `understood`. This field is meant for search UIs (M3 and M4 build on it):

```json
"understood": {
  "query": "500 ke andar kaale joote",
  "semantic_text": "black shoes",
  "chips": [
    {"label": "Under ₹500", "kind": "filter", "field": "price", "op": "range", "value": {"lte": 500.0},
     "source": "500 ke andar", "confidence": 0.95},
    {"label": "Black", "kind": "filter", "field": "color", "op": "eq", "value": "Black",
     "source": "black", "confidence": 0.85}
  ],
  "relaxations": [],
  "match_quality": "good",
  "source": "rules",
  "close_matches": []
}
```

- **`chips`**: what the engine applied, one chip per constraint:
  - `filter`: hard for prices; an inferred attribute instead excludes documents with a different value.
  - `boost`: ranks matching documents higher.
  - `sort`: re-ranks toward lower or higher prices while keeping relevance.

  To let a user remove a chip, send the same query again with the chip's `remove` list as `patch`. An explicit
  filter always overrides the inferred one on the same field.
- **`relaxations`**: inferred filters the engine dropped because the query returned nothing with them.
- **`match_quality`**:
  - `good`: some results match the query's words.
  - `weak`: results match on meaning only, or a filter had to be relaxed.
  - `none`: nothing relevant was found, so no results are returned instead of random neighbours.
- **`close_matches`**: ids of page-1 results that match the query but not every inferred attribute. When exact
  matches don't fill a page, close matches follow them.
- **`source`**:
  - `rules`: the fast path, used for almost every query.
  - `llm` / `cache`: the rules found words they couldn't account for, so the LLM planner rewrote the query.
  - `off`: understanding was off for this request (`understand: false`).

The planner runs on local Ollama `llama3.2:3b` by default (`ZERCH_PLANNER_MODEL`), or on Claude Haiku with
`ZERCH_PLANNER_PROVIDER=anthropic` and `ZERCH_ANTHROPIC_API_KEY` (paid; never enabled by a key alone). Its limits:
- **Time:** it waits at most `ZERCH_PLANNER_TIMEOUT_MS` (default 800) and then falls back to the rules plan. A
  late answer is still cached for the next identical query.
- **Calls:** identical queries in flight share one call, and at most 2 calls run at once, so it can't be flooded.
  Requests with `"llm": false`, which the widget sends while you type, use only the rules and cached plans.
  Codes such as SKUs and model numbers never trigger it.
- **Output:** it's validated against the schema, and it can only rewrite the text and boost results. It never adds
  filters, except a price the query states.

`"debug": true` adds the full plan, timings per stage (`understand`, `embed`, `retrieve`, `fetch`, `total`), the
planner outcome (`not_needed`, `skipped`, `busy`, `called`, `timeout`, `cache`, `error`), and the retrieval signals
behind `match_quality`. Provider error text is only included for admin keys.

### Chat (`POST /v1/chat`)

This is conversational search: refine the results over several turns, ask about the products on screen, and
pick from clarifying chips. Use the search key. The response is a stream of
[Server-Sent Events](https://developer.mozilla.org/en-US/docs/Web/API/Server-sent_events).

```bash
curl -N -X POST localhost:8000/v1/chat -H "authorization: Bearer $SEARCH" -H 'content-type: application/json' \
  -d '{"message": "saree under 1000"}'
```

```text
event: session
data: {"session_id": "chs_7B0uhvAOuBNcn2-8", "turn": 1}

event: plan
data: {"understood": {...same shape as /v1/search...}, "delta": {"turn_type": "new", "added": ["Under ₹1,000", "Sarees"], "removed": []}}

event: results
data: {"items": [{"id": "AP-00437", "score": 0.057, "document": {...}}, ...], "total": 10, "facets": {...},
       "pills": [...], "display": {"title": "title", "price": "price", ...}, "match_quality": "good", "close_matches": [...]}

event: clarify
data: {"question": "Only 1 match under ₹1,000. Want to see options slightly over budget?", "reason": "budget", "field": "price",
       "chips": [{"label": "Show slightly over budget", "count": null, "patch": [{"op": "set_price_range", "lte": 1300.0}],
                  "plan_patch": {"price": {"lte": 1300.0}}}, ...]}

event: text
data: {"delta": "Only one saree is under ₹1,000: "}
...
event: done
data: {"timings": {"plan": 2.1, "search": 21.4, "results": 21.9, "first_token": 2730.0, "total": 3150.2},
       "turn_type": "new", "reason": "names a product category", "answer_source": "model"}
```

To continue the conversation, send the `session_id` back with the next message: `{"session_id": "chs_...",
"message": "sasta wala"}`. To pick a clarifier chip, send its `patch` as `patch`, with its label as the
message: `{"session_id": "...", "message": "Show slightly over budget", "patch": [{"op": "set_price_range", "lte": 1300}]}`.
Removing an understood chip works the same way, with no message needed: `{"session_id": "...", "patch": <chip.remove>}`.
The older `apply` field, which takes a `plan_patch`, still works.

Sessions live in Redis for 30 minutes. If a patch arrives after its session expired, `done.reason` is
`session_expired`; ask again (the widget does this for you).

| Event | When | Payload |
|---|---|---|
| `session` | first | `session_id`, `turn` |
| `plan` | always | `understood` (chips, relaxations, match quality); `delta`: turn type plus chips added or removed versus the previous turn |
| `results` | as soon as the search returns, before any text | `items`, `total`, `facets`, `pills`, `display`, `match_quality`, `close_matches` (`unchanged: true` for questions and chit-chat) |
| `clarify` | optional, at most one per turn | `question`; `chips` built from the result set's own facet counts, each with a `patch` |
| `text` | streamed | answer deltas: 1–3 sentences, product ids cited as `[ID]`, same language as the user (Hinglish in, Hinglish out) |
| `done` | last | `timings` (ms since the request), `turn_type`, `reason`, `answer_source` (`model`, `fallback`, `error` or `template`) |

**How turns are handled.** Rules classify most turns; the LLM is only used when the rules can't tell.
- **New search:** runs the M2 planner on the message.
- **Refinement:** changes the current plan. Examples: "cheaper" / "aur sasta" lowers the price ceiling and
  sorts cheapest first; "under 500" / "500 ke andar" sets the price range; "only black" / "sirf cotton" adds a
  filter; "not plastic" / "black nahi" excludes; "bigger" / "chhota" moves along a size attribute such as
  "5 L" or "1 kg".
- **Question about shown products** ("is the second one lace-up?", "sabse sasta kaunsa?"): answered only from
  those products' fields. If the field isn't there, the answer says it doesn't know.
- **Chit-chat:** one line that steers back to searching.

**Clarifying questions** are asked at most once per turn, and only:
- when a price cap leaves fewer than 3 exact matches (chip: "Show slightly over budget");
- when a new search matches weakly;
- when the results span several product categories.

Attribute choices such as colour or size are passive facet pills (`results.pills`), not questions.

They are never asked right after the user answered one, or when the user says "just show" / "bas dikha do".

**Answers** are grounded: the model sees only the products on screen, with every number masked. It writes slots
such as `{price:ID}`, which the server fills from that product's fields. Each sentence is checked in code before
it streams, and is dropped whole if it:
- contains a number the model wrote itself (including spelled-out counts);
- puts a value on a product the sentence doesn't cite;
- names an attribute, product type or brand that doesn't fit the cited product;
- makes an uncited claim, or an "all / sabhi / both" claim that isn't true for every product it covers;
- makes a stock claim that the data doesn't support;
- makes a comparison (cheapest, highest rated, largest, sabse sasta…) other than the one computed in code.

If every sentence is dropped, or no chat LLM is configured, the answer is a plain template such as
"Top result: [ID]".

**Model:** local Ollama `llama3.1:8b` by default (`ZERCH_CHAT_MODEL`). For a hosted model, set
`ZERCH_CHAT_PROVIDER=openai` (with `OPENAI_API_KEY`, e.g. `gpt-4.1-mini`) or `anthropic` (with
`ZERCH_ANTHROPIC_API_KEY`). These are paid, and a key in `.env` alone never turns them on. `none` disables the
chat LLM. `scripts/chat_cli.py` is a terminal client for trying conversations.

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

### Locale packs

`packs/locales/en.yaml` and `packs/locales/hi-en.yaml` hold the language data the query parser uses:
- function words;
- price phrases ("under", "ke andar", "se kam");
- cheap and premium words;
- units;
- about 290 Hinglish words and phrases mapped to English ("tar" → cable, "sarson ka tel" → mustard oil,
  "gents" → men).

These are language resources, not catalog vocabulary. Each project's own values (colours, categories, brands)
come from its data. `ZERCH_LOCALE_PACKS` picks which packs load.

## Development

```bash
npm install && npm run check                  # JS: generate types, typecheck, build, bundle-size budgets
npm run e2e                                   # Playwright: widget (desktop + mobile) and React example; needs the stack up
uv sync
docker compose up -d postgres opensearch redis
uv run pytest                                 # integration tests use their own DB/index prefix and a hash embedder
uv run uvicorn zerch.main:app --reload        # API on the host (ZERCH_* env vars, see src/zerch/config.py)
uv run python -m zerch.worker                 # ingest worker
```

Run a single worker. Jobs for a project run in order.

### Demo data and evaluation

- `scripts/gen_demo_catalog.py` regenerates `data/demo_catalog.jsonl` and `.csv`. It needs Ollama (`llama3.1:8b`)
  or `--provider anthropic` with `ZERCH_ANTHROPIC_API_KEY`. Structured attributes are sampled from a
  taxonomy, and the LLM writes the brand names, titles and descriptions. All brands are invented, and nothing in
  the repo is scraped.
- `eval/build_queries.py` builds `eval/queries.jsonl`. Each query's relevant ids come from a predicate over the
  catalog's attributes.
- `uv run python eval/run.py --setup` imports the catalog into a new project, then writes `eval/report.md` with
  nDCG@10, recall@20, the zero-result rate and latency per segment, compared with the M1 baseline
  (`eval/baselines/m1.json`; the original M1 report is `eval/report_m1.md`).
- `uv run python scripts/bench.py` runs the 10k-document latency benchmark and writes `eval/latency_10k.md`.
- `uv run python eval/run_chat.py --search-key ...` runs the chat eval: 25 scripted conversations, scored on turn
  type, plan assertions, per-turn nDCG, clarifiers, numeric errors and latency. It writes the chat section of
  `eval/report.md` and saves every answer to `eval/results/` for review. `--judge` adds an LLM groundedness judge
  (local Ollama by default); the reported groundedness was reviewed by hand (`eval/chat_review_m4.md`).
- `eval/report.md` also covers planner call and cache rates, latency per path, out-of-catalog queries and the
  holdout (`eval/holdout.jsonl`: 20 Hinglish queries written by a different LLM, never tuned on, pending human
  review; format in `eval/README.md`).
- No eval script calls a paid API unless you pass a paid `--provider`/`--judge-provider` yourself.
