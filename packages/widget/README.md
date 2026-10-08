# @zerch/widget

Drop-in AI search for any page: a `<zerch-search>` Web Component (Shadow DOM, no framework).

```html
<script src="zerch-widget.js" data-project="prj_…" data-key="zk_search_…" data-base-url="https://api.example.com" defer></script>
<zerch-search></zerch-search>
```

Theme with CSS variables (`--zerch-accent`, `--zerch-bg`, `--zerch-fg`, `--zerch-radius`, …), customise cards with
`el.renderProduct = (hit, { display, formatPrice }) => …`, handle clicks with `el.onProductClick`, and override text with
`el.strings = { … }` (`locale="hi-en"` for Hinglish defaults). See the repository README.
