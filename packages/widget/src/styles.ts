/** Shadow-DOM styles. Theme with CSS variables on the host page, e.g. findaro-search { --findaro-accent: #e05a00 } */
export const CSS = `
:host {
  --findaro-accent: #ff6a00;
  --findaro-accent-ink: #ffffff;
  --findaro-bg: #ffffff;
  --findaro-surface: #f5f5f6;
  --findaro-fg: #18181b;
  --findaro-muted: #71717a;
  --findaro-border: #e4e4e7;
  --findaro-chip-bg: #f4f4f5;
  --findaro-chip-fg: #18181b;
  --findaro-warn: #a16207;
  --findaro-radius: 12px;
  --findaro-font: system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
  --findaro-card-min: 160px;
  --findaro-ph-l: 92%;
  --findaro-ph-s: 55%;
  display: block;
  color: var(--findaro-fg);
  font: 15px/1.45 var(--findaro-font);
  container-type: inline-size;
}
@media (prefers-color-scheme: dark) {
  :host(:not([theme="light"])) {
    --findaro-bg: #111113; --findaro-surface: #1b1b1f; --findaro-fg: #ececef; --findaro-muted: #a1a1aa;
    --findaro-border: #2e2e33; --findaro-chip-bg: #232328; --findaro-chip-fg: #ececef; --findaro-warn: #eab308;
    --findaro-ph-l: 20%;
    --findaro-ph-s: 18%;
  }
}
:host([theme="dark"]) {
  --findaro-bg: #111113; --findaro-surface: #1b1b1f; --findaro-fg: #ececef; --findaro-muted: #a1a1aa;
  --findaro-border: #2e2e33; --findaro-chip-bg: #232328; --findaro-chip-fg: #ececef; --findaro-warn: #eab308;
  --findaro-ph-l: 20%;
  --findaro-ph-s: 18%;
}
* { box-sizing: border-box; }
[hidden] { display: none !important; }
.root { background: var(--findaro-bg); display: grid; gap: 14px; }
button { font: inherit; color: inherit; cursor: pointer; }
:focus-visible { outline: 2px solid var(--findaro-accent); outline-offset: 2px; }

/* search bar: [Search | Ask AI] [input] [button] in one pill */
.box { display: flex; align-items: center; gap: 6px; padding: 5px; min-width: 0;
       border: 1px solid var(--findaro-border); border-radius: 999px; background: var(--findaro-bg);
       box-shadow: 0 1px 2px rgb(0 0 0 / .05); }
.box:focus-within { border-color: var(--findaro-accent); }
.modes { display: inline-flex; flex: none; background: var(--findaro-surface); border-radius: 999px; padding: 2px; }
.modes button { border: 0; background: none; padding: 6px 12px; border-radius: 999px; font-size: 13px;
                font-weight: 600; color: var(--findaro-muted); white-space: nowrap; }
.modes button[aria-checked="true"] { background: var(--findaro-bg); color: var(--findaro-fg);
                                     box-shadow: 0 1px 2px rgb(0 0 0 / .12); }
.box input { flex: 1; min-width: 0; border: 0; padding: 8px 6px; font: inherit; color: var(--findaro-fg);
             background: transparent; }
.box input:focus { outline: none; }
.box input::placeholder { color: var(--findaro-muted); }
.go { flex: none; border: 0; border-radius: 999px; background: var(--findaro-accent); color: var(--findaro-accent-ink);
      padding: 9px 18px; font-weight: 600; }
@container (max-width: 480px) {
  .box { flex-wrap: wrap; border-radius: 18px; }
  .modes { order: -1; }
  .box input { flex-basis: 100%; order: 1; padding: 8px 10px; }
  .go { margin-left: auto; }
}

/* understood chips + filters toggle, one line */
.row { display: flex; flex-wrap: wrap; gap: 6px; align-items: center; }
.chip { display: inline-flex; align-items: center; gap: 2px; padding: 3px 4px 3px 12px; border-radius: 999px;
        background: var(--findaro-chip-bg); color: var(--findaro-chip-fg); font-size: 13px; font-weight: 500;
        border: 1px solid var(--findaro-border); }
.chip.boost, .chip.sort { background: transparent; }
.chip button { border: 0; background: none; color: var(--findaro-muted); width: 22px; height: 22px;
               border-radius: 50%; line-height: 1; font-size: 15px; }
.chip button:hover { color: var(--findaro-fg); background: var(--findaro-border); }
.filters-toggle { margin-left: auto; border: 0; background: none; color: var(--findaro-muted); font-size: 13px;
                  font-weight: 600; padding: 4px 6px; }
.filters-toggle:hover { color: var(--findaro-fg); }
.pills { display: grid; gap: 8px; padding: 12px; border: 1px solid var(--findaro-border);
         border-radius: var(--findaro-radius); background: var(--findaro-surface); }
.row-label { font-size: 12px; color: var(--findaro-muted); min-width: 64px; }
.pill { border: 1px solid var(--findaro-border); background: var(--findaro-bg); border-radius: 999px;
        padding: 4px 12px; font-size: 13px; }
.pill:hover { border-color: var(--findaro-fg); }
.pill small { color: var(--findaro-muted); margin-left: 4px; }

.layout { display: grid; gap: 14px; }
.status { font-size: 13px; color: var(--findaro-muted); min-height: 1.2em; margin-bottom: 8px; }
.status.weak { color: var(--findaro-warn); }

/* product grid */
.grid { list-style: none; margin: 0; padding: 0; display: grid; gap: 14px;
        grid-template-columns: repeat(auto-fill, minmax(var(--findaro-card-min), 1fr)); }
.card { display: flex; flex-direction: column; height: 100%; text-decoration: none; color: inherit; border: 0;
        background: none; text-align: left; padding: 0; width: 100%; }
.card .img { border-radius: var(--findaro-radius); }
.card:hover .title { text-decoration: underline; }
.img { aspect-ratio: 4 / 3; width: 100%; object-fit: cover; background: var(--findaro-surface); display: grid;
       place-items: center; font-size: 26px; font-weight: 600; color: var(--findaro-muted); }
.img.ph { background: hsl(var(--h) var(--findaro-ph-s) var(--findaro-ph-l)); color: hsl(var(--h) 30% 50%); }
.body { padding: 8px 2px 0; display: grid; gap: 2px; }
.title { font-size: 14px; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical;
         overflow: hidden; }
.price { font-weight: 700; font-size: 15px; }
.mrp { color: var(--findaro-muted); text-decoration: line-through; font-weight: 400; font-size: 12px;
       margin-left: 6px; }
.meta { font-size: 12px; color: var(--findaro-muted); display: flex; gap: 8px; flex-wrap: wrap; }
.badge { font-size: 11px; font-weight: 600; color: var(--findaro-warn); }

.empty { border: 1px dashed var(--findaro-border); border-radius: var(--findaro-radius); padding: 28px;
         text-align: center; color: var(--findaro-muted); }
.empty strong { display: block; color: var(--findaro-fg); margin-bottom: 4px; }

/* AI answer card, full width above the results */
.panel { border: 1px solid var(--findaro-border); border-radius: var(--findaro-radius); background: var(--findaro-surface);
         padding: 14px 16px; display: grid; gap: 12px; max-height: 50vh; overflow: auto; }
.panel:empty { display: none; }
.msg { display: grid; gap: 4px; }
.msg .who { font-size: 11px; font-weight: 600; color: var(--findaro-muted); text-transform: uppercase;
            letter-spacing: .04em; }
.msg.user .text { font-weight: 600; }
.msg .text { white-space: pre-wrap; }
.mini { display: inline-flex; align-items: center; gap: 6px; vertical-align: middle; max-width: 100%;
        border: 1px solid var(--findaro-border); background: var(--findaro-bg); border-radius: 8px;
        padding: 2px 8px 2px 2px; font-size: 13px; margin: 1px 0; color: inherit; }
.mini .img { width: 26px; height: 26px; aspect-ratio: 1; font-size: 12px; border-radius: 6px; }
.mini span { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; max-width: 220px; }
.clarify { display: grid; gap: 8px; margin-top: 4px; }
.clarify p { margin: 0; font-weight: 600; }
/* "Ask" button on each card */
.cell { position: relative; }
.ask { position: absolute; top: 8px; right: 8px; border: 1px solid var(--findaro-border); border-radius: 999px;
       background: var(--findaro-bg); color: var(--findaro-fg); font-size: 12px; font-weight: 600; padding: 4px 10px;
       box-shadow: 0 1px 3px rgb(0 0 0 / .12); }
.ask:hover { border-color: var(--findaro-accent); color: var(--findaro-accent); }

/* product drawer */
.scrim { position: fixed; inset: 0; background: rgb(0 0 0 / .35); z-index: 2147483000; }
.drawer { position: fixed; top: 0; right: 0; bottom: 0; width: min(440px, 100vw); z-index: 2147483001;
          background: var(--findaro-bg); color: var(--findaro-fg); display: grid; grid-template-rows: auto 1fr auto;
          box-shadow: -8px 0 24px rgb(0 0 0 / .18); font: 15px/1.45 var(--findaro-font); }
.dhead { display: flex; align-items: start; gap: 12px; padding: 16px 16px 8px;
         padding-top: calc(16px + env(safe-area-inset-top, 0px)); border-bottom: 1px solid var(--findaro-border); }
.dhead h2 { flex: 1; margin: 0; font-size: 16px; line-height: 1.35; }
.close { border: 0; background: none; font-size: 22px; line-height: 1; color: var(--findaro-muted); padding: 2px 6px; }
.close:hover { color: var(--findaro-fg); }
.dbody { overflow: auto; padding: 14px 16px; display: grid; gap: 14px; align-content: start; }
.summary { display: grid; grid-template-columns: 96px 1fr; gap: 12px; align-items: center; }
.summary .img { aspect-ratio: 1; border-radius: 10px; font-size: 22px; }
.summary .price { font-size: 18px; font-weight: 700; }
.link { font-size: 13px; color: var(--findaro-accent); }
.factsbox { display: grid; gap: 6px; padding: 10px 12px; background: var(--findaro-surface); border-radius: 10px; }
.facts { display: grid; grid-template-columns: max-content 1fr; gap: 4px 12px; margin: 0; font-size: 13px; }
.factsbox details summary { cursor: pointer; font-size: 13px; font-weight: 600; color: var(--findaro-muted); }
.factsbox details[open] summary { margin-bottom: 6px; }
.facts dt { color: var(--findaro-muted); }
.facts dd { margin: 0; overflow-wrap: anywhere; }
.thread { display: grid; gap: 12px; }
.thread:empty { display: none; }
.general { margin-top: 6px; padding: 8px 10px; border-left: 3px solid var(--findaro-border); background: var(--findaro-surface);
           border-radius: 0 8px 8px 0; font-size: 14px; color: var(--findaro-muted); display: grid; gap: 2px; }
.dfoot { padding: 10px 12px; padding-bottom: calc(10px + env(safe-area-inset-bottom, 0px));
         border-top: 1px solid var(--findaro-border); }
.dfoot .box { box-shadow: none; flex-wrap: nowrap; border-radius: 999px; }
.dfoot .box input { flex: 1 1 auto; order: 0; padding: 8px 10px; }
.dfoot .box .go { margin-left: 0; }

.typing::after { content: "▍"; animation: blink 1s steps(1) infinite; }
@keyframes blink { 50% { opacity: 0; } }
@media (prefers-reduced-motion: reduce) { /* "Ask" button on each card */
.cell { position: relative; }
.ask { position: absolute; top: 8px; right: 8px; border: 1px solid var(--findaro-border); border-radius: 999px;
       background: var(--findaro-bg); color: var(--findaro-fg); font-size: 12px; font-weight: 600; padding: 4px 10px;
       box-shadow: 0 1px 3px rgb(0 0 0 / .12); }
.ask:hover { border-color: var(--findaro-accent); color: var(--findaro-accent); }

/* product drawer */
.scrim { position: fixed; inset: 0; background: rgb(0 0 0 / .35); z-index: 2147483000; }
.drawer { position: fixed; top: 0; right: 0; bottom: 0; width: min(440px, 100vw); z-index: 2147483001;
          background: var(--findaro-bg); color: var(--findaro-fg); display: grid; grid-template-rows: auto 1fr auto;
          box-shadow: -8px 0 24px rgb(0 0 0 / .18); font: 15px/1.45 var(--findaro-font); }
.dhead { display: flex; align-items: start; gap: 12px; padding: 16px 16px 8px;
         padding-top: calc(16px + env(safe-area-inset-top, 0px)); border-bottom: 1px solid var(--findaro-border); }
.dhead h2 { flex: 1; margin: 0; font-size: 16px; line-height: 1.35; }
.close { border: 0; background: none; font-size: 22px; line-height: 1; color: var(--findaro-muted); padding: 2px 6px; }
.close:hover { color: var(--findaro-fg); }
.dbody { overflow: auto; padding: 14px 16px; display: grid; gap: 14px; align-content: start; }
.summary { display: grid; grid-template-columns: 96px 1fr; gap: 12px; align-items: center; }
.summary .img { aspect-ratio: 1; border-radius: 10px; font-size: 22px; }
.summary .price { font-size: 18px; font-weight: 700; }
.link { font-size: 13px; color: var(--findaro-accent); }
.factsbox { display: grid; gap: 6px; padding: 10px 12px; background: var(--findaro-surface); border-radius: 10px; }
.facts { display: grid; grid-template-columns: max-content 1fr; gap: 4px 12px; margin: 0; font-size: 13px; }
.factsbox details summary { cursor: pointer; font-size: 13px; font-weight: 600; color: var(--findaro-muted); }
.factsbox details[open] summary { margin-bottom: 6px; }
.facts dt { color: var(--findaro-muted); }
.facts dd { margin: 0; overflow-wrap: anywhere; }
.thread { display: grid; gap: 12px; }
.thread:empty { display: none; }
.general { margin-top: 6px; padding: 8px 10px; border-left: 3px solid var(--findaro-border); background: var(--findaro-surface);
           border-radius: 0 8px 8px 0; font-size: 14px; color: var(--findaro-muted); display: grid; gap: 2px; }
.dfoot { padding: 10px 12px; padding-bottom: calc(10px + env(safe-area-inset-bottom, 0px));
         border-top: 1px solid var(--findaro-border); }
.dfoot .box { box-shadow: none; flex-wrap: nowrap; border-radius: 999px; }
.dfoot .box input { flex: 1 1 auto; order: 0; padding: 8px 10px; }
.dfoot .box .go { margin-left: 0; }

.typing::after { animation: none; } }
`;
