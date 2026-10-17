"""Pick FINDARO_MATCH_FLOOR: the k-NN score below which a vector-only result set means "no match".

Runs every query in queries.jsonl (all have relevant products) and negatives.jsonl (none do) with
debug on, looks at queries with no lexical match, and picks the highest floor that keeps every in-catalog
query above it. Uses the main eval set only; never the holdout.

    uv run python eval/calibrate_floor.py --search-key fdr_search_...
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", default="http://localhost:8000")
    ap.add_argument("--search-key", required=True)
    ap.add_argument("--margin", type=float, default=0.002)
    args = ap.parse_args()
    h = {"authorization": f"Bearer {args.search_key}", "cache-control": "no-cache"}
    rows = []
    with httpx.Client(base_url=args.base_url, headers=h, timeout=60) as c:
        for fname, positive in (("queries.jsonl", True), ("negatives.jsonl", False)):
            for line in (ROOT / fname).read_text().splitlines():
                if not line.strip():
                    continue
                q = json.loads(line)["query"]
                r = c.post("/v1/search", json={"query": q, "size": 1, "debug": True}).json()
                rows.append((positive, q, r["debug"]["lexical_hits"], r["debug"]["vector_top_score"] or 0.0))
    vec_only_pos = sorted(vt for p, _, lex, vt in rows if p and lex == 0)
    floor = (vec_only_pos[0] - args.margin) if vec_only_pos else 0.0
    print(f"in-catalog queries with no lexical match: {len(vec_only_pos)}; lowest vector score "
          f"{vec_only_pos[0] if vec_only_pos else None}")
    print(f"suggested FINDARO_MATCH_FLOOR={floor:.4f}\n")
    for p, q, lex, vt in sorted(rows, key=lambda r: (r[0], r[3])):
        if lex == 0:
            verdict = ("none" if vt < floor else "weak")
            print(f"{'IN ' if p else 'OUT'} lex={lex:3d} vec={vt:.4f} -> {verdict:4}  {q}")
    caught = sum(1 for p, _, lex, vt in rows if not p and lex == 0 and vt < floor)
    print(f"\nnegatives answered 'none': {caught}/{sum(1 for r in rows if not r[0])}")


if __name__ == "__main__":
    main()
