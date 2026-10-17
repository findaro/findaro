# @findaro/widget

Drop-in AI search for any page: a `<findaro-search>` Web Component (Shadow DOM, no framework).

```html
<script src="findaro-widget.js" data-project="prj_…" data-key="fdr_search_…" data-base-url="https://api.example.com" defer></script>
<findaro-search></findaro-search>
```

By default (`mode="unified"`) search and the assistant share one surface: results update as you type (rules only, no
LLM), Enter asks the assistant (`/v1/chat`), which refines the same grid and answers in a compact panel above it
(latest reply, "How I searched", next steps; earlier turns folded into "Conversation (N)"). Follow-ups in the same box
continue the session; chips, filter pills and next-step rows apply patches to it; cards can be selected (2–3) to compare
or ask about; "New search" starts over. `starters="a|b|c"` shows example requests as chips in the empty state.
`mode="search"` is search only (with a Search / Ask AI toggle; `starters` show as search chips when it's empty).

**Your own Search | AI Mode switch:** `toggle="off"` hides the built-in toggle and your page changes the `mode`
attribute (`search` ↔ `ai`). Each mode keeps its own results across switches; a search typed in Search mode is put in
the AI Mode composer (`el.search(el.query)` asks it right away; `el.turns` is the conversation length). `cards="full"`
gives the search grid the AI Mode cards (select to compare, "Matches 2/2", badges, Ask / View); Compare and Ask about
these switch to AI Mode and fire `findaro:mode` (`detail.mode`). The in-box AI Mode thread takes a fixed height from
`--findaro-thread-height` (composer docked at its bottom) and exposes `::part(thread)`. The site's
[live demo](../../site/public/demo/index.html) is built this way.

Light defaults: white, neutral greys, near-black text, one deep teal accent (no warm colours); `theme="light"` /
`theme="dark"` force a scheme, otherwise it follows the OS. Theme with CSS variables (`--findaro-accent`, `--findaro-bg`, `--findaro-fg`, `--findaro-radius`, `--findaro-font`,
`--findaro-font-heading`, `--findaro-accent-soft`, `--findaro-warn` for close-match/partial states, …), customise cards with
`el.renderProduct = (hit, { display, formatPrice }) => …`, handle clicks with `el.onProductClick`, and override text with
`el.strings = { … }` (`locale="hi-en"` for Hinglish defaults). See the repository README.

## AI Mode (full page, kept for existing integrations)

```html
<style>findaro-search { height: 100dvh; }</style>
<findaro-search mode="ai" layout="page" badges="material,tags" card-actions="Add to cart"
                starters="black shoes under 1000|steel water bottle"></findaro-search>
```

`mode="ai"` turns the widget into a conversational shopping assistant: products appear inline in the conversation,
with a "How I searched" summary, a requirement match line on each card ("Matches 1/2 · not Leather"), one-click next
steps, and select-to-compare (2–3 products). `layout="page"` makes it full-page, with a chat history sidebar (collapsible on
desktop, a drawer on phones) and an optional `slot="sidebar-footer"`; with `mode="search"` it shows a full-page search
view instead. Conversations are kept in `localStorage` per project; the search key is never stored.

| Attribute | |
|---|---|
| `layout="page"` | Full-page AI Mode with chat history (or full-page search with `mode="search"`). Give the element a height. |
| `starters="a\|b\|c"` | Up to 6 example requests in an empty conversation. |
| `toggle="off"` | No built-in Search / Ask AI toggle (the host page switches `mode`). |
| `cards="full"` | `mode="search"` uses the AI Mode cards. |
| `badges="field,field"` | Up to 2 short value badges per card from these document fields. |
| `card-actions="Add to cart,Save"` | Extra card buttons; each click dispatches `findaro:action`. |

Script-tag equivalents: `data-layout`, `data-starters`, `data-badges`, `data-card-actions`, `data-toggle`, `data-cards`.

```js
el.cardActions = [{ label: "Wishlist", onClick: (hit) => wishlist.add(hit.id) }];
el.addEventListener("findaro:action", (e) => {
  // e.detail = { action, hit }; cancelable (preventDefault() skips the cardActions onClick)
});
```
