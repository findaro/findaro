"""Run the eval set against a zerch API and write eval/report.md.

    # against a running stack, creating a fresh project and importing the demo catalog:
    uv run python eval/run.py --setup
    # or against an existing project:
    uv run python eval/run.py --search-key zk_search_...

Metrics: nDCG@10 (graded: 2 = full match, 1 = right category), recall@20 (of fully relevant docs,
denominator capped at 20), zero-result rate, and latency (client wall time and server took_ms,
uncached, sequential).
"""

from __future__ import annotations

import argparse
import json
import math
import os
import platform
import statistics
import subprocess
import sys
import time
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
QUERIES = ROOT / "eval" / "queries.jsonl"
CATALOG = ROOT / "data" / "demo_catalog.jsonl"
REPORT = ROOT / "eval" / "report.md"
NOTES = ROOT / "eval" / "baseline_notes.md"  # optional hand-written notes, included in the report
RESULTS = ROOT / "eval" / "results"


def dcg(gains: list[int]) -> float:
    return sum((2**g - 1) / math.log2(i + 2) for i, g in enumerate(gains))


def ndcg_at(ids: list[str], grades: dict[str, int], k: int) -> float:
    ideal = dcg(sorted(grades.values(), reverse=True)[:k])
    return dcg([grades.get(d, 0) for d in ids[:k]]) / ideal if ideal else 0.0


def recall_at(ids: list[str], relevant: set[str], k: int) -> float:
    if not relevant:
        return 0.0
    return len(set(ids[:k]) & relevant) / min(len(relevant), k)


def pct(xs: list[float], q: float) -> float:
    xs = sorted(xs)
    return xs[min(len(xs) - 1, max(0, math.ceil(q * len(xs)) - 1))]


def setup(base: str, bootstrap: str | None) -> str:
    h = {"authorization": f"Bearer {bootstrap}"} if bootstrap else {}
    with httpx.Client(base_url=base, timeout=60) as c:
        p = c.post("/v1/projects", json={"name": f"eval-{int(time.time())}"}, headers=h).raise_for_status().json()
        admin = {"authorization": f"Bearer {p['admin_key']}"}
        with open(CATALOG, "rb") as f:
            job = c.post(f"/v1/projects/{p['project_id']}/import", headers=admin,
                         files={"file": ("demo_catalog.jsonl", f, "application/x-ndjson")}).raise_for_status().json()
        t0 = time.time()
        while True:
            st = c.get(job["status_url"], headers=admin).json()
            if st["status"] not in ("queued", "running"):
                break
            if time.time() - t0 > 900:
                sys.exit("import did not finish in 15 minutes")
            time.sleep(1)
        print(f"import {st['status']}: {st['succeeded']} docs in {time.time() - t0:.1f}s", file=sys.stderr)
        if st["status"] != "succeeded":
            sys.exit(f"import failed: {st}")
    return p["search_key"]


def post_search(c: httpx.Client, body: dict) -> tuple[dict, float]:
    """POST /v1/search, waiting out per-key rate limiting (429s are retried and not timed)."""
    while True:
        t = time.perf_counter()
        r = c.post("/v1/search", json=body)
        ms = (time.perf_counter() - t) * 1000
        if r.status_code == 429:
            time.sleep(float(r.headers.get("retry-after", "1")))
            continue
        return r.raise_for_status().json(), ms


def git_rev() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, text=True).strip()
    except Exception:  # noqa: BLE001
        return "unknown"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--base-url", default=os.environ.get("ZERCH_URL", "http://localhost:8000"))
    ap.add_argument("--search-key")
    ap.add_argument("--setup", action="store_true", help="create a project and import the demo catalog first")
    ap.add_argument("--bootstrap-token", default=os.environ.get("ZERCH_BOOTSTRAP_TOKEN"))
    ap.add_argument("--repeats", type=int, default=5, help="timed runs per query for latency")
    ap.add_argument("--label", default="M1 baseline")
    ap.add_argument("--report", default=str(REPORT))
    args = ap.parse_args()

    key = setup(args.base_url, args.bootstrap_token) if args.setup else args.search_key
    if not key:
        sys.exit("pass --search-key or --setup")
    queries = [json.loads(line) for line in QUERIES.read_text().splitlines() if line.strip()]
    headers = {"authorization": f"Bearer {key}", "cache-control": "no-cache"}
    rows = []
    client_ms: list[float] = []
    server_ms: list[float] = []
    with httpx.Client(base_url=args.base_url, headers=headers, timeout=30) as c:
        for q in queries:  # warm-up: embeddings and OS caches
            post_search(c, {"query": q["query"], "size": 20})
        for q in queries:
            res = None
            for _ in range(args.repeats):
                res, ms = post_search(c, {"query": q["query"], "size": 20})
                client_ms.append(ms)
                server_ms.append(res["took_ms"])
            ids = [h["id"] for h in res["hits"]]
            grades = {d: 1 for d in q["partial"]} | {d: 2 for d in q["relevant"]}
            rows.append({
                "id": q["id"], "query": q["query"], "type": q["type"], "total": res["total"],
                "ndcg10": ndcg_at(ids, grades, 10), "recall20": recall_at(ids, set(q["relevant"]), 20),
                "n_relevant": len(q["relevant"]), "top3": [h["document"].get("title", h["id"]) for h in res["hits"][:3]],
                "needs_review": q.get("needs_review", False),
            })

    by_type: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by_type[r["type"]].append(r)

    def agg(rs: list[dict]) -> tuple[float, float, float]:
        return (statistics.mean(r["ndcg10"] for r in rs), statistics.mean(r["recall20"] for r in rs),
                sum(r["total"] == 0 for r in rs) / len(rs))

    n_docs = sum(1 for line in CATALOG.read_text().splitlines() if line.strip())
    lines = [
        f"# Eval report — {args.label}",
        "",
        f"- Date: {datetime.now(UTC).strftime('%Y-%m-%d %H:%M UTC')} · commit `{git_rev()}`",
        f"- Catalog: `data/demo_catalog.jsonl` ({n_docs} docs) · {len(rows)} queries (`eval/queries.jsonl`)",
        f"- Machine: {platform.machine()} {platform.system()} · API at {args.base_url}",
        "- Retrieval: BM25 (cross-field + fuzzy + phonetic) ∥ k-NN (multilingual-e5-small), RRF fusion. "
        "No query understanding (M2).",
        "",
        "## Summary",
        "",
        "| Segment | Queries | nDCG@10 | Recall@20 | Zero-result rate |",
        "|---|---:|---:|---:|---:|",
    ]
    nd, rc, zr = agg(rows)
    lines.append(f"| **All** | {len(rows)} | **{nd:.3f}** | **{rc:.3f}** | {zr:.1%} |")
    for typ in ("plain", "typo", "attribute", "price", "hinglish", "nl"):
        if by_type.get(typ):
            nd, rc, zr = agg(by_type[typ])
            lines.append(f"| {typ} | {len(by_type[typ])} | {nd:.3f} | {rc:.3f} | {zr:.1%} |")
    if NOTES.exists():
        lines += ["", NOTES.read_text().strip()]
    lines += [
        "",
        "## Latency (uncached, sequential)",
        "",
        "| | p50 | p95 | p99 |",
        "|---|---:|---:|---:|",
        f"| Server `took_ms` | {pct(server_ms, .5):.1f} ms | {pct(server_ms, .95):.1f} ms | {pct(server_ms, .99):.1f} ms |",
        f"| Client wall time | {pct(client_ms, .5):.1f} ms | {pct(client_ms, .95):.1f} ms | {pct(client_ms, .99):.1f} ms |",
        "",
        f"{len(client_ms)} timed requests ({args.repeats} per query) at {n_docs} docs. "
        "See `eval/latency_10k.md` for the 10k-document benchmark (`scripts/bench.py`).",
        "",
        "## Per query",
        "",
        "| id | type | query | nDCG@10 | R@20 | #rel | total | top result |",
        "|---|---|---|---:|---:|---:|---:|---|",
    ]
    for r in rows:
        flag = " ⚑" if r["needs_review"] else ""
        top = (r["top3"][0] if r["top3"] else "—").replace("|", "/")[:70]
        lines.append(f"| {r['id']} | {r['type']}{flag} | {r['query']} | {r['ndcg10']:.2f} | {r['recall20']:.2f} | "
                     f"{r['n_relevant']} | {r['total']} | {top} |")
    if any(r["needs_review"] for r in rows):
        lines += ["", "⚑ = query/predicate marked `needs_review` in `eval/queries.jsonl`.", ""]
    else:
        lines += [""]
    Path(args.report).write_text("\n".join(lines))
    RESULTS.mkdir(exist_ok=True)
    (RESULTS / f"{datetime.now(UTC).strftime('%Y%m%dT%H%M%S')}.json").write_text(json.dumps(rows, indent=1))
    print("\n".join(lines[8:19]))
    print(f"\nwrote {args.report}")


if __name__ == "__main__":
    main()
