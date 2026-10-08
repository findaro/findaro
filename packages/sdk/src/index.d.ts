/**
 * @zerch/sdk — headless client for the zerch search API. Zero runtime dependencies.
 *
 *   const zerch = createClient({ projectId: "prj_…", searchKey: "zk_search_…", baseUrl: "https://…" });
 *   const res = await zerch.search("black shoes under 1000");
 *   for await (const ev of zerch.chat("sasta wala", { sessionId })) { … }
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
export type ChatEvent = {
    type: "session";
    data: SessionEvent;
} | {
    type: "plan";
    data: PlanEvent;
} | {
    type: "results";
    data: ResultsEvent;
} | {
    type: "clarify";
    data: ClarifyEvent;
} | {
    type: "text";
    data: TextEvent;
} | {
    type: "done";
    data: DoneEvent;
};
export interface ClientOptions {
    /** Your project id (prj_…). Used to scope sessions; the search key already identifies the project. */
    projectId: string;
    /** The browser-safe search key (zk_search_…). Never put an admin key in a browser. */
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
    onSession?: (e: SessionEvent) => void;
    onPlan?: (e: PlanEvent) => void;
    onResults?: (e: ResultsEvent) => void;
    onClarify?: (e: ClarifyEvent) => void;
    onText?: (e: TextEvent, fullText: string) => void;
    onDone?: (e: DoneEvent) => void;
    onError?: (err: Error) => void;
}
export interface ChatResult {
    sessionId: string | null;
    text: string;
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
export declare class ZerchError extends Error {
    readonly status: number;
    readonly code: string;
    constructor(message: string, status: number, code: string);
}
export interface ZerchClient {
    readonly projectId: string;
    search(q: string | SearchParams, opts?: RequestOptions): Promise<SearchResponse>;
    chat(message: string, opts?: ChatOptions): ChatStream;
}
export declare function createClient(options: ClientOptions): ZerchClient;
/** Debounce helper for search-as-you-type: `const run = debounce((q) => zerch.search(q), 250)`. */
export declare function debounce<A extends unknown[], R>(fn: (...args: A) => R, ms?: number): {
    (...args: A): Promise<R>;
    cancel(): void | 0 | undefined;
};
export {};
