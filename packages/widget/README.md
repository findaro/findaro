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
`mode="search"` is search only (with a Search / Ask AI toggle).

Theme with CSS variables (`--findaro-accent`, `--findaro-bg`, `--findaro-fg`, `--findaro-radius`, `--findaro-font`,
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
| `starters="a\|b\|c"` | Up to 4 example requests in an empty conversation. |
| `badges="field,field"` | Up to 2 short value badges per card from these document fields. |
| `card-actions="Add to cart,Save"` | Extra card buttons; each click dispatches `findaro:action`. |

Script-tag equivalents: `data-layout`, `data-starters`, `data-badges`, `data-card-actions`.

```js
el.cardActions = [{ label: "Wishlist", onClick: (hit) => wishlist.add(hit.id) }];
el.addEventListener("findaro:action", (e) => {
  // e.detail = { action, hit }; cancelable (preventDefault() skips the cardActions onClick)
});
```
