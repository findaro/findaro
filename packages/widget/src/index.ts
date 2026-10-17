/**
 * <findaro-search>: drop-in AI search widget (Web Component, Shadow DOM, no framework).
 *
 *   <script src="findaro-widget.js" data-project="prj_…" data-key="fdr_search_…" data-base-url="…" defer></script>
 *   <findaro-search></findaro-search>
 *
 * Attributes (override the script tag): project, key, base-url, mode ("search" | "ai"), layout ("page": full-page
 * AI Mode with chat history; with mode="search", a full-page search view), locale ("en" | "hi-en"), placeholder, size,
 * theme ("light" | "dark"),
 * starters ("a|b|c"), badges ("field,field"), card-actions ("Add to cart,Save").
 * Properties: renderProduct, onProductClick, cardActions, strings, client.
 * Events: "findaro:product-click" (cancelable), "findaro:action" (cancelable), "findaro:results", "findaro:error".
 * Slots (layout="page"): "sidebar-footer", shown at the bottom of the chat history sidebar.
 */
import {
  createClient,
  debounce,
  type ChatEvent,
  type Chip,
  type ClarifyChip,
  type ClarifyEvent,
  type Display,
  type Hit,
  type PatchOp,
  type Pill,
  type SearchResponse,
  type FindaroClient,
} from "@findaro/sdk";

import { h, hhmm, icon, safeUrl, secs } from "./dom";
import { loadChats, saveChats, slimTurn, type Conv, type Turn } from "./history";
import { STRINGS, fmt, type Strings } from "./strings";
import { CSS } from "./styles";

export type RenderProduct = (hit: Hit, ctx: { display: Display; formatPrice: (v: unknown) => string }) =>
  HTMLElement | string;
export type ProductClick = (hit: Hit, event: Event) => void;
/** A button on each AI Mode product card. Clicking dispatches "findaro:action"; onClick runs unless it's canceled. */
export interface CardAction {
  label: string;
  onClick?: (hit: Hit) => void;
}

interface View {
  total: number;
  hits: Hit[];
  chips: Chip[];
  pills: Pill[];
  quality: string | null;
  close: Set<string>;
  display: Display;
  semantic: string;
}
/** product drawer messages */
interface Msg {
  role: "user" | "assistant";
  text: string;
  general?: string;
  pending?: boolean;
}

const SCRIPT_DEFAULTS: Record<string, string> = {};
{
  const s = (typeof document !== "undefined" ? document.currentScript : null) as HTMLScriptElement | null;
  if (s?.dataset) {
    const d = s.dataset;
    for (const [k, v] of Object.entries({ project: d.project, key: d.key, "base-url": d.baseUrl, locale: d.locale,
      mode: d.mode, layout: d.layout, starters: d.starters, badges: d.badges, "card-actions": d.cardActions })) {
      if (v) SCRIPT_DEFAULTS[k] = v;
    }
  }
}

const EMPTY_DISPLAY: Display = {};
const MAX_SELECT = 3; // the chat API answers about at most 3 products at once
const FIRST_CARDS = 6;
const SIDE_KEY = "findaro:side-collapsed"; // layout="page": the desktop sidebar's collapsed state, per browser
const list = (v: string | null, sep: string) => (v || "").split(sep).map((t) => t.trim()).filter(Boolean);

export class FindaroSearch extends HTMLElement {
  static observedAttributes = ["mode", "locale", "placeholder", "project", "key", "base-url", "layout", "starters",
    "badges", "card-actions"];

  /** Custom product card. Return an element, or an HTML string (escape document fields yourself: they are data). */
  renderProduct: RenderProduct | null = null;
  /** Called on product click; navigation to the product URL is skipped when set. */
  onProductClick: ProductClick | null = null;
  /** Extra buttons on AI Mode product cards (after the ones from the card-actions attribute). */
  cardActions: CardAction[] = [];
  /** Partial string overrides, merged over the locale's defaults. */
  strings: Partial<Strings> = {};
  /** Inject a preconfigured client (e.g. with a custom fetch). */
  client: FindaroClient | null = null;

  #root: ShadowRoot;
  #mode: "search" | "ai" = "search";
  #page = false;
  #query = "";
  #patches: PatchOp[] = [];
  #view: View | null = null;
  #loading = false;
  #error = "";
  #session: string | null = null;
  #msgs: Turn[] = [];
  #docs = new Map<string, Hit>();
  #display: Display = EMPTY_DISPLAY;
  #input!: HTMLInputElement;
  #ta!: HTMLTextAreaElement;
  #debounced = debounce(() => this.#runSearch(), 250);

  constructor() {
    super();
    this.#root = this.attachShadow({ mode: "open" });
  }

  connectedCallback() {
    this.#page = this.#attr("layout") === "page";
    this.#mode = this.#wantMode();
    this.#build();
    this.#render();
  }

  attributeChangedCallback(name: string) {
    if (!this.isConnected || !this.#input) return;
    if (name === "layout") {
      this.connectedCallback();
      return;
    }
    if (name === "mode") this.#setMode(this.#wantMode());
    else if (["project", "key", "base-url"].includes(name)) {
      this.client = null;
      this.#chats = null;
    } else if (["starters", "badges", "card-actions"].includes(name)) this.#dirty = true;
    this.#render();
  }

  /** Run a search (or ask the AI in "ai" mode) programmatically. */
  search(query: string) {
    if (this.#mode === "ai") {
      if (query.trim()) this.#ask(query.trim());
      return;
    }
    this.#input.value = query;
    this.#submit();
  }

  get #s(): Strings {
    const base = STRINGS[this.#attr("locale") || "en"] || STRINGS.en;
    return { ...base, ...this.strings };
  }

  /** layout="page" is AI Mode unless mode="search" is set explicitly; otherwise search unless mode="ai". */
  #wantMode(): "search" | "ai" {
    const m = this.#attr("mode");
    return m === "ai" || this.#page && m !== "search" ? "ai" : "search";
  }

  #attr(name: string): string | null {
    return this.getAttribute(name) ?? SCRIPT_DEFAULTS[name] ?? null;
  }

  #client(): FindaroClient {
    if (!this.client) {
      const key = this.#attr("key");
      if (!key || /^YOUR_/i.test(key)) {
        throw new Error("findaro-search: set data-key on the script tag (or key=…) to your project's search key");
      }
      this.client = createClient({ projectId: this.#attr("project") || "", searchKey: key,
                                   baseUrl: this.#attr("base-url") || undefined });
    }
    return this.client;
  }

  get #disp(): Display {
    return this.#view?.display && Object.keys(this.#view.display).length ? this.#view.display : this.#display;
  }

  // --- layout -------------------------------------------------------------------------------------------

  #els: Record<string, HTMLElement> = {};

  #build() {
    const s = this.#s;
    this.#root.innerHTML = "";
    this.#root.append(h("style", {}, CSS));
    this.#input = h("input", {
      type: "search", "aria-label": s.placeholder, autocomplete: "off", enterkeyhint: "search",
      oninput: () => this.#onInput(), onkeydown: (e: KeyboardEvent) => this.#onKey(e),
    });
    const modeBtn = (m: "search" | "ai", label: string) =>
      h("button", { type: "button", role: "radio", "data-mode": m, onclick: () => this.#setMode(m, true) }, label);
    this.#els.modes = h("div", { class: "modes", role: "radiogroup", "aria-label": s.modeLabel },
      modeBtn("search", s.search), modeBtn("ai", s.ask));
    this.#els.go = h("button", { class: "go", type: "submit" }, s.search);
    this.#els.form = h("form", { class: "box", role: "search", onsubmit: (e: Event) => {
      e.preventDefault();
      this.#submit();
    } }, this.#els.modes, this.#input, this.#els.go);
    this.#els.chips = h("div", { class: "row chips", role: "group" });
    this.#els.pills = h("div", { class: "pills", id: "findaro-filters" });
    this.#els.status = h("div", { class: "status", role: "status", "aria-live": "polite" });
    this.#els.results = h("div", {});
    this.#els.searchView = h("section", { "aria-label": s.products }, this.#els.status, this.#els.results);

    // AI Mode thread: scrollable log + sticky dock (selection bar, current filters, composer)
    this.#els.log = h("div", { class: "log", role: "log", "aria-live": "polite", "aria-label": s.conversation });
    this.#els.hello = h("div", { class: "hello" });
    const sc = this.#els.scroll = h("div", { class: "scroll", onscroll: () => this.#onScroll() },
      this.#els.hello, this.#els.log);
    for (const ev of ["wheel", "touchmove", "keydown", "pointerdown"]) {
      sc.addEventListener(ev, () => (this.#pin = false), { passive: true });
    }
    this.#ta = h("textarea", { rows: 1, enterkeyhint: "send", oninput: () => this.#grow(),
                               onkeydown: (e: KeyboardEvent) => this.#onComposerKey(e) });
    this.#els.send = h("button", { class: "send", type: "submit", "aria-label": s.send, disabled: true }, icon("send"));
    this.#els.composer = h("form", { class: "composer", onsubmit: (e: Event) => {
      e.preventDefault();
      this.#sendComposer();
    } }, this.#ta, this.#els.send);
    this.#els.selbar = h("div", { class: "selbar", role: "group", "aria-label": s.compare });
    this.#els.notice = h("div", { class: "notice", "aria-live": "polite" });
    this.#els.jump = h("button", { class: "jump", type: "button", "aria-label": s.jumpLatest, title: s.jumpLatest,
                                   hidden: true, onclick: () => this.#toBottom(true) }, icon("down"));
    this.#els.starters = h("div", { class: "starters", role: "group", "aria-label": s.tryAsking });
    this.#els.dock = h("div", { class: "dock" }, this.#els.jump, this.#els.notice, this.#els.selbar,
      this.#els.composer, this.#els.starters);
    this.#els.thread = h("div", { class: "thread-wrap" }, sc, this.#els.dock);

    if (this.#page) {
      this.#els.side = h("aside", { class: "side", id: "findaro-side", "aria-label": s.history });
      this.#els.menu = h("button", { class: "iconbtn", type: "button", "aria-label": s.openHistory,
                                     title: s.openHistory, "aria-controls": "findaro-side", "aria-expanded": "false",
                                     onclick: () => this.#narrow() ? this.#toggleSide(true) : this.#collapse(false) },
        icon("menu"));
      this.#els.sscrim = h("div", { class: "sscrim", hidden: true, onclick: () => this.#toggleSide(false) });
      const slot = h("slot", { name: "sidebar-footer", onslotchange: () => {
        this.#els.sfoot.hidden = !slot.assignedNodes().length;
      } });
      this.#els.sfoot = h("div", { class: "sfoot", hidden: true }, slot);
      const top = h("div", { class: "mtop" }, this.#els.menu, h("strong", {}, s.assistantName),
        h("button", { class: "iconbtn", type: "button", "aria-label": s.newChat, title: s.newChat,
                      onclick: () => this.#newChat() }, icon("plus")));
      // mode="search" in a page: the search box, chips, filters and grid in one centered column
      this.#els.spage = h("div", { class: "spage" }, h("div", { class: "sin" }, this.#els.form, this.#els.chips,
        this.#els.pills, this.#els.searchView));
      this.#els.root = h("div", { class: `root page${this.#collapsed ? " collapsed" : ""}`, part: "root",
                                  onkeydown: (e: KeyboardEvent) => {
        if (e.key === "Escape" && this.#sideOpen) this.#toggleSide(false);
      } }, this.#els.side, this.#els.sscrim, h("div", { class: "main" }, top, this.#els.thread, this.#els.spage));
      this.#root.append(this.#els.root);
    } else {
      this.#els.layout = h("div", { class: "layout" }, this.#els.thread, this.#els.searchView);
      this.#root.append(h("div", { class: "root", part: "root" },
        this.#els.form, this.#els.chips, this.#els.pills, this.#els.layout));
    }
    this.#dirty = true;
  }

  #setMode(m: "search" | "ai", focus = false) {
    if (m === this.#mode && this.#els.layout) {
      if (focus) (m === "ai" ? this.#ta : this.#input).focus();
      return;
    }
    this.#mode = m;
    this.#dirty = true;
    this.#render();
    if (focus) (m === "ai" ? this.#ta : this.#input).focus();
  }

  #typing = false; // search-as-you-type: rules only, no LLM planner call per keystroke

  #onInput() {
    if (this.#mode !== "search") return;
    const q = this.#input.value.trim();
    if (q !== this.#query) this.#patches = [];
    this.#query = q;
    this.#typing = true;
    if (q.length >= 2) this.#debounced();
  }

  #onKey(e: KeyboardEvent) {
    if (e.key === "Escape") {
      this.#input.value = "";
      this.#query = "";
      this.#patches = [];
      this.#view = null;
      this.#render();
    }
  }

  #submit() {
    const q = this.#input.value.trim();
    if (!q) return;
    if (this.#mode === "ai") {
      this.#input.value = "";
      this.#ask(q);
    } else {
      this.#debounced.cancel();
      if (q !== this.#query) this.#patches = [];
      this.#query = q;
      this.#typing = false;
      this.#runSearch();
    }
  }

  // --- search -------------------------------------------------------------------------------------------

  async #runSearch() {
    if (!this.#query) return;
    this.#loading = true;
    this.#error = "";
    this.#renderStatus();
    try {
      const res = await this.#client().search({ query: this.#query, patch: this.#patches, llm: !this.#typing,
                                                size: Number(this.#attr("size")) || 20 });
      this.#setView(res);
    } catch (e) {
      if ((e as Error).name === "AbortError") return;
      this.#fail(e);
    } finally {
      this.#loading = false;
      this.#render();
    }
  }

  #setView(res: SearchResponse) {
    const und = res.understood;
    this.#view = {
      total: res.total, hits: res.hits, chips: und?.chips ?? [], pills: res.pills ?? [],
      quality: und?.match_quality ?? null, close: new Set(und?.close_matches ?? []),
      display: res.display ?? EMPTY_DISPLAY, semantic: und?.semantic_text ?? res.query,
    };
    for (const hit of res.hits) this.#docs.set(hit.id, hit);
    this.dispatchEvent(new CustomEvent("findaro:results", { detail: res, bubbles: true, composed: true }));
  }

  #applyPatch(ops: PatchOp[], label: string) {
    if (this.#mode === "ai" && this.#session) {
      this.#ask(label, ops);
      return;
    }
    this.#patches = [...this.#patches, ...ops];
    this.#runSearch();
  }

  #fail(e: unknown) {
    const msg = e instanceof Error ? e.message : "";
    // setup problems are shown as-is so the page owner sees what to fix; everything else gets the friendly string
    this.#error = msg.startsWith("findaro-search:") || (e as { status?: number })?.status === 401
      ? (msg.startsWith("findaro-search:") ? msg : "findaro-search: invalid search key (check data-key)")
      : this.#s.error;
    this.dispatchEvent(new CustomEvent("findaro:error", { detail: e, bubbles: true, composed: true }));
  }

  // --- chat ---------------------------------------------------------------------------------------------

  #lastAsked = "";

  async #ask(message: string, patch?: PatchOp[], retried = false,
             opts: { productIds?: string[]; compare?: Hit[] } = {}): Promise<void> {
    const s = this.#s;
    if (!patch && !opts.productIds) this.#lastAsked = message;
    let expired = false;
    const user: Turn = { role: "user", text: message, time: Date.now(), ...(patch ? { patch: true } : {}) };
    const bot: Turn = { role: "assistant", text: "", general: "", time: Date.now(), pending: true, clarify: null,
                        step: s.stepThink, compare: opts.compare ?? null };
    const prev = this.#msgs[this.#msgs.length - 1];
    this.#msgs.push(user, bot);
    this.#pin = true;
    if (this.#mode === "ai") {
      if (this.#dirty) this.#renderThread();
      else {
        if (prev) this.#paint(prev); // its next-step rows go away
        this.#paint(user);
        this.#paint(bot);
      }
      this.#renderHello();
    }
    this.#saveConv();
    let sem = message;
    try {
      const stream = this.#client().chat(patch ? "" : message, { sessionId: this.#session, patch,
                                                                 productIds: opts.productIds });
      for await (const ev of stream as AsyncIterable<ChatEvent>) {
        if (ev.type === "session") {
          this.#session = ev.data.session_id;
          bot.step = s.stepUnderstand;
        } else if (ev.type === "plan") {
          const u = ev.data.understood;
          if (u) {
            sem = u.semantic_text || message;
            bot.plan = { chips: (u.chips ?? []).map((c) => c.label),
                         relax: (u.relaxations ?? []).map((r) => [r.label, r.reason] as [string, string]) };
            bot.step = fmt(s.stepSearch, { q: sem });
            if (this.#view) this.#view.chips = u.chips ?? [];
            else {
              this.#view = { total: 0, hits: [], pills: [], quality: null, close: new Set(), display: this.#display,
                             chips: u.chips ?? [], semantic: sem };
            }
          }
        } else if (ev.type === "results" && !ev.data.unchanged) {
          const prevView = this.#view;
          const display = ev.data.display ?? prevView?.display ?? this.#display;
          if (ev.data.display) this.#display = ev.data.display;
          this.#view = {
            total: ev.data.total, hits: ev.data.items, pills: ev.data.pills ?? [],
            chips: prevView?.chips ?? [], quality: ev.data.match_quality ?? null,
            close: new Set(ev.data.close_matches ?? []), display, semantic: sem,
          };
          for (const hit of ev.data.items) this.#docs.set(hit.id, hit);
          if (bot.plan) {
            bot.res = { q: sem, total: ev.data.total, hits: ev.data.items, close: ev.data.close_matches ?? [],
                        weak: ev.data.match_quality === "weak" };
            bot.step = fmt(s.stepFound, { n: ev.data.total });
          }
          this.#renderResults();
        } else if (ev.type === "clarify") bot.clarify = ev.data;
        else if (ev.type === "text") {
          if (ev.data.part === "general") bot.general += ev.data.delta;
          else bot.text += ev.data.delta;
        } else if (ev.type === "done") {
          bot.pending = false;
          bot.ms = ev.data.timings?.total ?? null;
          expired = ev.data.reason === "session_expired";
        }
        this.#renderChips();
        this.#paint(bot);
      }
    } catch (e) {
      if ((e as Error).name !== "AbortError") {
        bot.error = true;
        bot.text = s.error;
        this.#fail(e);
      }
    } finally {
      bot.pending = false;
      this.#paint(bot);
      this.#render();
    }
    if (expired && patch && !retried && this.#lastAsked) {
      // the chat session timed out: drop the empty turn, ask the last question again, then apply the click
      this.#msgs.splice(-2, 2);
      this.#session = null;
      this.#dirty = true;
      this.#render();
      await this.#ask(this.#lastAsked);
      await this.#ask(message, patch, true);
      return;
    }
    this.#saveConv();
  }

  // --- rendering ----------------------------------------------------------------------------------------

  #dirty = true; // the thread must be rebuilt (mode/layout/conversation changed)

  #render() {
    const s = this.#s;
    const ai = this.#mode === "ai";
    for (const b of this.#els.modes.querySelectorAll("button")) {
      b.setAttribute("aria-checked", String(b.dataset.mode === this.#mode));
    }
    this.#input.placeholder = this.#attr("placeholder") || s.placeholder;
    this.#input.setAttribute("aria-label", this.#input.placeholder);
    this.#els.go.textContent = s.search;
    this.#input.hidden = this.#els.go.hidden = ai;
    this.#els.form.classList.toggle("solo", ai);
    this.#els.thread.hidden = !ai;
    this.#els.searchView.hidden = ai;
    if (this.#page) {
      this.#els.spage.hidden = ai;
      this.#els.root.classList.toggle("search", !ai);
    }
    // the current understood chips: under the search box, or above the composer in AI Mode
    if (ai) this.#els.dock.insertBefore(this.#els.chips, this.#els.composer);
    else this.#els.form.after(this.#els.chips);
    this.#renderChips();
    this.#renderStatus();
    this.#renderResults();
    if (ai) {
      if (this.#dirty) this.#renderThread();
      this.#renderDock();
      this.#renderSide();
    }
  }

  #filtersOpen = false;

  #renderChips() {
    const s = this.#s;
    const v = this.#view;
    const chips = v?.chips ?? [];
    const pills = v?.pills ?? [];
    const canFilter = this.#mode === "search" && !!pills.length && !!v?.hits.length;
    this.#els.chips.replaceChildren();
    this.#els.chips.hidden = !chips.length && !canFilter;
    this.#els.chips.setAttribute("aria-label", s.understood);
    for (const c of chips) {
      this.#els.chips.append(h("span", { class: `chip ${c.kind}`, title: c.source || undefined }, c.label,
        h("button", { type: "button", "aria-label": fmt(s.removeFilter, { label: c.label }),
                      onclick: () => this.#applyPatch(c.remove ?? [], `− ${c.label}`) }, "×")));
    }
    if (canFilter) {
      this.#els.chips.append(h("button", {
        type: "button", class: "filters-toggle", "aria-expanded": String(this.#filtersOpen),
        "aria-controls": "findaro-filters", onclick: () => {
          this.#filtersOpen = !this.#filtersOpen;
          this.#renderChips();
        },
      }, this.#filtersOpen ? `${s.refine} ▴` : `${s.refine} ▾`));
    }
    this.#els.pills.replaceChildren();
    this.#els.pills.hidden = !canFilter || !this.#filtersOpen;
    for (const p of pills) {
      const row = h("div", { class: "row", role: "group", "aria-label": `${s.refine}: ${p.label}` },
        h("span", { class: "row-label", "aria-hidden": "true" }, p.label));
      for (const val of p.values) {
        row.append(h("button", { type: "button", class: "pill", onclick: () => this.#applyPatch(val.patch, val.label) },
          val.label, h("small", { "aria-hidden": "true" }, String(val.count))));
      }
      this.#els.pills.append(row);
    }
  }

  #renderStatus() {
    const s = this.#s;
    const v = this.#view;
    const st = this.#els.status;
    st.className = "status";
    if (this.#error) st.textContent = this.#error;
    else if (this.#loading) st.textContent = s.loading;
    else if (!v) st.textContent = "";
    else if (v.quality === "weak") {
      st.textContent = s.weak;
      st.classList.add("weak");
    } else if (v.close.size) {
      st.textContent = fmt(s.withClose, { n: v.hits.length - v.close.size, c: v.close.size });
    } else st.textContent = v.hits.length ? fmt(s.results, { n: v.total }) : "";
  }

  #renderResults() {
    const s = this.#s;
    const v = this.#view;
    const box = this.#els.results;
    box.replaceChildren();
    if (!v || this.#mode === "ai") return;
    if (!v.hits.length) {
      box.append(h("div", { class: "empty", "data-state": "no-match" },
        h("strong", {}, fmt(s.noMatch, { q: this.#query || v.semantic })), s.noMatchHint));
      return;
    }
    const grid = h("ul", { class: "grid", role: "list" });
    for (const hit of v.hits) {
      grid.append(h("li", { class: "cell" }, this.#card(hit, v.close),
        h("button", { type: "button", class: "ask", "data-ask": hit.id,
                      "aria-label": fmt(s.askAbout, { title: this.#title(hit) }),
                      onclick: (e: Event) => this.#openDrawer(hit, e.currentTarget as HTMLElement) }, s.askShort)));
    }
    box.append(grid);
  }

  #formatPrice = (value: unknown): string => {
    const n = typeof value === "number" ? value : Number(value);
    if (!Number.isFinite(n)) return value == null ? "" : String(value);
    const cur = this.#disp.currency;
    try {
      return new Intl.NumberFormat(cur === "INR" ? "en-IN" : undefined, cur
        ? { style: "currency", currency: cur, maximumFractionDigits: n % 1 ? 2 : 0 }
        : { maximumFractionDigits: 2 }).format(n);
    } catch {
      return String(n);
    }
  };

  #title(hit: Hit): string {
    const d = this.#disp;
    return String((d.title && (hit.document as Record<string, unknown>)[d.title]) ?? hit.id);
  }

  #image(src: unknown, alt: string): HTMLElement {
    let hue = 0;
    for (const ch of alt) hue = (hue * 31 + ch.charCodeAt(0)) % 360;
    const fallback = () => h("div", { class: "img ph", "aria-hidden": "true", style: `--h:${hue}` },
      (alt.trim()[0] || "?").toUpperCase());
    if (typeof src !== "string" || !src || !/^(https?:)?\/\//i.test(src) && !src.startsWith("/")) return fallback();
    const img = h("img", { class: "img", src, alt: "", loading: "lazy", decoding: "async" });
    img.addEventListener("error", () => img.replaceWith(fallback()), { once: true });
    return img;
  }

  #click(hit: Hit, e: Event) {
    const ev = new CustomEvent("findaro:product-click", { detail: { hit }, bubbles: true, composed: true,
                                                        cancelable: true });
    const allowed = this.dispatchEvent(ev);
    if (this.onProductClick) {
      e.preventDefault();
      this.onProductClick(hit, e);
    } else if (!allowed) e.preventDefault();
  }

  /** The product card (search grid and AI Mode). `extra` goes at the end of the card body. */
  #card(hit: Hit, close: Set<string> | string[], extra: (Node | null)[] = []): HTMLElement {
    const d = this.#disp;
    const doc = hit.document as Record<string, unknown>;
    if (this.renderProduct) {
      const out = this.renderProduct(hit, { display: d, formatPrice: this.#formatPrice });
      if (typeof out !== "string") return out;
      const wrap = h("div", {});
      wrap.innerHTML = out;
      return wrap;
    }
    const s = this.#s;
    const title = this.#title(hit);
    const url = safeUrl(d.url ? doc[d.url] : null);
    const price = d.price ? doc[d.price] : undefined;
    const mrp = d.compare_at_price ? doc[d.compare_at_price] : undefined;
    const rating = d.rating ? doc[d.rating] : undefined;
    const count = d.rating_count ? doc[d.rating_count] : undefined;
    const stock = d.in_stock ? doc[d.in_stock] : undefined;
    const isClose = Array.isArray(close) ? close.includes(hit.id) : close.has(hit.id);
    const body = h("div", { class: "body" },
      isClose ? h("span", { class: "badge" }, s.close) : null,
      h("span", { class: "title" }, title),
      ...extra.slice(0, 1),
      price != null ? h("span", { class: "price" }, this.#formatPrice(price),
        mrp != null && Number(mrp) > Number(price) ? h("span", { class: "mrp" }, this.#formatPrice(mrp)) : null) : null,
      h("span", { class: "meta" },
        rating != null ? h("span", {}, `★ ${rating}${count != null ? ` (${count})` : ""}`) : null,
        stock === false ? h("span", { class: "oos" }, s.outOfStock) : null),
      ...extra.slice(1));
    const attrs = { class: "card", "data-id": hit.id, onclick: (e: Event) => this.#click(hit, e) };
    return url
      ? h("a", { ...attrs, href: url, target: "_blank", rel: "noopener" }, this.#image(d.image ? doc[d.image] : null, title), body)
      : h("button", { ...attrs, type: "button" }, this.#image(d.image ? doc[d.image] : null, title), body);
  }

  #mini(id: string): HTMLElement | string {
    const hit = this.#docs.get(id);
    if (!hit) return `[${id}]`;
    const d = this.#disp;
    const doc = hit.document as Record<string, unknown>;
    const title = this.#title(hit);
    const price = d.price ? doc[d.price] : undefined;
    return h("button", { type: "button", class: "mini", "data-id": id, onclick: (e: Event) => this.#click(hit, e) },
      this.#image(d.image ? doc[d.image] : null, title),
      h("span", {}, title + (price != null ? ` · ${this.#formatPrice(price)}` : "")));
  }

  // --- AI Mode thread -------------------------------------------------------------------------------------

  #painted = new WeakMap<Turn, HTMLElement>();
  #resEl = new WeakMap<Turn, HTMLElement>();
  #pin = true; // keep the latest turn in view until the shopper scrolls

  #renderThread() {
    this.#dirty = false;
    this.#els.log.replaceChildren();
    for (const m of this.#msgs) this.#els.log.append(this.#paintEl(m));
    this.#renderHello();
  }

  /** Re-render one message in place (cards are kept, so images don't reload while text streams). */
  #paint(m: Turn) {
    if (this.#mode !== "ai" || this.#dirty) return;
    const old = this.#painted.get(m);
    const el = this.#paintEl(m);
    if (old?.parentNode === this.#els.log) old.replaceWith(el);
    else this.#els.log.append(el);
    this.#follow(m);
  }

  #paintEl(m: Turn): HTMLElement {
    const s = this.#s;
    let el: HTMLElement;
    if (m.role === "user") {
      el = h("div", { class: "msg user" }, h("span", { class: "sr" }, s.you), h("div", { class: "text" }, m.text));
    } else {
      const last = m === this.#msgs[this.#msgs.length - 1];
      const waiting = !!m.pending && !m.text;
      const text = h("div", { class: `text${m.pending ? " typing" : ""}${waiting ? " wait" : ""}` });
      for (const part of m.text.split(/(\[[^\]\s]+\])/)) { // [ID] citations become inline product cards
        const id = /^\[([^\]\s]+)\]$/.exec(part)?.[1];
        text.append(id ? this.#mini(id) : part);
      }
      if (waiting) {
        text.append(h("span", { class: "step" }, m.step || s.stepThink,
          h("span", { class: "dots", "aria-hidden": "true" }, h("i"), h("i"), h("i"))));
      }
      el = h("div", { class: `msg assistant${m.error ? " err" : ""}` },
        h("div", { class: "ahead" }, h("span", { class: "avatar" }, icon("spark")), h("strong", {}, s.assistantName),
          h("time", { datetime: new Date(m.time).toISOString() }, hhmm(m.time))),
        m.plan ? this.#how(m) : null,
        m.compare?.length ? this.#compareTable(m.compare) : null,
        text,
        m.general?.trim() ? h("div", { class: "general" }, h("span", { class: "who" }, s.generalLabel),
          m.general.trim()) : null,
        m.res ? this.#resultsBlock(m) : null,
        m.clarify && last && !m.pending ? this.#clarifyBlock(m.clarify) : null);
    }
    this.#painted.set(m, el);
    return el;
  }

  /** "How I searched": what the search understood, what it loosened, how many results, how long. */
  #how(m: Turn): HTMLElement {
    const s = this.#s;
    const p = m.plan!;
    const d = h("details", { class: "how" });
    d.open = !!m.open;
    d.addEventListener("toggle", () => (m.open = d.open));
    const line = (label: string, ...kids: (Node | string)[]) =>
      h("div", { class: "how-r" }, h("span", { class: "how-k" }, label), h("span", { class: "how-v" }, ...kids));
    d.append(
      h("summary", {}, icon("chev"), h("span", { class: "how-t" }, s.howSearched),
        m.ms != null ? h("span", { class: "how-m" }, fmt(s.searchedIn, { t: secs(m.ms) })) : null),
      h("div", { class: "how-b" },
        line(s.understood, ...(p.chips.length ? p.chips.map((c) => h("span", { class: "uchip" }, c)) : [s.byMeaning])),
        ...p.relax.map(([label, reason]) => h("div", { class: "how-r relax" }, fmt(s.loosened, { label, reason }))),
        m.res ? line(s.products, fmt(s.results, { n: m.res.total })) : null,
        m.ms != null ? line(s.time, secs(m.ms)) : null));
    return d;
  }

  #resultsBlock(m: Turn): HTMLElement {
    const cached = this.#resEl.get(m);
    if (cached) return cached;
    const s = this.#s;
    const r = m.res!;
    let el: HTMLElement;
    if (!r.hits.length) {
      el = h("div", { class: "empty", "data-state": "no-match" },
        h("strong", {}, fmt(s.noMatch, { q: r.q })), s.noMatchHint);
    } else {
      const grid = h("ul", { class: "grid tcards", role: "list" });
      const add = (hits: Hit[]) => hits.forEach((hit) => grid.append(this.#tcard(hit, r.close)));
      add(m.more ? r.hits : r.hits.slice(0, FIRST_CARDS));
      const rest = r.hits.length - FIRST_CARDS;
      const more = !m.more && rest > 0 ? h("button", { type: "button", class: "more", onclick: () => {
        m.more = true;
        const first = grid.children.length;
        add(r.hits.slice(FIRST_CARDS));
        more?.remove();
        (grid.children[first]?.querySelector(".card") as HTMLElement | null)?.focus();
      } }, fmt(s.showMore, { n: rest })) : null;
      el = h("section", { class: "res", "aria-label": r.q },
        h("div", { class: "res-h" }, h("h3", {}, r.q), h("span", {}, fmt(s.results, { n: r.total }))),
        r.weak ? h("p", { class: "status weak" }, s.weak) : null,
        grid, more);
    }
    this.#resEl.set(m, el);
    return el;
  }

  #badges(doc: Record<string, unknown>): string[] {
    const out: string[] = [];
    for (const f of list(this.#attr("badges"), ",")) {
      const v = doc[f];
      for (const x of Array.isArray(v) ? v : [v]) {
        const t = typeof x === "string" || typeof x === "number" ? String(x).trim() : "";
        if (out.length < 2 && t && t.length <= 24 && !out.includes(t)) out.push(t);
      }
    }
    return out;
  }

  #req(hit: Hit): HTMLElement | null {
    const r = hit.requirements;
    if (!r?.total) return null;
    const s = this.#s;
    const met = r.met ?? [];
    const unmet = r.unmet ?? [];
    const unk = r.unknown ?? [];
    const parts = [fmt(s.matches, { m: met.length, t: r.total })];
    if (!unmet.length && !unk.length && met.length) parts.push(met.join(", "));
    if (unmet.length) parts.push(fmt(s.notMet, { label: unmet.join(", ") }));
    if (unk.length) parts.push(fmt(s.notListed, { label: unk.join(", ") }));
    const full = !unmet.length && !unk.length;
    return h("span", { class: `req${full ? "" : " part"}` }, icon(full ? "check" : "dot"), parts.join(" · "));
  }

  #actions(): CardAction[] {
    return [...list(this.#attr("card-actions"), ",").map((label) => ({ label })), ...this.cardActions];
  }

  /** AI Mode card: select checkbox over the image, requirement line, Ask / View / custom actions. */
  #tcard(hit: Hit, close: string[]): HTMLElement {
    const s = this.#s;
    const doc = hit.document as Record<string, unknown>;
    const title = this.#title(hit);
    const tags = this.#badges(doc);
    const card = this.#card(hit, close, [
      tags.length ? h("span", { class: "tags" }, ...tags.map((t) => h("span", { class: "tag" }, t))) : null,
      this.#req(hit)]);
    const on = this.#sel.has(hit.id);
    const cb = h("input", { type: "checkbox", "data-sel": hit.id, "aria-label": fmt(s.selectTitle, { title }),
                            onchange: () => this.#toggleSel(hit, cb) });
    cb.checked = on;
    const url = safeUrl(this.#disp.url ? doc[this.#disp.url] : null);
    return h("li", { class: `pc${on ? " on" : ""}`, "data-id": hit.id }, card,
      h("label", { class: "sel" }, cb, h("span", { "aria-hidden": "true" }, s.select)),
      h("div", { class: "acts" },
        h("button", { type: "button", class: "act", "data-ask": hit.id, "aria-label": fmt(s.askAbout, { title }),
                      onclick: (e: Event) => this.#openDrawer(hit, e.currentTarget as HTMLElement) }, s.askShort),
        url ? h("a", { class: "act", href: url, target: "_blank", rel: "noopener",
                       "aria-label": `${s.view}: ${title}` }, s.view) : null,
        ...this.#actions().map((a) => h("button", { type: "button", class: "act", "data-action": a.label,
                                                    onclick: () => this.#action(a, hit) }, a.label))));
  }

  #action(a: CardAction, hit: Hit) {
    const ev = new CustomEvent("findaro:action", { detail: { action: a.label, hit }, bubbles: true, composed: true,
                                                 cancelable: true });
    if (this.dispatchEvent(ev)) a.onClick?.(hit);
  }

  #clarifyBlock(c: ClarifyEvent): HTMLElement {
    const nextish = c.reason === "next" || c.reason === "suggest";
    return h("div", { class: "clarify", role: "group", "aria-label": nextish ? this.#s.nextSteps : c.question },
      nextish ? null : h("p", {}, c.question),
      ...c.chips.map((chip) => h("button", { type: "button", class: "nrow", "data-clarify": c.reason,
                                             onclick: () => this.#clickClarify(c, chip) },
        h("span", {}, chip.label), chip.count != null ? h("small", { "aria-hidden": "true" }, String(chip.count)) : null,
        icon("arrow"))));
  }

  #clickClarify(c: ClarifyEvent, chip: ClarifyChip) {
    // "next" refinements apply their patch (label shown as the turn); suggestions and empty chips are sent as text
    if (c.reason !== "suggest" && chip.patch?.length) this.#ask(chip.label, chip.patch);
    else this.#ask(chip.label);
  }

  /** Side-by-side table of the selected products, built from their listings (no model involved). */
  #compareTable(hits: Hit[]): HTMLElement {
    const s = this.#s;
    const d = this.#disp;
    const docs = hits.map((x) => x.document as Record<string, unknown>);
    const rows: [string, string[]][] = [];
    if (d.price) rows.push([s.price, docs.map((doc) => doc[d.price!] != null ? this.#formatPrice(doc[d.price!]) : "—")]);
    if (d.rating) rows.push([s.rating, docs.map((doc) => doc[d.rating!] != null ? `★ ${doc[d.rating!]}` : "—")]);
    const facts = docs.map((doc) => new Map(this.#details(doc, d).filter(([, v]) => v.length <= 40)));
    const seen = new Map<string, number>();
    for (const f of facts) for (const k of f.keys()) seen.set(k, (seen.get(k) ?? 0) + 1);
    for (const [k, n] of seen) if (n >= 2 && rows.length < 12) rows.push([k, facts.map((f) => f.get(k) ?? "—")]);
    return h("div", { class: "cmp", role: "region", "aria-label": fmt(s.comparing, { n: hits.length }), tabindex: 0 },
      h("table", { style: `min-width:${104 + hits.length * 130}px` },
        h("thead", {}, h("tr", {}, h("td", {}),
          ...hits.map((hit, i) => h("th", { scope: "col" },
            this.#image(d.image ? docs[i][d.image] : null, this.#title(hit)), h("span", {}, this.#title(hit)))))),
        h("tbody", {}, ...rows.map(([k, vals]) =>
          h("tr", { class: new Set(vals).size > 1 ? "diff" : "" }, h("th", { scope: "row" }, k),
            ...vals.map((v) => h("td", {}, v)))))));
  }

  /** Empty conversation: greeting, then the composer and starter cards, centered (they dock after the first turn). */
  #renderHello() {
    const s = this.#s;
    const el = this.#els.hello;
    const fresh = !this.#msgs.length;
    const starters = fresh ? list(this.#attr("starters"), "|").slice(0, 4) : [];
    el.hidden = !fresh;
    this.#els.thread.classList.toggle("fresh", fresh);
    this.#els.starters.hidden = !starters.length;
    this.#els.starters.setAttribute("aria-label", s.tryAsking);
    this.#els.starters.replaceChildren(...starters.map((q) => h("button", { type: "button", class: "nrow",
                                                                             onclick: () => this.#ask(q) },
      h("span", {}, q), icon("arrow"))));
    if (fresh) el.replaceChildren(h("span", { class: "avatar big" }, icon("spark")), h("h2", {}, s.greeting),
      h("p", {}, s.greetingSub));
  }

  // scrolling: keep the newest turn in view (from the shopper's message down) until they scroll themselves
  #atBottom(): boolean {
    const sc = this.#els.scroll;
    return sc.scrollHeight - sc.scrollTop - sc.clientHeight < 48;
  }

  #onScroll() {
    if (this.#atBottom()) this.#els.jump.hidden = true;
  }

  #follow(m: Turn) {
    const sc = this.#els.scroll;
    if (this.#pin) {
      const i = this.#msgs.indexOf(m);
      const anchor = this.#painted.get(this.#msgs[i > 0 && m.role === "assistant" ? i - 1 : i]);
      if (anchor) sc.scrollTop = anchor.offsetTop - 12;
    }
    this.#els.jump.hidden = this.#atBottom();
  }

  #toBottom(smooth = false) {
    const sc = this.#els.scroll;
    const reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;
    sc.scrollTo({ top: sc.scrollHeight, behavior: smooth && !reduce ? "smooth" : "auto" });
    this.#els.jump.hidden = true;
  }

  // --- composer, selection ------------------------------------------------------------------------------

  #sel = new Map<string, Hit>();
  #focus: string[] | null = null; // "Ask about these": the next message is about these products
  #notice = "";
  #noticeTimer: ReturnType<typeof setTimeout> | undefined;

  #grow() {
    const ta = this.#ta;
    ta.style.height = "auto";
    ta.style.height = `${ta.scrollHeight}px`;
    (this.#els.send as HTMLButtonElement).disabled = !ta.value.trim();
  }

  #onComposerKey(e: KeyboardEvent) {
    if (e.key === "Enter" && !e.shiftKey && !e.isComposing && e.keyCode !== 229) {
      e.preventDefault();
      this.#sendComposer();
    }
  }

  #sendComposer() {
    const q = this.#ta.value.trim();
    if (!q) return;
    this.#ta.value = "";
    this.#grow();
    const ids = this.#focus;
    this.#focus = null;
    this.#renderDock();
    this.#ask(q, undefined, false, ids ? { productIds: ids } : {});
  }

  #toggleSel(hit: Hit, cb: HTMLInputElement) {
    if (cb.checked && !this.#sel.has(hit.id)) {
      if (this.#sel.size >= MAX_SELECT) {
        cb.checked = false;
        this.#flash(fmt(this.#s.maxSelect, { n: MAX_SELECT }));
        return;
      }
      this.#sel.set(hit.id, hit);
    } else if (!cb.checked) this.#sel.delete(hit.id);
    this.#syncSel();
  }

  #syncSel() {
    for (const cb of this.#root.querySelectorAll<HTMLInputElement>("input[data-sel]")) {
      cb.checked = this.#sel.has(cb.dataset.sel!);
      cb.closest(".pc")?.classList.toggle("on", cb.checked);
    }
    if (this.#focus && this.#sel.size === 0) this.#focus = null;
    this.#renderDock();
  }

  #flash(text: string) {
    this.#notice = text;
    this.#renderDock();
    clearTimeout(this.#noticeTimer);
    this.#noticeTimer = setTimeout(() => {
      this.#notice = "";
      this.#renderDock();
    }, 4000);
  }

  #renderDock() {
    const s = this.#s;
    const n = this.#sel.size;
    const bar = this.#els.selbar;
    bar.hidden = !n;
    const d = this.#disp;
    bar.replaceChildren(
      h("span", { class: "seln" },
        h("span", { class: "thumbs", "aria-hidden": "true" }, ...[...this.#sel.values()].map((hit) =>
          this.#image(d.image ? (hit.document as Record<string, unknown>)[d.image] : null, this.#title(hit)))),
        fmt(s.selected, { n })),
      h("button", { type: "button", class: "pri", disabled: n < 2, onclick: () => this.#compare() }, s.compare),
      h("button", { type: "button", class: "sec", "aria-pressed": String(!!this.#focus),
                    onclick: () => this.#askThese() }, s.askThese),
      h("button", { type: "button", class: "sec", onclick: () => {
        this.#sel.clear();
        this.#syncSel();
      } }, s.clear));
    this.#els.notice.textContent = this.#notice;
    this.#els.notice.hidden = !this.#notice;
    const ph = this.#focus ? fmt(s.askSelected, { n: this.#focus.length }) : s.composerPlaceholder;
    this.#ta.placeholder = ph;
    this.#ta.setAttribute("aria-label", ph);
  }

  #compare() {
    if (this.#sel.size < 2) return;
    this.#focus = null;
    const hits = [...this.#sel.values()];
    this.#ask(this.#s.compareMessage, undefined, false, { productIds: hits.map((x) => x.id), compare: hits });
    this.#renderDock();
  }

  #askThese() {
    this.#focus = [...this.#sel.keys()];
    this.#renderDock();
    this.#ta.focus();
  }

  // --- conversation history (layout="page" shows it; it's stored either way) ------------------------------

  #chats: Conv[] | null = null;
  #conv: string | null = null;
  #sideOpen = false; // phone drawer
  #collapsed = (() => { // desktop sidebar
    try {
      return localStorage.getItem(SIDE_KEY) === "1";
    } catch {
      return false;
    }
  })();
  #confirm: string | null = null;

  get #pid(): string {
    return this.#attr("project") || "default";
  }

  #chatList(): Conv[] {
    return (this.#chats ??= loadChats(this.#pid));
  }

  #saveConv() {
    const first = this.#msgs.find((m) => m.role === "user");
    if (!first) return;
    const chats = this.#chatList();
    let c = chats.find((x) => x.id === this.#conv);
    if (!c) {
      c = { id: `c${Date.now().toString(36)}${Math.random().toString(36).slice(2, 6)}`, title: "", updatedAt: 0,
            sessionId: null, msgs: [] };
      chats.unshift(c);
      this.#conv = c.id;
    }
    c.title = first.text.length > 48 ? `${first.text.slice(0, 47)}…` : first.text;
    c.updatedAt = Date.now();
    c.sessionId = this.#session;
    c.display = this.#display;
    const keep = new Set([...Object.values(this.#display).filter((v): v is string => typeof v === "string"),
      ...list(this.#attr("badges"), ",")]);
    c.msgs = this.#msgs.map((m) => slimTurn(m, keep));
    this.#chats = saveChats(this.#pid, chats);
    this.#renderSide();
  }

  #openConv(id: string) {
    const c = this.#chatList().find((x) => x.id === id);
    if (!c) return;
    this.#conv = c.id;
    this.#session = c.sessionId;
    this.#display = c.display ?? EMPTY_DISPLAY;
    this.#msgs = c.msgs.map((m) => ({ ...m }));
    for (const m of this.#msgs) for (const hit of [...m.res?.hits ?? [], ...m.compare ?? []]) this.#docs.set(hit.id, hit);
    this.#lastAsked = [...this.#msgs].reverse().find((m) => m.role === "user" && !m.patch)?.text ?? "";
    this.#reset();
    requestAnimationFrame(() => this.#toBottom());
  }

  #newChat() {
    this.#conv = null;
    this.#session = null;
    this.#msgs = [];
    this.#lastAsked = "";
    this.#reset();
    this.#ta.focus();
  }

  #reset() {
    this.#view = null;
    this.#sel.clear();
    this.#focus = null;
    this.#confirm = null;
    this.#dirty = true;
    this.#toggleSide(false, false);
    this.#render();
  }

  #deleteConv(id: string) {
    this.#chats = saveChats(this.#pid, this.#chatList().filter((x) => x.id !== id));
    this.#confirm = null;
    if (id === this.#conv) this.#newChat();
    else this.#renderSide();
    (this.#els.side?.querySelector(".newchat") as HTMLElement | null)?.focus();
  }

  #toggleSide(open: boolean, focus = true) {
    if (!this.#page) return;
    this.#sideOpen = open;
    this.#els.side.classList.toggle("open", open);
    this.#els.sscrim.hidden = !open;
    this.#els.menu.setAttribute("aria-expanded", String(open));
    if (!focus) return;
    if (open) (this.#els.side.querySelector(".newchat") as HTMLElement | null)?.focus();
    else this.#els.menu.focus();
  }

  /** The sidebar is a drawer when the widget is phone-width (same breakpoint as the CSS container query). */
  #narrow(): boolean {
    return this.getBoundingClientRect().width <= 760;
  }

  /** Desktop: hide or show the history sidebar; remembered in localStorage when it's available. */
  #collapse(on: boolean) {
    this.#collapsed = on;
    try {
      localStorage.setItem(SIDE_KEY, on ? "1" : "0");
    } catch {
      // storage blocked: the choice lasts until reload
    }
    this.#els.root.classList.toggle("collapsed", on);
    ((on ? this.#els.menu : this.#els.side.querySelector(".scol")) as HTMLElement | null)?.focus();
  }

  #renderSide() {
    if (!this.#page) return;
    const s = this.#s;
    const today = new Date().toDateString();
    const groups: [string, Conv[]][] = [[s.today, []], [s.earlier, []]];
    for (const c of [...this.#chatList()].sort((a, b) => b.updatedAt - a.updatedAt)) {
      groups[new Date(c.updatedAt).toDateString() === today ? 0 : 1][1].push(c);
    }
    const item = (c: Conv) => this.#confirm === c.id
      ? h("li", { class: "ci confirm" }, h("span", {}, s.deleteConfirm),
        h("button", { type: "button", class: "danger", "data-confirm": "", "aria-label": fmt(s.deleteChat, { title: c.title }),
                      onclick: () => this.#deleteConv(c.id) }, s.deleteYes),
        h("button", { type: "button", class: "cancel", onclick: () => {
          this.#confirm = null;
          this.#renderSide();
          (this.#els.side.querySelector(`[data-del="${c.id}"]`) as HTMLElement | null)?.focus();
        } }, s.cancel))
      : h("li", { class: `ci${c.id === this.#conv ? " cur" : ""}` },
        h("button", { type: "button", class: "conv", "aria-current": c.id === this.#conv ? "true" : null,
                      title: c.title, onclick: () => this.#openConv(c.id) }, c.title),
        h("button", { type: "button", class: "iconbtn del", "data-del": c.id, "aria-label": fmt(s.deleteChat, { title: c.title }),
                      onclick: () => {
                        this.#confirm = c.id;
                        this.#renderSide();
                        (this.#els.side.querySelector("[data-confirm]") as HTMLElement | null)?.focus();
                      } }, icon("trash")));
    this.#els.side.replaceChildren(
      h("div", { class: "shead" }, h("span", { class: "avatar" }, icon("spark")), h("strong", {}, s.assistantName),
        h("button", { type: "button", class: "iconbtn scol", "aria-label": s.closeHistory, title: s.closeHistory,
                      "aria-controls": "findaro-side", "aria-expanded": "true", onclick: () => this.#collapse(true) },
          icon("side")),
        h("button", { type: "button", class: "iconbtn sclose", "aria-label": s.closeHistory,
                      onclick: () => this.#toggleSide(false) }, icon("x"))),
      h("button", { type: "button", class: "newchat", onclick: () => this.#newChat() }, icon("plus"), s.newChat),
      h("nav", { class: "convs", "aria-label": s.history },
        ...groups.filter(([, cs]) => cs.length).map(([label, cs]) =>
          h("div", { class: "grp" }, h("h4", {}, label), h("ul", { role: "list" }, ...cs.map(item)))),
        this.#chatList().length ? null : h("p", { class: "none" }, s.noChats)),
      this.#els.sfoot);
  }

  // --- product drawer (M5): a conversation about one product -------------------------------------------------

  #drawer: { hit: Hit; msgs: Msg[]; opener: HTMLElement | null } | null = null;
  #drawerSessions = new Map<string, string>();

  #openDrawer(hit: Hit, opener: HTMLElement | null = null) {
    this.#drawer = { hit, msgs: [], opener };
    if (!this.#els.drawer) {
      this.#els.scrim = h("div", { class: "scrim", onclick: () => this.#closeDrawer() });
      this.#els.drawer = h("div", { class: "drawer", role: "dialog", "aria-modal": "true",
                                    "aria-labelledby": "zd-title",
                                    onkeydown: (e: KeyboardEvent) => e.key === "Escape" && this.#closeDrawer() });
      this.#root.append(this.#els.scrim, this.#els.drawer);
    }
    this.#els.scrim.hidden = false;
    this.#els.drawer.hidden = false;
    this.#renderDrawer();
    (this.#els.drawer.querySelector("input") as HTMLInputElement | null)?.focus();
  }

  #closeDrawer() {
    if (!this.#drawer) return;
    const opener = this.#drawer.opener;
    this.#drawer = null;
    this.#els.drawer.hidden = true;
    this.#els.scrim.hidden = true;
    opener?.focus();
  }

  #details(doc: Record<string, unknown>, d: Display): [string, string][] {
    const skip = new Set([d.id, d.title, d.price, d.compare_at_price, d.image, d.url, d.rating, d.rating_count,
                          d.in_stock, d.currency].filter(Boolean) as string[]);
    const out: [string, string][] = [];
    for (const [k, v] of Object.entries(doc)) {
      if (skip.has(k) || v == null || v === "" || typeof v === "object" && !Array.isArray(v)) continue;
      if (d.currency && v === d.currency) continue; // "Currency: INR" adds nothing next to the price
      const label = k.replace(/_/g, " ").replace(/^./, (c) => c.toUpperCase());
      const text = Array.isArray(v) ? v.join(", ") : String(v);
      out.push([label, text.includes(" > ") ? text.split(" > ").pop()! : text]);
    }
    return out;
  }

  #renderDrawer() {
    const dr = this.#drawer;
    if (!dr) return;
    const s = this.#s;
    const d = this.#disp;
    const doc = dr.hit.document as Record<string, unknown>;
    const title = this.#title(dr.hit);
    const price = d.price ? doc[d.price] : undefined;
    const rating = d.rating ? doc[d.rating] : undefined;
    const stock = d.in_stock ? doc[d.in_stock] : undefined;
    const url = safeUrl(d.url ? doc[d.url] : null);

    const thread = h("div", { class: "thread", role: "log", "aria-live": "polite" });
    for (const m of dr.msgs) {
      const text = h("div", { class: `text${m.pending ? " typing" : ""}` },
        m.role === "assistant" && m.pending && !m.text ? s.thinking : m.text.replace(/\[[^\]\s]+\]/g, "").trim());
      const msg = h("div", { class: `msg ${m.role}` }, h("span", { class: "who" }, m.role === "user" ? s.you : s.assistant),
        text);
      if (m.general?.trim()) msg.append(h("div", { class: "general" }, h("span", { class: "who" }, s.generalLabel),
        m.general.trim()));
      thread.append(msg);
    }
    const sugg = h("div", { class: "row suggestions", role: "group", "aria-label": s.suggestions });
    if (!dr.msgs.length) {
      const asked = new Set<string>();
      for (const [field, q] of Object.entries(s.suggest)) {
        if ((field === "*" || doc[field] != null) && !asked.has(q)) {
          asked.add(q);
          sugg.append(h("button", { type: "button", class: "pill", onclick: () => this.#askProduct(q) }, q));
        }
      }
    }
    const input = h("input", { type: "text", "aria-label": s.drawerPlaceholder, placeholder: s.drawerPlaceholder,
                               autocomplete: "off" });
    const form = h("form", { class: "box", onsubmit: (e: Event) => {
      e.preventDefault();
      const q = input.value.trim();
      if (q) this.#askProduct(q);
    } }, input, h("button", { class: "go", type: "submit" }, s.send));

    this.#els.drawer.replaceChildren(
      h("div", { class: "dhead" },
        h("h2", { id: "zd-title" }, title),
        h("button", { type: "button", class: "close", "aria-label": s.closeDrawer, onclick: () => this.#closeDrawer() },
          "×")),
      h("div", { class: "dbody" },
        h("div", { class: "summary" }, this.#image(d.image ? doc[d.image] : null, title),
          h("div", {},
            price != null ? h("div", { class: "price" }, this.#formatPrice(price)) : null,
            h("div", { class: "meta" }, rating != null ? h("span", {}, `★ ${rating}`) : null,
              stock === false ? h("span", {}, s.outOfStock) : null),
            url ? h("a", { href: url, target: "_blank", rel: "noopener", class: "link" }, s.viewProduct) : null)),
        this.#factsBlock(this.#details(doc, d)),
        thread, sugg),
      h("div", { class: "dfoot" }, form));
    thread.lastElementChild?.scrollIntoView({ block: "nearest" });
  }

  /** Up to 6 short facts up front; long text (description, care, Q&A) and the rest behind "All details". */
  #factsBlock(facts: [string, string][]): HTMLElement {
    const short = facts.filter(([, v]) => v.length <= 40).slice(0, 6);
    const rest = facts.filter((f) => !short.includes(f));
    const dl = (items: [string, string][]) =>
      h("dl", { class: "facts" }, ...items.flatMap(([k, v]) => [h("dt", {}, k), h("dd", {}, v)]));
    return h("div", { class: "factsbox" }, short.length ? dl(short) : null,
      rest.length ? h("details", {}, h("summary", {}, this.#s.allDetails), dl(rest)) : null);
  }

  async #askProduct(q: string) {
    const dr = this.#drawer;
    if (!dr) return;
    const id = dr.hit.id;
    const bot: Msg = { role: "assistant", text: "", general: "", pending: true };
    dr.msgs.push({ role: "user", text: q }, bot);
    this.#renderDrawer();
    try {
      const stream = this.#client().chat(q, { sessionId: this.#drawerSessions.get(id) ?? null, productIds: [id],
                                             cancelPrevious: false });
      for await (const ev of stream as AsyncIterable<ChatEvent>) {
        if (ev.type === "session") this.#drawerSessions.set(id, ev.data.session_id);
        else if (ev.type === "text") {
          if (ev.data.part === "general") bot.general += ev.data.delta;
          else bot.text += ev.data.delta;
        } else if (ev.type === "done") bot.pending = false;
        if (this.#drawer === dr) this.#renderDrawer();
      }
    } catch (e) {
      bot.text = this.#s.error;
      this.#fail(e);
    } finally {
      bot.pending = false;
      if (this.#drawer === dr) {
        this.#renderDrawer();
        (this.#els.drawer.querySelector("input") as HTMLInputElement | null)?.focus();
      }
    }
  }
}

if (typeof customElements !== "undefined" && !customElements.get("findaro-search")) {
  customElements.define("findaro-search", FindaroSearch);
}

declare global {
  interface HTMLElementTagNameMap {
    "findaro-search": FindaroSearch;
  }
}
