"""Product-conversation eval (M5): multi-turn chats focused on one product, against /v1/chat with product_ids.

Picks 12 demo products (seeded, across categories, some with origin/warranty deliberately unlisted) and asks each
4 questions in English or Hinglish. Automatic checks per answer (the facts part, not the general tip):
- fact questions (material, origin, warranty, care, returns): the listed value appears, or, when the field isn't
  listed, the answer says so; when the field IS listed, saying "not listed" is an error
- suitability questions: no yes/no verdict in the facts part
Every answer is saved to eval/results/product-chat-*.json for manual review. Local models only; no paid calls.

    uv run python eval/run_product_chat.py --search-key fdr_search_...
"""

from __future__ import annotations

import argparse
import json
import random
import re
import statistics
import time
from datetime import UTC, datetime
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
EVAL = ROOT / "eval"

QUESTIONS = {
    "material": ["What is it made of?", "Ye kis material ka bana hai?"],
    "country_of_origin": ["Is this made in India or imported?", "Ye kahan bana hai?"],
    "warranty": ["Does it come with a warranty?", "Warranty milegi kya?"],
    "care": ["How should I take care of it?", "Iski dekhbhal kaise karein?"],
    "return_policy": ["Can I return it if I don't like it?", "Pasand na aaye to return ho jayega?"],
    "suitability": ["Is it good for daily use in the monsoon?", "Kya ye roz use ke liye theek hai?"],
}
NOT_LISTED = re.compile(r"(not listed|hasn't listed|has not listed|isn't listed|doesn't (say|mention|list)|"
                        r"not mentioned|not specified|nahi (bataya|diya|likha)|listing doesn't|seller doesn't say|"
                        r"couldn't answer)", re.I)
VERDICT = re.compile(r"\b(yes|haan|definitely|absolutely)\b|\b(can|could) (be )?(wear|worn|use|used)\b|"
                     r"\b(suitable|perfect|ideal|great|fine|okay|ok) (for|to)\b|\bwaterproof\b", re.I)


def pick_products(docs: list[dict], n: int, seed: int) -> list[dict]:
    rng = random.Random(seed)
    by_top: dict[str, list[dict]] = {}
    for d in docs:
        by_top.setdefault(d["category"].split(" > ")[0], []).append(d)
    picks: list[dict] = []
    for top in sorted(by_top):
        pool = by_top[top]
        missing = [d for d in pool if "country_of_origin" not in d]
        picks.append(rng.choice(pool))
        if missing:
            picks.append(rng.choice(missing))  # one product per category with origin unlisted
    return picks[:n]


def chat(c: httpx.Client, body: dict) -> tuple[str, str, dict, float | None]:
    answer, general, done, first = "", "", {}, None
    t0 = time.perf_counter()
    with c.stream("POST", "/v1/chat", json=body, timeout=180) as r:
        r.raise_for_status()
        ev = None
        for line in r.iter_lines():
            if line.startswith("event: "):
                ev = line[7:]
            elif line.startswith("data: "):
                d = json.loads(line[6:])
                if ev == "session":
                    body["session_id"] = d["session_id"]
                elif ev == "text":
                    first = first or (time.perf_counter() - t0) * 1000
                    if d.get("part") == "general":
                        general += d["delta"]
                    else:
                        answer += d["delta"]
                elif ev == "done":
                    done = d
    return " ".join(answer.split()), " ".join(general.split()), done, first


def score(kind: str, doc: dict, answer: str) -> tuple[bool, str]:
    if kind == "suitability":
        return (not VERDICT.search(answer), "verdict in facts part" if VERDICT.search(answer) else "")
    value = doc.get(kind)
    if value is None:
        return (bool(NOT_LISTED.search(answer)), "" if NOT_LISTED.search(answer) else "should say not listed")
    if NOT_LISTED.search(answer) and kind != "care":
        return False, "said not listed but it is listed"
    stem = lambda w: w[:-1] if w.endswith("s") else w  # noqa: E731  ("6 months" vs "6-month")
    words = [stem(w) for w in re.findall(r"[a-z]+", str(value).lower()) if len(w) > 2][:3]
    ok = all(w in answer.lower() for w in words) or kind == "care" and len(answer) > 20
    return ok, "" if ok else f"listed value '{value}' not in answer"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", default="http://localhost:8000")
    ap.add_argument("--search-key", required=True)
    ap.add_argument("--seed", type=int, default=7)
    args = ap.parse_args()
    docs = [json.loads(line) for line in (ROOT / "data" / "demo_catalog.jsonl").read_text().splitlines() if line]
    products = pick_products(docs, 12, args.seed)
    rng = random.Random(args.seed)
    c = httpx.Client(base_url=args.base_url, headers={"authorization": f"Bearer {args.search_key}"})
    rows = []
    for doc in products:
        kinds = ["material", "country_of_origin", "warranty", "care", "return_policy", "suitability"]
        if "material" not in doc:
            kinds.remove("material")
        chosen = rng.sample(kinds, 4)
        body: dict = {"product_ids": [doc["id"]]}
        for kind in chosen:
            q = rng.choice(QUESTIONS[kind])
            body["message"] = q
            answer, general, done, first = chat(c, body)
            ok, why = score(kind, doc, answer)
            rows.append({"id": doc["id"], "title": doc["title"][:70], "kind": kind, "q": q, "answer": answer,
                         "general": general, "ok": ok, "why": why, "listed": doc.get(kind) if kind != "suitability"
                         else None, "first_ms": first, "source": done.get("answer_source"),
                         "turn_type": done.get("turn_type")})
            print(f"{'✓' if ok else '✗'} {doc['id']} {kind:17} {q[:38]:38} → {answer[:90]}")
    out = EVAL / "results" / f"product-chat-{datetime.now(UTC).strftime('%Y%m%dT%H%M%S')}.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(rows, indent=1, ensure_ascii=False))
    by_kind: dict[str, list[bool]] = {}
    for r in rows:
        by_kind.setdefault(r["kind"], []).append(r["ok"])
    firsts = sorted(r["first_ms"] for r in rows if r["first_ms"])
    print(f"\nautomatic checks: {sum(r['ok'] for r in rows)}/{len(rows)} · " +
          ", ".join(f"{k} {sum(v)}/{len(v)}" for k, v in by_kind.items()))
    print(f"turn type product: {sum(r['turn_type'] == 'product' for r in rows)}/{len(rows)} · "
          f"general tips: {sum(bool(r['general']) for r in rows)} · fallbacks: "
          f"{sum(r['source'] == 'fallback' for r in rows)} · first token p50 {statistics.median(firsts):.0f} ms, "
          f"p95 {firsts[int(len(firsts) * .95) - 1]:.0f} ms")
    print(f"saved {out.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
