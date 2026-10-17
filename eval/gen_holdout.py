"""Generate eval/holdout.jsonl with an independent LLM (not the model that wrote the locale packs).

Targets (category + optional attribute + optional budget) are sampled from the demo catalog; the LLM
writes a natural Hinglish query for each without seeing packs/locales/*.yaml or eval/queries.jsonl.
The sampled target is the ground-truth predicate. Rows are marked needs_review for a human pass.

    uv run python eval/gen_holdout.py --n 20   # local Ollama by default; paid providers only when asked
"""

from __future__ import annotations

import argparse
import asyncio
import json
import random
from collections import Counter
from pathlib import Path

from findaro.llm import get_llm
from findaro.llm.base import parse_json

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "eval" / "holdout.jsonl"

SYSTEM = ("You write realistic search queries that Indian shoppers type into an online store's search box. "
          "Reply with JSON only.")

PROMPT = """Write {k} different search queries a shopper in India might type to find the product described below.
Write them in Hinglish: Hindi words typed in Latin letters, mixed with English the way people really type
(e.g. "ke liye", "wala", "chahiye", "sasta", "ke andar"). Make each one sound like a different person:
vary length (2 to 9 words), word order, spelling and how much Hindi vs English they use. Do not copy the
category name word for word in every query; use everyday words people would actually say.
{budget_rule}

Product the shopper wants:
{target}

Reply as JSON: {{"queries": ["...", "..."]}}"""


def leaf_categories(docs):
    return Counter(d["category"] for d in docs)


def sample_targets(docs, n, seed):
    rng = random.Random(seed)
    cats = sorted(leaf_categories(docs))
    rng.shuffle(cats)
    targets = []
    for cat in cats:
        if len(targets) >= n:
            break
        in_cat = [d for d in docs if d["category"] == cat]
        pred = {"cat": cat}
        desc = [f"- type of product: {cat.split(' > ')[-1]} (catalog section: {cat})"]
        roll = rng.random()
        attrs = [k for k in ("color", "material", "gender") if all(k in d for d in in_cat)]
        if attrs and roll < 0.6:
            k = rng.choice(attrs)
            vals = Counter(str(d[k]) for d in in_cat)
            v = rng.choice([v for v, c in vals.items() if c >= 3] or list(vals))
            pred[k] = v
            desc.append(f"- {k}: {v}")
        if rng.random() < 0.45:
            prices = sorted(d["price"] for d in in_cat)
            cap = prices[len(prices) // 2]
            cap = int(round(cap / 100.0)) * 100 or cap
            pred["price_max"] = cap
            desc.append(f"- budget: at most ₹{cap}")
        rel = [d for d in in_cat if all(
            (k == "cat") or (k == "price_max" and d["price"] <= v) or (str(d.get(k)) == str(v))
            for k, v in pred.items())]
        if len(rel) >= 2:
            targets.append((pred, "\n".join(desc)))
    return targets


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--provider", default="ollama")
    ap.add_argument("--model", default="llama3.1:8b")
    ap.add_argument("--n", type=int, default=20)
    ap.add_argument("--seed", type=int, default=2026)
    args = ap.parse_args()
    docs = [json.loads(line) for line in (ROOT / "data" / "demo_catalog.jsonl").read_text().splitlines() if line]
    llm = get_llm(args.provider, args.model)
    targets = sample_targets(docs, args.n, args.seed)
    rng = random.Random(args.seed + 1)
    rows = []
    for i, (pred, desc) in enumerate(targets, 1):
        budget_rule = ("Mention the budget in the query." if "price_max" in pred
                       else "Do not mention any price or budget.")
        raw = await llm.complete(PROMPT.format(k=3, target=desc, budget_rule=budget_rule), system=SYSTEM,
                                 json_mode=True, max_tokens=600)
        qs = [q for q in parse_json(raw).get("queries", []) if isinstance(q, str) and q.strip()]
        q = rng.choice(qs)  # one per target, picked at random so no one looks at them first
        rows.append({"id": f"h{i:03d}", "query": q.strip(), "type": "hinglish", "predicate": pred,
                     "needs_review": True, "written_by": llm.name})
        print(f"h{i:03d}  {q.strip()!r:60}  {json.dumps(pred, ensure_ascii=False)}")
    OUT.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows))
    print(f"wrote {len(rows)} queries to {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    asyncio.run(main())
