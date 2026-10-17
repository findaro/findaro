# Findaro

[![CI](https://github.com/findaro/findaro/actions/workflows/ci.yml/badge.svg)](https://github.com/findaro/findaro/actions/workflows/ci.yml)
[![License](https://img.shields.io/badge/license-Apache--2.0-blue)](LICENSE)

**Open-source AI search for your catalog: one API call or one script tag, and it understands how your shoppers
actually type.**

Push your catalog as JSON or CSV, call one search endpoint (or drop in a widget), and get natural-language search
with filters inferred from the query, conversational refinement and grounded answers about your products. No
schema to define, no search engine to tune. Apache-2.0.

```text
"kaale joote 1000 ke andar"  →  black shoes, price ≤ ₹1,000   (chips: "Under ₹1,000" ×, "Black" ×)
```

**Try it:** [live demo](https://findaro.fortwinai.com/demo/) on a 3,000-product synthetic store (Search and AI Mode),
or see [findaro.fortwinai.com](https://findaro.fortwinai.com).

## Why findaro

- **Indian-English and Hinglish out of the box.** "sasta", "500 ke andar", "sarson ka tel", "gents chappal",
  Devanagari (`जूते` matches `joote`) and romanised spelling variants (joota / juta / jootey) all work, through
  language packs rather than per-catalog hacks.
- **Filters inferred from the query.** Prices, colours, materials, sizes, brands and categories are read from the
  words and applied as removable chips, using only values that exist in *your* catalog.
- **Chat-style refinement.** "running shoes for men" → "only black" → "aur sasta" → "is the second one lace-up?",
  over Server-Sent Events, with clarifying chips when they help.
- **Grounded product Q&A.** Ask about a product the way you would on a product page ("made in India or
  imported?", "return ho jayega?"). The model only sees the products on screen, numbers are filled in by the
  server, and every sentence is checked in code before it streams. If the listing doesn't say, the answer says so.
- **Drop-in widget and headless SDK.** `<findaro-search>` (one script tag, about 23 KB gzipped with the SDK) or `@findaro/sdk`
  (typed, zero dependencies, about 1.5 KB gzipped).
- **Hybrid retrieval.** BM25 (with typo tolerance and ICU analysis) plus multilingual vectors
  (`multilingual-e5-small`, run locally), fused with Reciprocal Rank Fusion.
- **Schema inference.** Field roles (title, price, facet, category, ...) are inferred from your data and can be
  overridden through the API.
- **Runs entirely on your machine.** The AI parts use local [Ollama](https://ollama.com) models by default. Paid
  LLM APIs are only used if you explicitly configure them, and search never depends on an LLM: it works fully
  without one.

## Quickstart: self-host in 5 minutes

Requirements: Docker (with about 4 GB of memory for containers), `curl` and `jq`.

```bash
git clone https://github.com/findaro/findaro.git && cd findaro
docker compose up -d --build        # API on :8000, plus worker, OpenSearch, Postgres, Redis
curl -s localhost:8000/healthz      # {"status":"ok"} once the API is up (the first build takes a few minutes)
```

**1. Create a project.** The response contains two keys. The `admin_key` manages data, so keep it on the server.
The `search_key` can only search and chat, so it is safe to use in browsers. On any deployment others can reach,
set `FINDARO_BOOTSTRAP_TOKEN`; otherwise anyone can create projects (the API logs a warning).

```bash
curl -s -X POST localhost:8000/v1/projects -H 'content-type: application/json' -d '{"name":"demo"}' | tee project.json
PID=$(jq -r .project_id project.json); ADMIN=$(jq -r .admin_key project.json); SEARCH=$(jq -r .search_key project.json)
```

**2. Import a catalog.** The repo ships a synthetic demo catalog (3,000 invented Indian e-commerce products). The
import runs as an async job:

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
  -d '{"query": "kaale joote 1000 ke andar", "size": 5}' \
  | jq '{total, chips: [.understood.chips[].label], hits: [.hits[] | {id, title: .document.title, price: .document.price}]}'

# typos, Hinglish, explicit filters
curl -s -X POST localhost:8000/v1/search -H "authorization: Bearer $SEARCH" -H 'content-type: application/json' \
  -d '{"query": "presure coker"}' | jq '[.hits[:3][].document.title]'
curl -s -X POST localhost:8000/v1/search -H "authorization: Bearer $SEARCH" -H 'content-type: application/json' \
  -d '{"query": "black running shoes", "filters": {"price": {"lte": 1500}}, "size": 5}' | jq '[.hits[].document.title]'
```

**5. Chat** (optional, needs a chat model; see below):

```bash
curl -N -X POST localhost:8000/v1/chat -H "authorization: Bearer $SEARCH" -H 'content-type: application/json' \
  -d '{"message": "saree under 1000"}'
```

### Local AI models (optional)

Search, query understanding and chat refinement work without any LLM. For streamed chat answers and the query
planner's fallback on unusual phrasing, install [Ollama](https://ollama.com) and pull the two default models:

```bash
ollama pull llama3.1:8b    # chat answers
ollama pull llama3.2:3b    # query planner, for words the rules can't read
```

Without them, chat answers fall back to plain one-line templates. Hosted models (OpenAI, Anthropic) are supported
but are never turned on by an API key alone; see [Chat](#chat-post-v1chat).

## Try the demo page

The demo page shows the widget on the demo catalog. It needs Node.js 20+ and [uv](https://docs.astral.sh/uv/)
(Python 3.12) in addition to the stack above:

```bash
npm install && npm run build                    # builds the SDK and the widget
uv run python scripts/demo_setup.py             # waits for the API, imports the demo catalog, warms the models
```

Open http://localhost:8080/demo.html. Things to try:
- Search: `kaale joote 1000 ke andar`, then remove the "Black" chip;
- Search: `presure coker` (typo), `sarson ka tel` (Hinglish), or `guitar strings` (nothing matches, said honestly);
- Ask AI: `saree under 1000`, then tap "Show slightly over budget";
- Ask AI: `running shoes for men`, then `only black`, then `is the second one lace-up?`;
- Search `women shoes under 1000`, tap **Ask** on a card, then `What is it made of?`, `Is this made in India or
  imported?`, `Pasand na aaye to return ho jayega?`.

Chat answers take a few seconds on the local 8B model.

## Hosted findaro

Don't want to run OpenSearch, Postgres and the models yourself? A managed version of findaro is in **beta**: the same
API, SDK and widget, operated for you in India (Mumbai). [Request access](https://findaro.fortwinai.com/request-access.html)
or [try the live demo](https://findaro.fortwinai.com/demo/).

The open-source core in this repository is complete on its own; the hosted service runs the same engine. How we
deploy it (one Docker host behind a shared Caddy, fronted by a Cloudflare Worker so the server's address stays
private) is in [`deploy/app-a1`](deploy/app-a1/README.md) and [`deploy/cloudflare`](deploy/cloudflare/deploy.sh).

## Add search to your site (script tag)

1. Create a project and import your catalog (see the [quickstart](#quickstart-self-host-in-5-minutes)), and keep
   the **search key**. It's browser-safe: read-only, search and chat only.
2. Allow your site's origin. localhost always works (`FINDARO_ALLOW_LOCALHOST_ORIGINS=false` turns that off for
   production).

   ```bash
   curl -X PUT localhost:8000/v1/projects/$PID/settings -H "authorization: Bearer $ADMIN" \
     -H 'content-type: application/json' -d '{"allowed_origins": ["https://shop.example.com"]}'
   ```
3. Add one script tag and one element to any page:

   ```html
   <script src="findaro-widget.js" data-project="prj_…" data-key="fdr_search_…" data-base-url="https://api.example.com" defer></script>
   <findaro-search></findaro-search>
   ```

Build the widget with `npm install && npm run build`; the file is `packages/widget/dist/findaro-widget.js` (the
packages are not published to npm or a CDN yet). By default (`mode="unified"`) it gives you one surface:
- one search box: results update as you type (rules only, no LLM); **Enter asks the assistant**, and follow-ups typed
  in the same box ("only leather", "cheaper", "is the first one leather?") continue the conversation;
- understood chips ("Under ₹1,000", "Black") that can be removed, and facet pills behind a "Filters" button;
- a compact assistant panel above the results: the latest streamed answer with inline cards for the products it cites,
  "How I searched", one-click next steps and clarifier rows ("Show slightly over budget"); earlier turns fold into a
  "Conversation (N)" expander;
- a product grid (image, title, price, rating, a "Matches 2/2" requirement line), where shoppers select 2–3 products
  to compare them side by side or ask about them;
- an **Ask** button on every card that opens a product drawer: the product's details, suggested questions
  (picked from the fields it has, e.g. material, origin, warranty) and a chat about that one product.

`mode="search"` is search only (with a Search / Ask AI toggle); `mode="ai"` and `layout="page"` give the older
full-page conversational AI Mode. The demo pages are `examples/plain-html/unified.html` (the default mode) and
`index.html` (`mode="search"`), with the demo project's keys filled in by `scripts/demo_setup.py`.

**Customise:**

```html
<style>
  findaro-search { --findaro-accent: #2563eb; --findaro-radius: 6px; --findaro-font: Inter, sans-serif; --findaro-card-min: 180px; }
</style>
<findaro-search locale="hi-en" mode="ai" size="24"></findaro-search>
<script>
  const el = document.querySelector("findaro-search");
  el.onProductClick = (hit) => location.assign(`/p/${hit.id}`);               // replaces opening the product URL
  el.renderProduct = (hit, { display, formatPrice }) => {                     // your own card: return an element
    const card = document.createElement("div");                              // (textContent keeps catalog data safe;
    card.className = "my-card";                                               // if you return an HTML string,
    card.textContent = `${hit.document[display.title]} · ${formatPrice(hit.document[display.price])}`;
    return card;                                                              // escape document fields yourself)
  };
  el.strings = { placeholder: "Search 10,000 products…" };                    // any UI text; locale="hi-en" for Hinglish
  el.addEventListener("findaro:results", (e) => console.log(e.detail.total));  // also findaro:product-click, findaro:error
</script>
```

- **Attributes:** `project`, `key`, `base-url` (override the script tag), `mode` (`unified` | `search` | `ai`), `locale`
  (`en` | `hi-en`), `placeholder`, `size`, `theme` (`light` | `dark`; default follows `prefers-color-scheme`).
- **Behaviour:** the widget is mobile-first and keyboard accessible: the mode toggle is a radio group, Enter
  searches and Escape clears, and the conversation is an ARIA live log.
- **Safety:** product links from catalog data are only followed if they are `http(s)`. Search-as-you-type never
  calls the LLM planner; only a submitted search can.

## Headless SDK

`@findaro/sdk` is a typed client with zero dependencies (ESM + UMD). Its types are generated from the API's OpenAPI
spec (`packages/sdk/openapi.json`, regenerated by `scripts/export_openapi.py` and `npm run gen:types`).

```ts
import { createClient, debounce } from "@findaro/sdk";

const findaro = createClient({ projectId: "prj_…", searchKey: "fdr_search_…", baseUrl: "http://localhost:8000" });

const res = await findaro.search("kaale joote 1000 ke andar");          // typed SearchResponse
res.understood?.chips;  // [{ label: "Under ₹1,000", remove: [...] }, { label: "Black", remove: [...] }]
await findaro.search({ query: res.query, patch: res.understood!.chips[1].remove });   // drop "Black"

// chat: iterate events, use callbacks, or await .result
const turn = findaro.chat("sasta wala", { sessionId, onText: (_, full) => render(full) });
for await (const ev of turn) if (ev.type === "results") showProducts(ev.data.items);
const { sessionId: next, clarify } = await turn.result;

// talk about one product (e.g. on a product page): facts in .text, labeled general know-how in .general
const about = await findaro.chat("Is this made in India?", { productIds: ["FW-00421"] }).result;

const searchAsYouType = debounce((q: string) => findaro.search(q), 250);
```

- **Cancellation:** a new `search()` (or `chat()`) cancels the client's previous in-flight one; pass
  `{ cancelPrevious: false }` to keep it.
- **Retries:** network errors are retried once.
- **Errors:** API errors throw a `FindaroError` with `status` and `code`.
- **Example:** `examples/react/` is a 40-line Vite + React app that uses only the SDK.

## Architecture

```text
 browser (widget / SDK, search key)        your server (admin key)
              │                                      │
              ▼                                      ▼
        FastAPI API ──── query understanding (rules + locale packs + per-project value dictionary,
              │          optional LLM planner behind a timeout) ──── chat (SSE, grounded answers)
              │
   ┌──────────┼──────────────┬───────────────┐
   ▼          ▼              ▼               ▼
OpenSearch  Redis         Postgres        ingest worker
(BM25+kNN)  (cache,       (projects,      (parse, infer schema,
            rate limit,   hashed keys,     embed, index)
            chat sessions) jobs)
```

Python 3.12 + FastAPI, OpenSearch 3 (with `analysis-icu`), Postgres, Redis, local `multilingual-e5-small`
embeddings, and a pluggable LLM interface (Ollama by default; OpenAI and Anthropic opt-in). The engine is
domain-agnostic: nothing in `src/findaro/` knows about any particular catalog. Everything catalog-specific is
inferred from your data.

## API reference

All endpoints take `Authorization: Bearer <key>`. The `X-Findaro-Key: <key>` header works too.

| Method | Path | Key | |
|---|---|---|---|
| POST | `/v1/projects` | bootstrap token, if `FINDARO_BOOTSTRAP_TOKEN` is set | → `project_id`, `admin_key`, `search_key` |
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
  works unless `FINDARO_ALLOW_LOCALHOST_ORIGINS=false`.
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
bypass the cache. Each key is limited to 50 requests per second (`FINDARO_RATE_LIMIT_PER_SECOND`).

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

What it understood comes back in `understood`. This field is meant for search UIs (the widget and SDK build on it):

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

The planner runs on local Ollama `llama3.2:3b` by default (`FINDARO_PLANNER_MODEL`), or on Claude Haiku with
`FINDARO_PLANNER_PROVIDER=anthropic` and `FINDARO_ANTHROPIC_API_KEY` (paid; never enabled by a key alone). Its limits:
- **Time:** it waits at most `FINDARO_PLANNER_TIMEOUT_MS` (default 800) and then falls back to the rules plan. A
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
| `text` | streamed | answer deltas: 1–3 sentences, product ids cited as `[ID]`, same language as the user (Hinglish in, Hinglish out); `part` is `answer` or `general` (labeled general advice, product conversations only) |
| `done` | last | `timings` (ms since the request), `turn_type`, `reason`, `answer_source` (`model`, `fallback`, `error` or `template`) |

**How turns are handled.** Rules classify most turns; the LLM is only used when the rules can't tell.
- **New search:** runs the query planner on the message.
- **Refinement:** changes the current plan. Examples: "cheaper" / "aur sasta" lowers the price ceiling and
  sorts cheapest first; "under 500" / "500 ke andar" sets the price range; "only black" / "sirf cotton" adds a
  filter; "not plastic" / "black nahi" / "not slippers" excludes; "increase it to 2000" / "2000 tak" sets a new
  price cap; "bigger" / "chhota" moves along a size attribute such as
  "5 L" or "1 kg".
- **Question about shown products** ("is the second one lace-up?", "sabse sasta kaunsa?"): answered only from
  those products' fields. If the field isn't there, the answer says it doesn't know.
- **Greetings and thanks** ("hi", "shukriya"): an instant one-line reply (no LLM). With nothing on screen it comes
  with suggestion chips for the catalog's main categories.
- **Small talk or a need in the shopper's own words** ("going to Goa next week, kuch suggest karo", "how's your
  day?", "gift for my dad"): when the words name nothing in the catalog and their search finds no good match, the
  chat model replies like a shop assistant (one JSON call, `FINDARO_CHAT_CONVERSE_TIMEOUT_MS`, default 8 s). If the
  catalog can help, it also suggests a search in the catalog's own words, which runs and fills the results
  (`done.reason` = `conversation`). If not, the results on screen stay, and suggestion chips are offered. The reply
  can't see products, so a sentence with a number, citation, price, stock, offer or delivery claim is dropped.
  The model chooses what to look at, but attribute filters (gender, colour, budget) in its search are kept only
  if the shopper used those words. Plain searches never take this path.

**Clarifying questions** are asked at most once per turn, and only:
- when a price cap leaves fewer than 3 exact matches (chip: "Show slightly over budget");
- when a new search matches weakly;
- when the results span several product categories.

Attribute choices such as colour or size are passive facet pills (`results.pills`), not questions.

**Suggestion chips** use the same `clarify` event with `reason: "suggest"` and an empty `patch`: send the chip's
label as the next `message` (an empty `patch` is not treated as a plan edit).

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

**Talking about a product.** Send `product_ids` (up to 3) and every turn is answered about those products, the
way a shopper would ask about a product page: "what is it made of?", "is this made in India or imported?",
"pasand na aaye to return ho jayega?". Keep sending the same `session_id` for follow-ups. The model sees the
products' full listings (including text such as care instructions and seller Q&A).
The `results` event resends what was on screen with `unchanged: true`, and `done.turn_type` is `product`.

```bash
curl -N -X POST localhost:8000/v1/chat -H "authorization: Bearer $SEARCH" -H 'content-type: application/json' \
  -d '{"message": "Is this made in India or imported?", "product_ids": ["FW-00421"]}'
```

The answer has up to two parts, both streamed as `text` events:
- `part: "answer"` (the default) holds the facts about the product, from its listing only. If the listing doesn't
  have a detail, it says so ("The seller hasn't listed a warranty") instead of guessing.
- `part: "general"` is an optional line of general know-how ("Always check the care label before washing…").
  Show it labeled as general advice. It is checked to make no claim about the product: no numbers, brands,
  citations or comparisons.

On top of the checks above, a product answer is dropped sentence by sentence if it:
- gives a yes/no suitability verdict ("it's fine for the monsoon", "roz use ke liye theek hai") the listing doesn't
  state in its own words;
- promises a return, refund, replacement or exchange the listing doesn't name (a "10-day replacement" is not "you
  can return it");
- names a value the catalog uses elsewhere (a country, a colour) that this product doesn't list;
- says a listed detail is missing (the model is asked once more, pointed at that field).

If nothing survives, the reply is honest: it quotes the listed policy, or says the seller doesn't state it.

**Model:** local Ollama `llama3.1:8b` by default (`FINDARO_CHAT_MODEL`). For a hosted model, set
`FINDARO_CHAT_PROVIDER=openai` (with `OPENAI_API_KEY`, e.g. `gpt-4.1-mini`) or `anthropic` (with
`FINDARO_ANTHROPIC_API_KEY`). These are paid, and a key in `.env` alone never turns them on. `none` disables the
chat LLM. `scripts/chat_cli.py` is a terminal client for trying conversations.

### Schema roles

On first ingest, findaro infers one role per field from the field names and value statistics. Fields that first
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
come from its data. `FINDARO_LOCALE_PACKS` picks which packs load.

## Development

See [CONTRIBUTING.md](CONTRIBUTING.md) for the full setup. In short:

```bash
uv sync && docker compose up -d postgres opensearch redis
uv run pytest                                 # integration tests use their own DB/index prefix and a hash embedder
uv run uvicorn findaro.main:app --reload        # API on the host (FINDARO_* env vars, see src/findaro/config.py)
uv run python -m findaro.worker                 # ingest worker (run a single worker; jobs for a project run in order)
npm install && npm run check                  # JS: generate types, typecheck, build, bundle-size budgets
npm run e2e                                   # Playwright: widget (desktop + mobile) and React example; needs the stack up
```

### Query log

With `FINDARO_QUERY_LOG` set to a file path, every submitted search and every chat turn is appended as one JSON line:
the query or message, the understood chips, match quality, total, top 10 results (id and title), and for chat the
turn type, clarifier, answer, general tip, dropped sentences and timings. Search-as-you-type keystrokes are not
logged. `docker compose` turns it on, writing to `./logs/queries.jsonl` (gitignored); set `FINDARO_QUERY_LOG=` to
turn it off. Read it with:

```bash
uv run python scripts/queries.py            # last 20 entries, readable
uv run python scripts/queries.py -f --chat  # follow chat turns as they happen
uv run python scripts/queries.py --json | jq .
```

Queries are end-user data: it is off by default outside compose; decide on retention before enabling it in a
real deployment.

### Demo data and evaluation

- `scripts/gen_demo_catalog.py` regenerates `data/demo_catalog.jsonl` and `.csv`. It needs Ollama (`llama3.1:8b`)
  or `--provider anthropic` with `FINDARO_ANTHROPIC_API_KEY`. Structured attributes are sampled from a
  taxonomy, and the LLM writes the brand names, titles and descriptions. All brands are invented, and nothing in
  the repo is scraped.
- `scripts/enrich_demo_catalog.py` adds what shoppers ask about (country of origin, warranty, return policy, care,
  seller Q&A), seeded per product with no LLM. About 12% of products leave each one out, so "the seller hasn't
  listed that" is a real answer.
- `uv run python eval/run_product_chat.py --search-key ...` runs the product-conversation eval (12 products × 4
  questions); hand review in `eval/product_chat_review_m5.md`.
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
  holdout (`eval/holdout.jsonl`: 20 Hinglish queries written by a different LLM, never tuned on; format in
  `eval/README.md`).
- No eval script calls a paid API unless you pass a paid `--provider`/`--judge-provider` yourself.

A short milestone history is in [docs/history.md](docs/history.md).

## Status and roadmap

findaro is early (0.x): the API is versioned under `/v1` and changes additively, but expect rough edges. Not built
yet: autocomplete, recommendations, personalization, analytics and click tracking, an admin dashboard, database
or Shopify connectors, image and voice search, and npm/CDN packages. Ideas and pull requests are welcome; see
[CONTRIBUTING.md](CONTRIBUTING.md).

## Contributing, security and license

- Contributing: [CONTRIBUTING.md](CONTRIBUTING.md) · Code of conduct: [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md)
- Security issues: please report privately, see [SECURITY.md](SECURITY.md)
- License: [Apache-2.0](LICENSE)
