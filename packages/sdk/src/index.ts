/**
 * @findaro/sdk — headless client for the findaro search API. Zero runtime dependencies.
 *
 *   const findaro = createClient({ projectId: "prj_…", searchKey: "fdr_search_…", baseUrl: "https://…" });
 *   const res = await findaro.search("black shoes under 1000");
 *   for await (const ev of findaro.chat("sasta wala", { sessionId })) { … }
 */
import type { components } from "./api.gen";

type S = components["schemas"];
export type SearchRequest = S["SearchRequest"];
export type SearchResponse = S["SearchResponse"];
export type Hit = S["Hit"];
export type Understood = S["Understood"];
export type Chip = S["Chip"];
export type Pill = S["Pill"];
export type PillValue = S["PillValue"];
export type Display = S["Display"];
export type PatchOp = S["PatchOp"];
export type SessionEvent = S["SessionEvent"];
export type PlanEvent = S["PlanEvent"];
export type ResultsEvent = S["ResultsEvent"];
export type ClarifyEvent = S["ClarifyEvent"];
export type ClarifyChip = S["ClarifyChipView"];
export type TextEvent = S["TextEvent"];
export type DoneEvent = S["DoneEvent"];
export type MatchQuality = "good" | "weak" | "none";

export type ChatEvent =
  | { type: "session"; data: SessionEvent }
  | { type: "plan"; data: PlanEvent }
  | { type: "results"; data: ResultsEvent }
  | { type: "clarify"; data: ClarifyEvent }
  | { type: "text"; data: TextEvent }
  | { type: "done"; data: DoneEvent };

export interface ClientOptions {
  /** Your project id (prj_…). Used to scope sessions; the search key already identifies the project. */
  projectId: string;
  /** The browser-safe search key (fdr_search_…). Never put an admin key in a browser. */
  searchKey: string;
  /** API base URL, e.g. "https://api.example.com". Defaults to http://localhost:8000. */
  baseUrl?: string;
  /** Custom fetch (tests, SSR). Defaults to globalThis.fetch. */
  fetch?: typeof fetch;
}

export interface SearchParams extends Partial<Omit<SearchRequest, "patch">> {
  query?: string;
  patch?: PatchOp[];
}

export interface RequestOptions {
  /** Abort this request. */
  signal?: AbortSignal;
  /** Cancel the previous in-flight request of the same kind (default true). */
  cancelPrevious?: boolean;
}

export interface ChatOptions extends RequestOptions {
  sessionId?: string | null;
  /** Structured plan edits (e.g. a chip's `remove` or a clarifier chip's `patch`), applied without a new turn. */
  patch?: PatchOp[];
  /** Talk about these products (up to 3), e.g. from a product page: every turn is answered about them. */
  productIds?: string[];
  onSession?: (e: SessionEvent) => void;
  onPlan?: (e: PlanEvent) => void;
  onResults?: (e: ResultsEvent) => void;
  onClarify?: (e: ClarifyEvent) => void;
  /** `fullText` is the answer so far (product facts); general know-how arrives with `e.part === "general"`. */
  onText?: (e: TextEvent, fullText: string) => void;
  onDone?: (e: DoneEvent) => void;
  onError?: (err: Error) => void;
}

export interface ChatResult {
  sessionId: string | null;
  text: string;
  /** General know-how (labeled, not a claim about the product), if the answer had any. */
  general: string;
  plan: PlanEvent | null;
  results: ResultsEvent | null;
  clarify: ClarifyEvent | null;
  done: DoneEvent | null;
}

/** A chat turn: iterate it for events, or await `.result`. Callbacks in ChatOptions fire either way. */
export interface ChatStream extends AsyncIterable<ChatEvent> {
  result: Promise<ChatResult>;
  cancel(): void;
}

export class FindaroError extends Error {
  constructor(message: string, readonly status: number, readonly code: string) {
    super(message);
    this.name = "FindaroError";
  }
}

export interface FindaroClient {
  readonly projectId: string;
  search(q: string | SearchParams, opts?: RequestOptions): Promise<SearchResponse>;
  chat(message: string, opts?: ChatOptions): ChatStream;
}

const isAbort = (e: unknown) => e instanceof Error && e.name === "AbortError";
// fetch rejects with a TypeError when the network fails (DNS, offline, CORS): retry those once
const isNetwork = (e: unknown) => e instanceof TypeError;

function linkSignals(outer?: AbortSignal): AbortController {
  const c = new AbortController();
  if (outer) {
    if (outer.aborted) c.abort(outer.reason);
    else outer.addEventListener("abort", () => c.abort(outer.reason), { once: true });
  }
  return c;
}

export function createClient(options: ClientOptions): FindaroClient {
  const base = (options.baseUrl || "http://localhost:8000").replace(/\/+$/, "");
  const doFetch = options.fetch || globalThis.fetch.bind(globalThis);
  const inflight: Record<string, AbortController | undefined> = {};

  function begin(kind: string, opts: RequestOptions = {}): AbortController {
    if (opts.cancelPrevious !== false) inflight[kind]?.abort();
    const c = linkSignals(opts.signal);
    inflight[kind] = c;
    return c;
  }

  async function post(path: string, body: unknown, signal: AbortSignal, accept = "application/json") {
    const init: RequestInit = {
      method: "POST",
      signal,
      headers: { authorization: `Bearer ${options.searchKey}`, "content-type": "application/json", accept },
      body: JSON.stringify(body),
    };
    let res: Response;
    try {
      res = await doFetch(base + path, init);
    } catch (e) {
      if (isAbort(e) || !isNetwork(e) || signal.aborted) throw e;
      res = await doFetch(base + path, init); // one retry on a network error
    }
    if (!res.ok) {
      let code = "http_error";
      let message = `${res.status} ${res.statusText}`;
      try {
        const j = await res.json();
        code = j?.error?.code ?? code;
        message = j?.error?.message ?? message;
      } catch {
        /* not JSON */
      }
      throw new FindaroError(message, res.status, code);
    }
    return res;
  }

  async function search(q: string | SearchParams, opts: RequestOptions = {}): Promise<SearchResponse> {
    const body = typeof q === "string" ? { query: q } : q;
    const c = begin("search", opts);
    try {
      const res = await post("/v1/search", body, c.signal);
      return (await res.json()) as SearchResponse;
    } finally {
      if (inflight.search === c) inflight.search = undefined;
    }
  }

  function chat(message: string, opts: ChatOptions = {}): ChatStream {
    const c = begin("chat", opts);
    const queue: ChatEvent[] = [];
    let wake: (() => void) | null = null;
    let finished = false;
    let failure: unknown = null;
    const state: ChatResult = { sessionId: opts.sessionId ?? null, text: "", general: "", plan: null,
                                results: null, clarify: null, done: null };

    const emit = (ev: ChatEvent) => {
      switch (ev.type) {
        case "session": state.sessionId = ev.data.session_id; opts.onSession?.(ev.data); break;
        case "plan": state.plan = ev.data; opts.onPlan?.(ev.data); break;
        case "results": state.results = ev.data; opts.onResults?.(ev.data); break;
        case "clarify": state.clarify = ev.data; opts.onClarify?.(ev.data); break;
        case "text":
          if (ev.data.part === "general") state.general += ev.data.delta;
          else state.text += ev.data.delta;
          opts.onText?.(ev.data, state.text);
          break;
        case "done": state.done = ev.data; opts.onDone?.(ev.data); break;
      }
      queue.push(ev);
      wake?.();
    };

    const run = (async () => {
      const body: Record<string, unknown> = { message, session_id: opts.sessionId ?? null };
      if (opts.patch) body.patch = opts.patch;
      if (opts.productIds?.length) body.product_ids = opts.productIds;
      const res = await post("/v1/chat", body, c.signal, "text/event-stream");
      if (!res.body) throw new FindaroError("streaming not supported by this fetch", 0, "no_stream");
      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buf = "";
      for (;;) {
        const { value, done } = await reader.read();
        if (done) break;
        buf += decoder.decode(value, { stream: true });
        let cut: number;
        while ((cut = buf.indexOf("\n\n")) >= 0) {
          const block = buf.slice(0, cut);
          buf = buf.slice(cut + 2);
          let type = "message";
          let data = "";
          for (const line of block.split("\n")) {
            if (line.startsWith("event:")) type = line.slice(6).trim();
            else if (line.startsWith("data:")) data += line.slice(5).trim();
          }
          if (data) emit({ type, data: JSON.parse(data) } as ChatEvent);
        }
      }
    })()
      .catch((e) => {
        failure = e;
        if (!isAbort(e)) opts.onError?.(e instanceof Error ? e : new Error(String(e)));
      })
      .finally(() => {
        finished = true;
        if (inflight.chat === c) inflight.chat = undefined;
        wake?.();
      });

    const result = run.then(() => {
      if (failure) throw failure;
      return state;
    });
    result.catch(() => {}); // callers using only callbacks/iteration shouldn't see unhandled rejections

    return {
      result,
      cancel: () => c.abort(),
      async *[Symbol.asyncIterator]() {
        for (;;) {
          if (queue.length) {
            yield queue.shift()!;
            continue;
          }
          if (finished) {
            if (failure && !isAbort(failure)) throw failure;
            return;
          }
          await new Promise<void>((r) => (wake = r));
          wake = null;
        }
      },
    };
  }

  return { projectId: options.projectId, search, chat };
}

/** Debounce helper for search-as-you-type: `const run = debounce((q) => findaro.search(q), 250)`. */
export function debounce<A extends unknown[], R>(fn: (...args: A) => R, ms = 250) {
  let t: ReturnType<typeof setTimeout> | undefined;
  const debounced = (...args: A): Promise<R> =>
    new Promise((resolve, reject) => {
      if (t) clearTimeout(t);
      t = setTimeout(() => {
        try {
          resolve(fn(...args));
        } catch (e) {
          reject(e);
        }
      }, ms);
    });
  debounced.cancel = () => t && clearTimeout(t);
  return debounced;
}
