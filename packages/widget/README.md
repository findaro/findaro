# @findaro/widget

Drop-in AI search for any page: a `<findaro-search>` Web Component (Shadow DOM, no framework).

```html
<script src="findaro-widget.js" data-project="prj_…" data-key="fdr_search_…" data-base-url="https://api.example.com" defer></script>
<findaro-search></findaro-search>
```

Theme with CSS variables (`--findaro-accent`, `--findaro-bg`, `--findaro-fg`, `--findaro-radius`, …), customise cards with
`el.renderProduct = (hit, { display, formatPrice }) => …`, handle clicks with `el.onProductClick`, and override text with
`el.strings = { … }` (`locale="hi-en"` for Hinglish defaults). See the repository README.
