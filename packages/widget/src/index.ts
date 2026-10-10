/**
 * <zerch-search>: drop-in AI search widget (Web Component, Shadow DOM, no framework).
 *
 *   <script src="zerch-widget.js" data-project="prj_…" data-key="zk_search_…" data-base-url="…" defer></script>
 *   <zerch-search></zerch-search>
 *
 * Attributes (override the script tag): project, key, base-url, mode ("search" | "ai"), locale ("en" | "hi-en"),
 * placeholder, size, theme ("light" | "dark"). Properties: renderProduct, onProductClick, strings, client.
 * Events: "zerch:product-click" (cancelable), "zerch:results", "zerch:error".
 */
import {
  createClient,
  debounce,
  type ChatEvent,
  type Chip,
  type ClarifyEvent,
  type Display,
  type Hit,
  type PatchOp,
  type Pill,
  type SearchResponse,
  type ZerchClient,
} from "@zerch/sdk";

import { STRINGS, fmt, type Strings } from "./strings";
import { CSS } from "./styles";

export type RenderProduct = (hit: Hit, ctx: { display: Display; formatPrice: (v: unknown) => string }) =>
  HTMLElement | string;
export type ProductClick = (hit: Hit, event: Event) => void;

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
interface Msg {
  role: "user" | "assistant";
  text: string;
  general?: string; // labeled general know-how (product conversation)
  clarify?: ClarifyEvent | null;
  pending?: boolean;
  error?: boolean;
}

const SCRIPT_DEFAULTS: Record<string, string> = {};
{
  const s = (typeof document !== "undefined" ? document.currentScript : null) as HTMLScriptElement | null;
  if (s?.dataset) {
    for (const [k, v] of Object.entries({ project: s.dataset.project, key: s.dataset.key,
      "base-url": s.dataset.baseUrl, locale: s.dataset.locale, mode: s.dataset.mode })) {
      if (v) SCRIPT_DEFAULTS[k] = v;
    }
  }
}

function h<K extends keyof HTMLElementTagNameMap>(tag: K, attrs: Record<string, unknown> = {},
                                                   ...kids: (Node | string | null | undefined | false)[]) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v == null || v === false) continue;
    if (k.startsWith("on") && typeof v === "function") el.addEventListener(k.slice(2), v as EventListener);
    else if (k === "class") el.className = String(v);
    else el.setAttribute(k, v === true ? "" : String(v));
  }
  for (const kid of kids) if (kid != null && kid !== false) el.append(kid);
  return el;
}

const EMPTY_DISPLAY: Display = {};

/** Only http(s) links from catalog data (no javascript:, data: …). */
function safeUrl(value: unknown): string | null {
  if (typeof value !== "string" || !value) return null;
  try {
    const u = new URL(value, location.href);
    return u.protocol === "http:" || u.protocol === "https:" ? u.href : null;
  } catch {
    return null;
  }
}

export class ZerchSearch extends HTMLElement {
  static observedAttributes = ["mode", "locale", "placeholder", "project", "key", "base-url"];

  /** Custom product card. Return an element, or an HTML string (escape document fields yourself: they are data). */
  renderProduct: RenderProduct | null = null;
  /** Called on product click; navigation to the product URL is skipped when set. */
  onProductClick: ProductClick | null = null;
  /** Partial string overrides, merged over the locale's defaults. */
  strings: Partial<Strings> = {};
  /** Inject a preconfigured client (e.g. with a custom fetch). */
  client: ZerchClient | null = null;

  #root: ShadowRoot;
  #mode: "search" | "ai" = "search";
  #query = "";
  #patches: PatchOp[] = [];
  #view: View | null = null;
  #loading = false;
  #error = "";
  #session: string | null = null;
  #msgs: Msg[] = [];
  #docs = new Map<string, Hit>();
  #input!: HTMLInputElement;
  #debounced = debounce(() => this.#runSearch(), 250);

  constructor() {
    super();
    this.#root = this.attachShadow({ mode: "open" });
  }

  connectedCallback() {
    this.#mode = (this.#attr("mode") === "ai" ? "ai" : "search");
    this.#build();
    this.#render();
  }

  attributeChangedCallback(name: string) {
    if (!this.isConnected || !this.#input) return;
    if (name === "mode") this.#setMode(this.#attr("mode") === "ai" ? "ai" : "search");
    else if (["project", "key", "base-url"].includes(name)) this.client = null;
    this.#render();
  }

  /** Run a search (or ask the AI in "ai" mode) programmatically. */
  search(query: string) {
    this.#input.value = query;
    this.#submit();
  }

  get #s(): Strings {
    const base = STRINGS[this.#attr("locale") || "en"] || STRINGS.en;
    return { ...base, ...this.strings };
  }

  #attr(name: string): string | null {
    return this.getAttribute(name) ?? SCRIPT_DEFAULTS[name] ?? null;
  }

  #client(): ZerchClient {
    if (!this.client) {
      const key = this.#attr("key");
      if (!key || /^YOUR_/i.test(key)) {
        throw new Error("zerch-search: set data-key on the script tag (or key=…) to your project's search key");
      }
      this.client = createClient({ projectId: this.#attr("project") || "", searchKey: key,
                                   baseUrl: this.#attr("base-url") || undefined });
    }
    return this.client;
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
    const form = h("form", { class: "box", role: "search", onsubmit: (e: Event) => {
      e.preventDefault();
      this.#submit();
    } }, this.#els.modes, this.#input, this.#els.go);
    this.#els.chips = h("div", { class: "row chips", role: "group" });
    this.#els.pills = h("div", { class: "pills", id: "zerch-filters" });
    this.#els.status = h("div", { class: "status", role: "status", "aria-live": "polite" });
    this.#els.results = h("div", {});
    this.#els.panel = h("div", { class: "panel", role: "log", "aria-live": "polite" });
    this.#els.layout = h("div", { class: "layout" }, this.#els.panel,
      h("section", { "aria-label": s.products }, this.#els.status, this.#els.results));
    this.#root.append(h("div", { class: "root", part: "root" },
      form, this.#els.chips, this.#els.pills, this.#els.layout));
  }

  #setMode(m: "search" | "ai", focus = false) {
    if (m === this.#mode && this.#els.layout) {
      if (focus) this.#input.focus();
      return;
    }
    this.#mode = m;
    this.#render();
    if (focus) this.#input.focus();
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
    this.dispatchEvent(new CustomEvent("zerch:results", { detail: res, bubbles: true, composed: true }));
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
    this.#error = msg.startsWith("zerch-search:") || (e as { status?: number })?.status === 401
      ? (msg.startsWith("zerch-search:") ? msg : "zerch-search: invalid search key (check data-key)")
      : this.#s.error;
    this.dispatchEvent(new CustomEvent("zerch:error", { detail: e, bubbles: true, composed: true }));
  }

  // --- chat ---------------------------------------------------------------------------------------------

  #lastAsked = "";

  async #ask(message: string, patch?: PatchOp[], retried = false): Promise<void> {
    if (!patch) this.#lastAsked = message;
    let expired = false;
    const user: Msg = { role: "user", text: message };
    const bot: Msg = { role: "assistant", text: "", pending: true, clarify: null };
    this.#msgs.push(user, bot);
    this.#renderPanel();
    try {
      const stream = this.#client().chat(patch ? "" : message, { sessionId: this.#session, patch });
      for await (const ev of stream as AsyncIterable<ChatEvent>) {
        if (ev.type === "session") this.#session = ev.data.session_id;
        else if (ev.type === "plan" && ev.data.understood && this.#view) {
          this.#view.chips = ev.data.understood.chips ?? [];
        } else if (ev.type === "results" && !ev.data.unchanged) {
          const prev = this.#view;
          this.#view = {
            total: ev.data.total, hits: ev.data.items, pills: ev.data.pills ?? [],
            chips: prev?.chips ?? [], quality: ev.data.match_quality ?? null,
            close: new Set(ev.data.close_matches ?? []), display: ev.data.display ?? prev?.display ?? EMPTY_DISPLAY,
            semantic: message,
          };
          for (const hit of ev.data.items) this.#docs.set(hit.id, hit);
          this.#renderResults();
        } else if (ev.type === "plan" && ev.data.understood) {
          this.#view = { total: 0, hits: [], pills: [], quality: null, close: new Set(), display: EMPTY_DISPLAY,
                         chips: ev.data.understood.chips ?? [], semantic: message };
        } else if (ev.type === "clarify") bot.clarify = ev.data;
        else if (ev.type === "text") bot.text += ev.data.delta;
        else if (ev.type === "done") {
          bot.pending = false;
          expired = ev.data.reason === "session_expired";
        }
        this.#renderChips();
        this.#renderPanel();
      }
    } catch (e) {
      if ((e as Error).name !== "AbortError") {
        bot.error = true;
        bot.text = this.#s.error;
        this.#fail(e);
      }
    } finally {
      bot.pending = false;
      this.#render();
    }
    if (expired && patch && !retried && this.#lastAsked) {
      // the chat session timed out: drop the empty turn, ask the last question again, then apply the click
      this.#msgs.splice(-2, 2);
      this.#session = null;
      await this.#ask(this.#lastAsked);
      await this.#ask(message, patch, true);
    }
  }

  // --- rendering ----------------------------------------------------------------------------------------

  #render() {
    const s = this.#s;
    const ai = this.#mode === "ai";
    for (const b of this.#els.modes.querySelectorAll("button")) {
      b.setAttribute("aria-checked", String(b.dataset.mode === this.#mode));
    }
    this.#input.placeholder = ai ? s.askPlaceholder : (this.#attr("placeholder") || s.placeholder);
    this.#input.setAttribute("aria-label", this.#input.placeholder);
    this.#els.go.textContent = ai ? s.send : s.search;
    this.#els.layout.classList.toggle("ai", ai);
    this.#els.panel.hidden = !ai;
    this.#els.panel.setAttribute("aria-label", s.conversation);
    this.#renderChips();
    this.#renderStatus();
    this.#renderResults();
    this.#renderPanel();
  }

  #filtersOpen = false;

  #renderChips() {
    const s = this.#s;
    const v = this.#view;
    const chips = v?.chips ?? [];
    const pills = v?.pills ?? [];
    const canFilter = !!pills.length && !!v?.hits.length;
    this.#els.chips.replaceChildren();
    this.#els.chips.hidden = !chips.length && !canFilter;
    this.#els.chips.setAttribute("aria-label", s.understood);
    {
      for (const c of chips) {
        this.#els.chips.append(h("span", { class: `chip ${c.kind}`, title: c.source || undefined }, c.label,
          h("button", { type: "button", "aria-label": fmt(s.removeFilter, { label: c.label }),
                        onclick: () => this.#applyPatch(c.remove ?? [], `− ${c.label}`) }, "×")));
      }
    }
    if (canFilter) {
      this.#els.chips.append(h("button", {
        type: "button", class: "filters-toggle", "aria-expanded": String(this.#filtersOpen),
        "aria-controls": "zerch-filters", onclick: () => {
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
    if (!v) return;
    if (!v.hits.length) {
      box.append(h("div", { class: "empty", "data-state": "no-match" },
        h("strong", {}, fmt(s.noMatch, { q: this.#query || v.semantic })), s.noMatchHint));
      return;
    }
    const list = h("ul", { class: "grid", role: "list" });
    for (const hit of v.hits) {
      const doc = hit.document as Record<string, unknown>;
      const title = String((v.display.title && doc[v.display.title]) ?? hit.id);
      list.append(h("li", { class: "cell" }, this.#card(hit, v),
        h("button", { type: "button", class: "ask", "data-ask": hit.id, "aria-label": fmt(s.askAbout, { title }),
                      onclick: (e: Event) => this.#openDrawer(hit, e.currentTarget as HTMLElement) }, s.askShort)));
    }
    box.append(list);
  }

  #formatPrice = (value: unknown): string => {
    const n = typeof value === "number" ? value : Number(value);
    if (!Number.isFinite(n)) return value == null ? "" : String(value);
    const cur = this.#view?.display.currency;
    try {
      return new Intl.NumberFormat(cur === "INR" ? "en-IN" : undefined, cur
        ? { style: "currency", currency: cur, maximumFractionDigits: n % 1 ? 2 : 0 }
        : { maximumFractionDigits: 2 }).format(n);
    } catch {
      return String(n);
    }
  };

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
    const ev = new CustomEvent("zerch:product-click", { detail: { hit }, bubbles: true, composed: true,
                                                        cancelable: true });
    const allowed = this.dispatchEvent(ev);
    if (this.onProductClick) {
      e.preventDefault();
      this.onProductClick(hit, e);
    } else if (!allowed) e.preventDefault();
  }

  #card(hit: Hit, v: View): HTMLElement {
    const d = v.display;
    const doc = hit.document as Record<string, unknown>;
    if (this.renderProduct) {
      const out = this.renderProduct(hit, { display: d, formatPrice: this.#formatPrice });
      if (typeof out !== "string") return out;
      const wrap = h("div", {});
      wrap.innerHTML = out;
      return wrap;
    }
    const s = this.#s;
    const title = String((d.title && doc[d.title]) ?? hit.id);
    const url = safeUrl(d.url ? doc[d.url] : null);
    const price = d.price ? doc[d.price] : undefined;
    const mrp = d.compare_at_price ? doc[d.compare_at_price] : undefined;
    const rating = d.rating ? doc[d.rating] : undefined;
    const count = d.rating_count ? doc[d.rating_count] : undefined;
    const stock = d.in_stock ? doc[d.in_stock] : undefined;
    const body = h("div", { class: "body" },
      v.close.has(hit.id) ? h("span", { class: "badge" }, s.close) : null,
      h("span", { class: "title" }, title),
      price != null ? h("span", { class: "price" }, this.#formatPrice(price),
        mrp != null && Number(mrp) > Number(price) ? h("span", { class: "mrp" }, this.#formatPrice(mrp)) : null) : null,
      h("span", { class: "meta" },
        rating != null ? h("span", {}, `★ ${rating}${count != null ? ` (${count})` : ""}`) : null,
        stock === false ? h("span", {}, s.outOfStock) : null));
    const attrs = { class: "card", "data-id": hit.id, onclick: (e: Event) => this.#click(hit, e) };
    return url
      ? h("a", { ...attrs, href: url, target: "_blank", rel: "noopener" }, this.#image(d.image ? doc[d.image] : null, title), body)
      : h("button", { ...attrs, type: "button" }, this.#image(d.image ? doc[d.image] : null, title), body);
  }

  #mini(id: string): HTMLElement | string {
    const hit = this.#docs.get(id);
    if (!hit) return `[${id}]`;
    const d = this.#view?.display ?? EMPTY_DISPLAY;
    const doc = hit.document as Record<string, unknown>;
    const title = String((d.title && doc[d.title]) ?? id);
    const price = d.price ? doc[d.price] : undefined;
    return h("button", { type: "button", class: "mini", "data-id": id, onclick: (e: Event) => this.#click(hit, e) },
      this.#image(d.image ? doc[d.image] : null, title),
      h("span", {}, title + (price != null ? ` · ${this.#formatPrice(price)}` : "")));
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
    const d = this.#view?.display ?? EMPTY_DISPLAY;
    const doc = dr.hit.document as Record<string, unknown>;
    const title = String((d.title && doc[d.title]) ?? dr.hit.id);
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
      const q = (input as HTMLInputElement).value.trim();
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

  #renderPanel() {
    if (this.#mode !== "ai") return;
    const s = this.#s;
    const panel = this.#els.panel;
    panel.replaceChildren();
    for (const [i, m] of this.#msgs.entries()) {
      const text = h("div", { class: `text${m.pending ? " typing" : ""}` });
      if (m.role === "assistant") {
        // [ID] citations become inline product cards
        for (const part of m.text.split(/(\[[^\]\s]+\])/)) {
          const id = /^\[([^\]\s]+)\]$/.exec(part)?.[1];
          text.append(id ? this.#mini(id) : part);
        }
        if (m.pending && !m.text) text.append(s.thinking);
      } else text.textContent = m.text;
      const msg = h("div", { class: `msg ${m.role}` }, h("span", { class: "who" }, m.role === "user" ? s.you : s.assistant),
        text);
      const c = m.clarify;
      if (c && i === this.#msgs.length - 1) {
        const chips = h("div", { class: "row", role: "group", "aria-label": c.question });
        for (const chip of c.chips) {
          chips.append(h("button", { type: "button", class: "pill", "data-clarify": "",
                                     onclick: () => this.#ask(chip.label, chip.patch) },
            chip.label, chip.count != null ? h("small", { "aria-hidden": "true" }, String(chip.count)) : null));
        }
        msg.append(h("div", { class: "clarify" }, h("p", {}, c.question), chips));
      }
      panel.append(msg);
    }
    panel.scrollTop = panel.scrollHeight;
  }
}

if (typeof customElements !== "undefined" && !customElements.get("zerch-search")) {
  customElements.define("zerch-search", ZerchSearch);
}

declare global {
  interface HTMLElementTagNameMap {
    "zerch-search": ZerchSearch;
  }
}
