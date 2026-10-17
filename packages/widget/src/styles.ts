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
  --findaro-ok: #15803d;
  --findaro-radius: 12px;
  --findaro-font: system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
  --findaro-card-min: 160px;
  --findaro-page-width: 880px;
  --findaro-ph-l: 92%;
  --findaro-ph-s: 55%;
  --findaro-accent-soft: color-mix(in srgb, var(--findaro-accent) 11%, var(--findaro-bg));
  display: block;
  color: var(--findaro-fg);
  font: 15px/1.45 var(--findaro-font);
  container-type: inline-size;
}
@media (prefers-color-scheme: dark) {
  :host(:not([theme="light"])) {
    --findaro-bg: #111113; --findaro-surface: #1b1b1f; --findaro-fg: #ececef; --findaro-muted: #a1a1aa;
    --findaro-border: #2e2e33; --findaro-chip-bg: #232328; --findaro-chip-fg: #ececef; --findaro-warn: #eab308;
    --findaro-ok: #4ade80; --findaro-ph-l: 20%; --findaro-ph-s: 18%;
  }
}
:host([theme="dark"]) {
  --findaro-bg: #111113; --findaro-surface: #1b1b1f; --findaro-fg: #ececef; --findaro-muted: #a1a1aa;
  --findaro-border: #2e2e33; --findaro-chip-bg: #232328; --findaro-chip-fg: #ececef; --findaro-warn: #eab308;
  --findaro-ok: #4ade80; --findaro-ph-l: 20%; --findaro-ph-s: 18%;
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
.box.solo { border: 0; padding: 0; box-shadow: none; background: none; }
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
.meta:empty { display: none; }
.badge { font-size: 11px; font-weight: 600; color: var(--findaro-warn); }

.empty { border: 1px dashed var(--findaro-border); border-radius: var(--findaro-radius); padding: 28px;
         text-align: center; color: var(--findaro-muted); }
.empty strong { display: block; color: var(--findaro-fg); margin-bottom: 4px; }

.msg .who { font-size: 11px; font-weight: 600; color: var(--findaro-muted); text-transform: uppercase;
            letter-spacing: .04em; }
.msg .text { white-space: pre-wrap; }
.mini { display: inline-flex; align-items: center; gap: 6px; vertical-align: middle; max-width: 100%;
        border: 1px solid var(--findaro-border); background: var(--findaro-bg); border-radius: 8px;
        padding: 2px 8px 2px 2px; font-size: 13px; margin: 1px 0; color: inherit; }
.mini .img { width: 26px; height: 26px; aspect-ratio: 1; font-size: 12px; border-radius: 6px; }
.mini span { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; max-width: 220px; }
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
.thread .msg { display: grid; gap: 4px; }
.thread .msg.user .text { font-weight: 600; }
.general { margin-top: 6px; padding: 8px 10px; border-left: 3px solid var(--findaro-border); background: var(--findaro-surface);
           border-radius: 0 8px 8px 0; font-size: 14px; color: var(--findaro-muted); display: grid; gap: 2px; }
.dfoot { padding: 10px 12px; padding-bottom: calc(10px + env(safe-area-inset-bottom, 0px));
         border-top: 1px solid var(--findaro-border); }
.dfoot .box { box-shadow: none; flex-wrap: nowrap; border-radius: 999px; }
.dfoot .box input { flex: 1 1 auto; order: 0; padding: 8px 10px; }
.dfoot .box .go { margin-left: 0; }

/* ---------- AI Mode ---------- */
.sr { position: absolute; width: 1px; height: 1px; overflow: hidden; clip: rect(0 0 0 0); white-space: nowrap; }
.ico { display: inline-grid; width: 18px; height: 18px; flex: none; }
.ico svg { width: 100%; height: 100%; }
.thread-wrap { display: grid; grid-template-rows: minmax(0, 1fr) auto; min-height: 0; min-width: 0;
               border: 1px solid var(--findaro-border); border-radius: calc(var(--findaro-radius) + 6px);
               background: var(--findaro-bg); }
.scroll { position: relative; overflow-y: auto; overscroll-behavior: contain; padding: 20px 18px 8px;
          max-height: min(75vh, 820px); min-height: 300px; }
.log { display: grid; gap: 26px; }
.log:empty { display: none; }
.log .msg.user { justify-self: end; max-width: min(80%, 640px); }
.log .msg.user .text { background: var(--findaro-accent-soft); padding: 10px 16px; border-radius: 20px 20px 6px 20px;
                       font-weight: 500; overflow-wrap: anywhere; }
.log .msg.assistant { display: grid; gap: 12px; min-width: 0; }
.msg.assistant > .text { line-height: 1.6; overflow-wrap: anywhere; }
.msg.assistant > .text:empty { display: none; }
.msg.err > .text { color: var(--findaro-warn); }
.ahead { display: flex; align-items: center; gap: 8px; font-size: 13.5px; }
.ahead strong { font-weight: 650; }
.ahead time { color: var(--findaro-muted); font-size: 12px; }
.avatar { width: 28px; height: 28px; border-radius: 50%; display: grid; place-items: center; flex: none;
          color: var(--findaro-accent-ink);
          background: linear-gradient(135deg, var(--findaro-accent), color-mix(in srgb, var(--findaro-accent) 45%, #7c3aed)); }
.avatar .ico { width: 16px; height: 16px; }
.avatar.big { width: 52px; height: 52px; box-shadow: 0 8px 24px color-mix(in srgb, var(--findaro-accent) 30%, transparent); }
.avatar.big .ico { width: 26px; height: 26px; }
.step { color: var(--findaro-muted); }
.dots i { display: inline-block; width: 4px; height: 4px; margin-left: 3px; border-radius: 50%; background: currentColor;
          vertical-align: middle; animation: dot 1.2s infinite ease-in-out; }
.dots i:nth-child(2) { animation-delay: .15s; }
.dots i:nth-child(3) { animation-delay: .3s; }
@keyframes dot { 0%, 80%, 100% { opacity: .25; transform: none; } 40% { opacity: 1; transform: translateY(-3px); } }

/* "How I searched" */
.how { font-size: 13px; color: var(--findaro-muted); }
.how summary { list-style: none; cursor: pointer; display: inline-flex; align-items: center; gap: 6px;
               padding: 4px 12px 4px 8px; border-radius: 999px; background: var(--findaro-surface);
               border: 1px solid var(--findaro-border); }
.how summary::-webkit-details-marker { display: none; }
.how summary:hover { color: var(--findaro-fg); }
.how summary .ico { width: 14px; height: 14px; transition: transform .15s; }
.how[open] summary .ico { transform: rotate(90deg); }
.how-t { font-weight: 600; color: var(--findaro-fg); }
.how-m::before { content: "·"; margin-right: 6px; }
.how-b { margin: 10px 0 2px 14px; padding: 2px 0 2px 14px; border-left: 2px solid var(--findaro-border);
         display: grid; gap: 8px; }
.how-r { display: flex; gap: 10px; align-items: baseline; flex-wrap: wrap; }
.how-k { min-width: 84px; font-weight: 600; }
.how-v { display: flex; gap: 6px; flex-wrap: wrap; color: var(--findaro-fg); }
.how-r.relax { color: var(--findaro-warn); }
.uchip { font-size: 12px; padding: 1px 10px; border-radius: 999px; background: var(--findaro-chip-bg);
         color: var(--findaro-chip-fg); border: 1px solid var(--findaro-border); }

/* inline results */
.res { display: grid; gap: 12px; min-width: 0; }
.res-h { display: flex; align-items: baseline; gap: 10px; flex-wrap: wrap; }
.res-h h3 { margin: 0; font-size: 16px; font-weight: 650; }
.res-h h3::first-letter { text-transform: uppercase; }
.res-h span { font-size: 13px; color: var(--findaro-muted); }
.res .status { margin: 0; }
.tcards { grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 16px; }
.pc { position: relative; display: flex; flex-direction: column; min-width: 0; border: 1px solid var(--findaro-border);
      border-radius: calc(var(--findaro-radius) + 2px); overflow: hidden; background: var(--findaro-bg);
      transition: box-shadow .15s, border-color .15s; }
.pc:hover { box-shadow: 0 8px 24px rgb(0 0 0 / .08); }
.pc.on { border-color: var(--findaro-accent); box-shadow: 0 0 0 1px var(--findaro-accent); }
.pc .card { flex: 1; height: auto; }
.pc .card .img { border-radius: 0; aspect-ratio: 1; }
.pc .card:focus-visible { outline-offset: -2px; }
.pc .body { padding: 10px 12px 2px; gap: 5px; align-content: start; }
.pc .title { font-weight: 500; line-height: 1.35; }
.sel { position: absolute; top: 10px; left: 10px; display: inline-flex; align-items: center; gap: 6px;
       padding: 4px 10px 4px 8px; border-radius: 999px; background: rgb(255 255 255 / .94); color: #18181b;
       font-size: 12px; font-weight: 600; box-shadow: 0 1px 4px rgb(0 0 0 / .18); cursor: pointer; }
.sel input { margin: 0; width: 15px; height: 15px; accent-color: var(--findaro-accent); cursor: pointer; }
.sel:has(input:focus-visible) { outline: 2px solid var(--findaro-accent); outline-offset: 2px; }
.sel input:focus-visible { outline: none; }
.pc.on .sel { background: var(--findaro-accent); color: var(--findaro-accent-ink); }
.tags { display: flex; gap: 4px; flex-wrap: wrap; }
.tag { font-size: 11px; line-height: 1.6; padding: 0 8px; border-radius: 999px; background: var(--findaro-chip-bg);
       color: var(--findaro-chip-fg); font-weight: 500; border: 1px solid var(--findaro-border); }
.oos { color: var(--findaro-warn); }
.req { font-size: 12px; display: flex; gap: 4px; align-items: flex-start; color: var(--findaro-ok); line-height: 1.4; }
.req.part { color: var(--findaro-warn); }
.req .ico { width: 14px; height: 14px; margin-top: 1px; }
.acts { display: flex; gap: 6px; padding: 10px 12px 12px; flex-wrap: wrap; }
.act { flex: 1 1 auto; text-align: center; border: 1px solid var(--findaro-border); background: var(--findaro-bg);
       border-radius: 999px; padding: 5px 10px; font-size: 12.5px; font-weight: 600; text-decoration: none;
       color: inherit; white-space: nowrap; }
.act:hover { border-color: var(--findaro-accent); color: var(--findaro-accent); }
.more { justify-self: center; border: 1px solid var(--findaro-border); background: var(--findaro-bg); border-radius: 999px;
        padding: 7px 18px; font-size: 13px; font-weight: 600; }
.more:hover { border-color: var(--findaro-fg); }

/* next steps, clarifying questions, starters */
.clarify { display: grid; gap: 8px; }
.clarify p { margin: 0; font-weight: 600; }
.nrow { display: flex; align-items: center; gap: 10px; width: 100%; text-align: left; border: 1px solid var(--findaro-border);
        background: var(--findaro-bg); border-radius: 14px; padding: 12px 16px; font-size: 14px; }
.nrow > span:not(.ico) { flex: 1; min-width: 0; }
.nrow small { color: var(--findaro-muted); font-size: 12px; }
.nrow .ico { color: var(--findaro-muted); width: 16px; height: 16px; transition: transform .15s; }
.nrow:hover { border-color: var(--findaro-accent); background: var(--findaro-accent-soft); }
.nrow:hover .ico { transform: translateX(3px); color: var(--findaro-accent); }

/* compare table */
.cmp { overflow-x: auto; border: 1px solid var(--findaro-border); border-radius: calc(var(--findaro-radius) + 2px); }
.cmp table { border-collapse: collapse; width: 100%; font-size: 13px; table-layout: fixed; }
.cmp thead td { width: 150px; }
.cmp th, .cmp td { padding: 10px 12px; text-align: left; vertical-align: top; border-bottom: 1px solid var(--findaro-border); }
.cmp thead th { font-weight: 600; }
.cmp thead th span { display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }
.cmp thead .img { width: 64px; height: 64px; aspect-ratio: 1; border-radius: 10px; font-size: 18px; margin-bottom: 6px; }
.cmp tbody th { color: var(--findaro-muted); font-weight: 500; white-space: nowrap; background: var(--findaro-surface); }
.cmp tr.diff td { background: var(--findaro-accent-soft); }
.cmp tbody tr:last-child > * { border-bottom: 0; }

/* dock: jump button, notice, selection bar, current filters, composer */
.dock { position: sticky; bottom: 0; display: grid; gap: 8px; padding: 10px 16px 14px;
        background: linear-gradient(to bottom, transparent, var(--findaro-bg) 14px); border-radius: inherit; }
.dock .chips { font-size: 13px; }
.composer { display: flex; align-items: flex-end; gap: 8px; padding: 7px 7px 7px 20px; background: var(--findaro-bg);
            border: 1.5px solid var(--findaro-border); border-radius: 28px; box-shadow: 0 6px 20px rgb(0 0 0 / .06);
            transition: border-color .15s, box-shadow .15s; }
.composer:focus-within { border-color: var(--findaro-accent);
                         box-shadow: 0 0 0 4px var(--findaro-accent-soft), 0 6px 20px rgb(0 0 0 / .06); }
.composer textarea { flex: 1; min-width: 0; resize: none; border: 0; outline: 0; background: transparent; color: inherit;
                     font: inherit; font-size: 16px; line-height: 1.45; padding: 9px 0; margin: 0;
                     max-height: calc(6 * 1.45em + 18px); overflow-y: auto; }
.composer textarea::placeholder { color: var(--findaro-muted); }
.send { width: 42px; height: 42px; border-radius: 50%; border: 0; background: var(--findaro-accent);
        color: var(--findaro-accent-ink); display: grid; place-items: center; flex: none; }
.send .ico { width: 20px; height: 20px; }
.send:disabled { background: var(--findaro-surface); color: var(--findaro-muted); cursor: default; }
.jump { position: absolute; top: -46px; left: 50%; transform: translateX(-50%); width: 38px; height: 38px;
        border-radius: 50%; border: 1px solid var(--findaro-border); background: var(--findaro-bg);
        box-shadow: 0 4px 14px rgb(0 0 0 / .16); display: grid; place-items: center; z-index: 1; }
.notice { font-size: 13px; color: var(--findaro-warn); text-align: center; font-weight: 600; }
.selbar { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; padding: 7px 7px 7px 10px; border-radius: 18px;
          background: var(--findaro-fg); color: var(--findaro-bg); box-shadow: 0 8px 28px rgb(0 0 0 / .2); font-size: 13.5px; }
.seln { flex: 1; display: flex; align-items: center; gap: 8px; font-weight: 600; min-width: 0; }
.thumbs { display: flex; }
.thumbs .img { width: 28px; height: 28px; aspect-ratio: 1; border-radius: 8px; font-size: 11px; border: 2px solid var(--findaro-fg); }
.thumbs .img + .img { margin-left: -8px; }
.selbar button { border: 0; border-radius: 999px; padding: 7px 14px; font-weight: 600; font-size: 13px; color: inherit;
                 background: color-mix(in srgb, currentColor 14%, transparent); }
.selbar button:hover { background: color-mix(in srgb, currentColor 24%, transparent); }
.selbar .pri, .selbar .pri:hover { background: var(--findaro-accent); color: var(--findaro-accent-ink); }
.selbar .pri:disabled { opacity: .45; cursor: default; }
.selbar [aria-pressed="true"] { box-shadow: inset 0 0 0 2px var(--findaro-accent); }

/* empty state */
.hello { display: grid; justify-items: center; align-content: center; text-align: center; gap: 10px; padding: 32px 0 20px;
         min-height: 100%; }
.hello h2 { margin: 8px 0 0; font-size: 26px; line-height: 1.2; letter-spacing: -.01em; }
.hello p { margin: 0; color: var(--findaro-muted); max-width: 460px; }
.starters { display: grid; gap: 8px; width: min(100%, 560px); margin-top: 16px; }

/* layout="page": sidebar + main column */
.root.page { display: grid; grid-template-columns: 280px minmax(0, 1fr); gap: 0; height: 100%; min-height: 440px; }
.page .main { display: grid; grid-template-rows: auto minmax(0, 1fr); min-height: 0; min-width: 0; }
.page .thread-wrap { grid-row: 2; border: 0; border-radius: 0; }
.page .scroll { max-height: none; min-height: 0; padding: 32px max(20px, calc((100% - var(--findaro-page-width)) / 2)) 12px; }
.page .dock { padding: 10px max(16px, calc((100% - var(--findaro-page-width)) / 2)) calc(18px + env(safe-area-inset-bottom, 0px)); }
.side { background: var(--findaro-surface); border-right: 1px solid var(--findaro-border); display: flex; flex-direction: column;
        gap: 14px; padding: 16px 12px; overflow-y: auto; min-height: 0; }
.shead { display: flex; align-items: center; gap: 10px; padding: 2px 6px; font-size: 15px; }
.shead strong { flex: 1; }
.newchat { display: flex; align-items: center; gap: 8px; border: 1px solid var(--findaro-border); background: var(--findaro-bg);
           border-radius: 12px; padding: 10px 14px; font-weight: 600; font-size: 14px; }
.newchat:hover { border-color: var(--findaro-accent); color: var(--findaro-accent); }
.convs { display: grid; gap: 10px; }
.grp h4 { margin: 4px 10px 6px; font-size: 11.5px; text-transform: uppercase; letter-spacing: .06em;
          color: var(--findaro-muted); font-weight: 600; }
.grp ul { list-style: none; margin: 0; padding: 0; display: grid; gap: 2px; }
.ci { display: flex; align-items: center; border-radius: 10px; min-height: 38px; }
.ci:hover, .ci:focus-within, .ci.cur { background: var(--findaro-bg); }
.ci.cur .conv { font-weight: 600; }
.ci .conv { flex: 1; min-width: 0; text-align: left; border: 0; background: none; padding: 8px 10px; font-size: 14px;
            white-space: nowrap; overflow: hidden; text-overflow: ellipsis; border-radius: 10px; }
.ci .del { opacity: 0; width: 30px; height: 30px; }
.ci:hover .del, .ci:focus-within .del { opacity: 1; }
.ci .del .ico { width: 16px; height: 16px; }
.ci.confirm { gap: 6px; padding: 4px 4px 4px 12px; font-size: 13px; background: var(--findaro-bg); }
.ci.confirm span { flex: 1; font-weight: 600; }
.ci.confirm button { border: 0; border-radius: 8px; padding: 5px 10px; font-size: 12.5px; font-weight: 600; }
.danger { background: #dc2626; color: #fff; }
.ci.confirm .cancel { background: var(--findaro-surface); }
.none { color: var(--findaro-muted); font-size: 13px; padding: 0 10px; margin: 0; }
.iconbtn { border: 0; background: none; width: 36px; height: 36px; border-radius: 10px; display: grid; place-items: center;
           color: var(--findaro-muted); flex: none; }
.iconbtn:hover { background: var(--findaro-border); color: var(--findaro-fg); }
.mtop { display: none; align-items: center; gap: 6px; padding: 8px 10px; padding-top: calc(8px + env(safe-area-inset-top, 0px));
        border-bottom: 1px solid var(--findaro-border); }
.mtop strong { flex: 1; text-align: center; }
.sclose, .sscrim { display: none; }

@container (max-width: 1000px) { .tcards { grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; } }
@container (max-width: 760px) {
  .root.page { grid-template-columns: minmax(0, 1fr); }
  .mtop { display: flex; }
  .page .side { position: fixed; top: 0; bottom: 0; left: 0; width: min(310px, 86vw); z-index: 2147482001;
                transform: translateX(-100%); visibility: hidden; transition: transform .2s ease, visibility .2s;
                box-shadow: 8px 0 28px rgb(0 0 0 / .2); }
  .page .side.open { transform: none; visibility: visible; }
  .sclose { display: grid; }
  .sscrim:not([hidden]) { display: block; position: fixed; inset: 0; background: rgb(0 0 0 / .35); z-index: 2147482000; }
  .page .scroll { padding: 20px 14px 8px; }
  .page .dock { padding: 8px 12px calc(12px + env(safe-area-inset-bottom, 0px)); }
  .scroll { padding: 16px 12px 8px; }
  .dock { padding: 8px 10px 12px; }
  .ci .del { opacity: 1; }
  .log .msg.user { max-width: 88%; }
  .hello h2 { font-size: 22px; }
}
@container (max-width: 520px) {
  .tcards { gap: 10px; }
  .pc .body { padding: 8px 10px 0; }
  .acts { padding: 8px 10px 10px; gap: 4px; }
  .act { padding: 5px 8px; font-size: 12px; }
  .sel { top: 6px; left: 6px; padding: 3px 8px 3px 6px; }
  .seln { flex-basis: 100%; padding: 2px 0 4px; }
  .selbar button { flex: 1 1 auto; white-space: nowrap; padding: 7px 10px; }
  .cmp tbody th { white-space: normal; }
  .cmp thead td { width: 104px; }
}
@container (max-width: 330px) { .tcards { grid-template-columns: minmax(0, 1fr); } }
@media (hover: none) { .ci .del { opacity: 1; } }

.typing::after { content: "▍"; animation: blink 1s steps(1) infinite; }
.typing.wait::after { content: none; }
@keyframes blink { 50% { opacity: 0; } }
@media (prefers-reduced-motion: reduce) {
  .typing::after, .dots i { animation: none; }
  .page .side, .nrow .ico, .how summary .ico, .pc, .composer { transition: none; }
}
`;
