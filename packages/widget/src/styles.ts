/** Shadow-DOM styles. Theme with CSS variables on the host page, e.g. zerch-search { --zerch-accent: #e05a00 } */
export const CSS = `
:host {
  --zerch-accent: #ff6a00;
  --zerch-accent-ink: #ffffff;
  --zerch-bg: #ffffff;
  --zerch-surface: #f6f6f7;
  --zerch-fg: #1d1d1f;
  --zerch-muted: #6b6b70;
  --zerch-border: #e3e3e6;
  --zerch-chip-bg: #fff3ea;
  --zerch-chip-fg: #a34300;
  --zerch-good: #12805c;
  --zerch-warn: #9a6200;
  --zerch-radius: 12px;
  --zerch-font: system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
  --zerch-card-min: 150px;
  display: block;
  color: var(--zerch-fg);
  font: 15px/1.45 var(--zerch-font);
  container-type: inline-size;
}
@media (prefers-color-scheme: dark) {
  :host(:not([theme="light"])) {
    --zerch-bg: #161618; --zerch-surface: #1f1f22; --zerch-fg: #ececef; --zerch-muted: #a0a0a8;
    --zerch-border: #34343a; --zerch-chip-bg: #3a2414; --zerch-chip-fg: #ffb27a; --zerch-good: #4fd1a1;
    --zerch-warn: #f0c060;
  }
}
:host([theme="dark"]) {
  --zerch-bg: #161618; --zerch-surface: #1f1f22; --zerch-fg: #ececef; --zerch-muted: #a0a0a8;
  --zerch-border: #34343a; --zerch-chip-bg: #3a2414; --zerch-chip-fg: #ffb27a; --zerch-good: #4fd1a1;
  --zerch-warn: #f0c060;
}
* { box-sizing: border-box; }
[hidden] { display: none !important; }
.root { background: var(--zerch-bg); display: grid; gap: 12px; }
button { font: inherit; color: inherit; cursor: pointer; }
:focus-visible { outline: 2px solid var(--zerch-accent); outline-offset: 2px; }
.sr { position: absolute; width: 1px; height: 1px; overflow: hidden; clip: rect(0 0 0 0); white-space: nowrap; }

.bar { display: flex; flex-wrap: wrap; gap: 8px; align-items: stretch; }
.modes { display: inline-flex; border: 1px solid var(--zerch-border); border-radius: 999px; padding: 3px;
         background: var(--zerch-surface); }
.modes button { border: 0; background: none; padding: 6px 14px; border-radius: 999px; font-weight: 600;
                font-size: 14px; color: var(--zerch-muted); }
.modes button[aria-checked="true"] { background: var(--zerch-accent); color: var(--zerch-accent-ink); }
.box { flex: 1 1 260px; display: flex; min-width: 0; border: 2px solid var(--zerch-accent);
       border-radius: 999px; overflow: hidden; background: var(--zerch-bg); }
.box input { flex: 1; min-width: 0; border: 0; padding: 10px 16px; font: inherit; color: var(--zerch-fg);
             background: transparent; }
.box input:focus { outline: none; }
.box:focus-within { box-shadow: 0 0 0 3px color-mix(in srgb, var(--zerch-accent) 25%, transparent); }
.go { border: 0; background: var(--zerch-accent); color: var(--zerch-accent-ink); padding: 0 20px;
      font-weight: 700; }

.row { display: flex; flex-wrap: wrap; gap: 6px; align-items: center; }
.row-label { font-size: 12px; text-transform: uppercase; letter-spacing: .06em; color: var(--zerch-muted);
             margin-right: 4px; }
.chip { display: inline-flex; align-items: center; gap: 4px; padding: 4px 6px 4px 12px; border-radius: 999px;
        background: var(--zerch-chip-bg); color: var(--zerch-chip-fg); font-size: 14px; font-weight: 600;
        border: 1px solid transparent; }
.chip.boost, .chip.sort { background: transparent; border-color: var(--zerch-chip-fg); }
.chip button { border: 0; background: none; color: inherit; width: 22px; height: 22px; border-radius: 50%;
               line-height: 1; font-size: 16px; }
.chip button:hover { background: color-mix(in srgb, currentColor 15%, transparent); }
.pills { display: grid; gap: 6px; }
.pill { border: 1px solid var(--zerch-border); background: var(--zerch-surface); border-radius: 999px;
        padding: 4px 12px; font-size: 13px; }
.pill:hover { border-color: var(--zerch-accent); }
.pill small { color: var(--zerch-muted); margin-left: 4px; }

.layout { display: grid; gap: 16px; }
@container (min-width: 760px) { .layout.ai { grid-template-columns: minmax(280px, 380px) 1fr; } }
.status { font-size: 13px; color: var(--zerch-muted); min-height: 1.2em; }
.status.weak { color: var(--zerch-warn); }

.grid { list-style: none; margin: 0; padding: 0; display: grid; gap: 12px;
        grid-template-columns: repeat(auto-fill, minmax(var(--zerch-card-min), 1fr)); }
.card { display: flex; flex-direction: column; height: 100%; text-decoration: none; color: inherit;
        border: 1px solid var(--zerch-border); border-radius: var(--zerch-radius); overflow: hidden;
        background: var(--zerch-bg); text-align: left; padding: 0; width: 100%; }
.card:hover { border-color: var(--zerch-accent); }
.img { aspect-ratio: 1; width: 100%; object-fit: cover; background: var(--zerch-surface); display: grid;
       place-items: center; font-size: 28px; font-weight: 700; color: var(--zerch-muted); }
.body { padding: 8px 10px 10px; display: grid; gap: 4px; }
.title { font-size: 14px; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical;
         overflow: hidden; }
.price { font-weight: 700; font-size: 16px; }
.mrp { color: var(--zerch-muted); text-decoration: line-through; font-weight: 400; font-size: 13px;
       margin-left: 6px; }
.meta { font-size: 12px; color: var(--zerch-muted); display: flex; gap: 8px; flex-wrap: wrap; }
.badge { font-size: 11px; font-weight: 700; color: var(--zerch-warn); }

.empty { border: 1px dashed var(--zerch-border); border-radius: var(--zerch-radius); padding: 24px;
         text-align: center; color: var(--zerch-muted); }
.empty strong { display: block; color: var(--zerch-fg); margin-bottom: 4px; }

.panel { border: 1px solid var(--zerch-border); border-radius: var(--zerch-radius); background: var(--zerch-surface);
         padding: 12px; display: grid; gap: 10px; align-content: start; max-height: 70vh; overflow: auto; }
.msg { display: grid; gap: 6px; }
.msg .who { font-size: 12px; font-weight: 700; color: var(--zerch-muted); }
.msg.user .text { background: var(--zerch-bg); border: 1px solid var(--zerch-border); border-radius: 10px;
                  padding: 6px 10px; justify-self: end; }
.msg .text { white-space: pre-wrap; }
.mini { display: inline-flex; align-items: center; gap: 6px; vertical-align: middle; max-width: 100%;
        border: 1px solid var(--zerch-border); background: var(--zerch-bg); border-radius: 8px; padding: 2px 8px 2px 2px;
        font-size: 13px; margin: 2px 0; text-decoration: none; color: inherit; }
.mini .img { width: 28px; height: 28px; font-size: 13px; border-radius: 6px; }
.mini span { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; max-width: 220px; }
.clarify { display: grid; gap: 6px; }
.clarify p { margin: 0; font-weight: 600; }
.typing::after { content: "▍"; animation: blink 1s steps(1) infinite; }
@keyframes blink { 50% { opacity: 0; } }
@media (prefers-reduced-motion: reduce) { .typing::after { animation: none; } }
`;
