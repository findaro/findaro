# findaro website

Marketing site and docs for findaro: plain static HTML, CSS and vanilla JS in `public/`. There's no build step and no
JS dependencies (fonts come from Google Fonts). Serve `public/` as the web root.

```bash
python3 -m http.server 8765 --directory site/public   # http://localhost:8765
```

| Path | Page |
|---|---|
| `public/index.html` | Landing page (no widget on it: every demo link goes to `/demo/`) |
| `public/demo/index.html` | The live demo: the site header plus the widget in its default unified mode (search as you type, Enter asks) on the demo project; `?q=` asks on load |
| `public/ai.html` | Redirects to `/demo/` (old links) |
| `public/pricing.html` | Pricing (INR by default, USD toggle remembered in localStorage) |
| `public/request-access.html` | Request-access form, POSTs JSON to `/api/request-access` |
| `public/docs/` | Docs: `index`, `quickstart`, `widget`, `sdk`, `api` (generated), `self-hosting` |
| `public/terms.html`, `public/privacy.html` | Draft legal templates. **They need legal review before launch.** |
| `public/404.html`, `robots.txt`, `sitemap.xml` | |
| `public/assets/` | `site.css`, `site.js`, `favicon.svg`, `og.png` |

## Placeholders

The deploy step replaces these strings in every file under `public/` (`.html`, `.xml`, `.txt`):

| Placeholder | Replaced with | Example |
|---|---|---|
| `__SITE_URL__` | Public site origin, no trailing slash (canonical/OG URLs, sitemap, widget URL in docs) | `https://findaro.example.com` |
| `__API_URL__` | API base URL, no trailing slash (demo widget, docs snippets) | `https://api.findaro.example.com` |
| `__DEMO_PROJECT__` | Demo project id for the live demo page (`/demo/`) | `prj_…` |
| `__DEMO_SEARCH_KEY__` | That project's **search** key (browser-safe; never an admin key) | `fdr_search_…` |
| `__GITHUB_URL__` | Repository URL, no trailing slash | `https://github.com/org/findaro` |
| `__COMPANY_NAME__` | Legal name of the operator (footer, terms, privacy) | |

For example:

```bash
find public -type f \( -name '*.html' -o -name '*.xml' -o -name '*.txt' \) -print0 | xargs -0 sed -i \
  -e "s#__SITE_URL__#$SITE_URL#g" -e "s#__API_URL__#$API_URL#g" \
  -e "s#__DEMO_PROJECT__#$DEMO_PROJECT#g" -e "s#__DEMO_SEARCH_KEY__#$DEMO_SEARCH_KEY#g" \
  -e "s#__GITHUB_URL__#$GITHUB_URL#g" -e "s#__COMPANY_NAME__#$COMPANY_NAME#g"
grep -rl '__[A-Z_]*__' public && echo "unreplaced placeholders" && exit 1
```

The deploy also has to:
- copy the built widget (`packages/widget/dist/findaro-widget.js`, from `npm run build`) to `public/findaro-widget.js`.
  The demo page (`/demo/`) loads it from `/findaro-widget.js`, and the docs tell customers to load it from
  `__SITE_URL__/findaro-widget.js`;
- add the site's origin to the demo project's `allowed_origins`;
- route `POST /api/request-access` to the request-access handler. The form sends
  `{name, email, company, website, catalog_size, plan, message, company_url_hp}`. `company_url_hp` is a honeypot
  that people leave empty, so drop submissions where it's filled in. The page shows a thank-you on 200, a "try
  later" message on 429 and a generic error otherwise;
- serve `404.html` for missing paths.

If the widget can't load, the demo page shows a short notice instead of an empty page.

## API reference

`public/docs/api.html` is generated from `packages/sdk/openapi.json`. Don't edit it by hand:

```bash
python3 site/build_api_docs.py           # regenerate
python3 site/build_api_docs.py --check   # fails if the committed page is stale
```

The script copies the page chrome (head, header, sidebar, footer) from `public/docs/index.html`, between the
`<!-- content:start -->` and `<!-- content:end -->` markers. Regenerate it after you change that page's header or
footer.

## Editing

The header, footer and docs sidebar are repeated in every page. If you change one, change them all. Colours and
fonts are CSS variables at the top of `assets/site.css`, with a dark palette under
`prefers-color-scheme: dark`. The palette is one blue, navy ink and cool greys, with no orange, amber or yellow:
caution states use `--note` (slate-indigo) and red (`--danger`) is only for form validation errors. Any
`<findaro-search>` on the site is themed from these tokens (bottom of `site.css`). Fonts: Geist (headings), IBM Plex
Sans (body), IBM Plex Mono (code).
