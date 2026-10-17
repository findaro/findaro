/**
 * AI Mode conversations, kept in this browser's localStorage per project (key findaro:chats:<projectId>).
 * Only what the thread needs to re-render is stored: messages, and for result turns at most 12 trimmed hits.
 * The search key is never stored. Storage can be missing or full: every access is wrapped and failures are ignored.
 */
import type { ClarifyEvent, Display, Hit } from "@findaro/sdk";

export interface Turn {
  role: "user" | "assistant";
  text: string;
  time: number;
  general?: string;
  clarify?: ClarifyEvent | null;
  /** what the search understood: chip labels and [label, reason] of loosened filters */
  plan?: { chips: string[]; relax: [string, string][] } | null;
  /** inline results: heading, total and the hits shown as cards */
  res?: { q: string; total: number; hits: Hit[]; close: string[]; weak?: boolean } | null;
  /** products compared in this turn (client-side table) */
  compare?: Hit[] | null;
  /** done.timings.total, ms */
  ms?: number | null;
  /** user turn sent as a patch (a clicked refinement), not typed */
  patch?: boolean;
  // transient UI state (not stored)
  pending?: boolean;
  error?: boolean;
  step?: string;
  more?: boolean;
  open?: boolean;
}

export interface Conv {
  id: string;
  title: string;
  updatedAt: number;
  sessionId: string | null;
  display?: Display;
  msgs: Turn[];
}

const MAX_CONVS = 30;
const MAX_HITS = 12;
const storeKey = (project: string) => `findaro:chats:${project}`;

export function loadChats(project: string): Conv[] {
  try {
    const v = JSON.parse(localStorage.getItem(storeKey(project)) || "[]");
    return Array.isArray(v) ? v.filter((c) => c && typeof c.id === "string" && Array.isArray(c.msgs)) : [];
  } catch {
    return [];
  }
}

/** Saves newest first, at most 30; when storage is full, drops the oldest until it fits. Returns what was kept. */
export function saveChats(project: string, convs: Conv[]): Conv[] {
  let list = [...convs].sort((a, b) => b.updatedAt - a.updatedAt).slice(0, MAX_CONVS);
  for (;;) {
    try {
      localStorage.setItem(storeKey(project), JSON.stringify(list));
      return list;
    } catch {
      if (list.length <= 1) return list;
      list = list.slice(0, -1);
    }
  }
}

/** A hit with only what a card, the compare table and the product drawer's short facts need. */
function slimHit(hit: Hit, keep: Set<string>): Hit {
  const doc: Record<string, unknown> = {};
  for (const [k, v] of Object.entries(hit.document)) {
    if (keep.has(k) || typeof v === "number" || typeof v === "boolean"
        || typeof v === "string" && v.length <= 60 || Array.isArray(v) && JSON.stringify(v).length <= 80) doc[k] = v;
  }
  return { id: hit.id, score: 0, document: doc, ...(hit.requirements ? { requirements: hit.requirements } : {}) };
}

export function slimTurn(t: Turn, keep: Set<string>): Turn {
  const { pending: _p, error: _e, step: _s, more: _m, open: _o, ...rest } = t;
  if (rest.res) rest.res = { ...rest.res, hits: rest.res.hits.slice(0, MAX_HITS).map((x) => slimHit(x, keep)) };
  if (rest.compare) rest.compare = rest.compare.map((x) => slimHit(x, keep));
  return rest;
}
