"""Run the eval against a zerch API and write eval/report.md.

    uv run python eval/run.py --setup                    # new project + demo catalog import, then eval
    uv run python eval/run.py --search-key zk_search_... # existing project

Passes (all with the search-result cache bypassed):
  0. warm-up: every query once, so query embeddings are cached (latency below is for warm embeddings;
     scripts/bench.py reports the cold-embedding path)
  1. quality: every query once with debug on and the LLM plan cache bypassed, so LLM-path latency is
     measured uncached. Relevance metrics come from this pass.
  2. latency: --repeats more runs per query with the plan cache on (cache hit rate comes from here)

Metrics: nDCG@10 (graded: 2 = full match, 1 = right category), recall@20 (of fully relevant docs,
denominator capped at 20), zero-result rate; compared per segment against eval/baselines/m1.json.
Also: out-of-catalog negatives (eval/negatives.jsonl) and the human holdout (eval/holdout.jsonl).
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
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
EVAL = ROOT / "eval"
CATALOG = ROOT / "data" / "demo_catalog.jsonl"
REPORT = EVAL / "report.md"
NOTES = EVAL / "notes.md"  # optional hand-written analysis, included in the report
BASELINE = EVAL / "baselines" / "m1.json"
RESULTS = EVAL / "results"
SEGMENTS = ("plain", "typo", "attribute", "price", "hinglish", "nl")
TARGETS = {"price": 0.85, "hinglish": 0.80}
MAX_REGRESSION = 0.02
P95_RULES_MS, P95_LLM_MS = 30.0, 1000.0


def dcg(gains: list[int]) -> float:
    return sum((2**g - 1) / math.log2(i + 2) for i, g in enumerate(gains))


def ndcg_at(ids: list[str], grades: dict[str, int], k: int) -> float:
    ideal = dcg(sorted(grades.values(), reverse=True)[:k])
    return dcg([grades.get(d, 0) for d in ids[:k]]) / ideal if ideal else 0.0


def recall_at(ids: list[str], relevant: set[str], k: int) -> float:
    return len(set(ids[:k]) & relevant) / min(len(relevant), k) if relevant else 0.0


def pct(xs: list[float], q: float) -> float | None:
    if not xs:
        return None
    xs = sorted(xs)
    return xs[min(len(xs) - 1, max(0, math.ceil(q * len(xs)) - 1))]


def ms(v: float | None) -> str:
    return "—" if v is None else f"{v:.1f} ms"


def load_jsonl(p: Path) -> list[dict]:
    return [json.loads(line) for line in p.read_text().splitlines() if line.strip()] if p.exists() else []


def grade_fn():
    sys.path.insert(0, str(EVAL))
    from build_queries import grade  # same grading as the main set

    return grade


def setup(base: str, bootstrap: str | None) -> str:
    h = {"authorization": f"Bearer {bootstrap}"} if bootstrap else {}
    with httpx.Client(base_url=base, timeout=60) as c:
        p = c.post("/v1/projects", json={"name": f"eval-{int(time.time())}"}, headers=h).raise_for_status().json()
        admin = {"authorization": f"Bearer {p['admin_key']}"}
        with open(CATALOG, "rb") as f:
            job = c.post(f"/v1/projects/{p['project_id']}/import", headers=admin,
                         files={"file": ("demo_catalog.jsonl", f, "application/x-ndjson")}).raise_for_status().json()
        t0 = time.time()
        while (st := c.get(job["status_url"], headers=admin).json())["status"] in ("queued", "running"):
            if time.time() - t0 > 900:
                sys.exit("import did not finish in 15 minutes")
            time.sleep(1)
        if st["status"] != "succeeded":
            sys.exit(f"import failed: {st}")
        print(f"imported {st['succeeded']} docs in {time.time() - t0:.0f}s", file=sys.stderr)
    return p["admin_key"]  # admin can search too, and may bypass the plan cache for uncached LLM timings


class Client:
    def __init__(self, base: str, key: str):
        self.c = httpx.Client(base_url=base, timeout=60,
                              headers={"authorization": f"Bearer {key}", "cache-control": "no-cache"})

    def search(self, body: dict, bypass_plans: bool = False) -> dict:
        headers = {"x-zerch-plan-cache": "bypass"} if bypass_plans else {}
        while True:
            r = self.c.post("/v1/search", json=body, headers=headers)
            if r.status_code == 429:  # per-key rate limit: wait it out
                time.sleep(float(r.headers.get("retry-after", "1")))
                continue
            return r.raise_for_status().json()


def llm_status(res: dict) -> str:
    return ((res.get("debug") or {}).get("llm") or {}).get("llm", "not_needed")


def llm_path(res: dict) -> str:
    """rules | llm (called/timeout/error, uncached) | cache"""
    return {"not_needed": "rules", "unavailable": "rules", "cache": "cache"}.get(llm_status(res), "llm")


def git_rev() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, text=True).strip()
    except Exception:  # noqa: BLE001
        return "unknown"


def evaluate(cl: Client, queries: list[dict], repeats: int) -> tuple[list[dict], dict[str, list[float]]]:
    for q in queries:
        cl.search({"query": q["query"], "size": 20})
    rows = []
    lat: dict[str, list[float]] = defaultdict(list)
    for q in queries:
        res = cl.search({"query": q["query"], "size": 20, "debug": True}, bypass_plans=True)
        lat[f"pass1:{llm_path(res)}"].append(res["took_ms"])
        ids = [h["id"] for h in res["hits"]]
        grades = {d: 1 for d in q["partial"]} | {d: 2 for d in q["relevant"]}
        und = res.get("understood") or {}
        rows.append({
            "id": q["id"], "query": q["query"], "type": q["type"], "total": res["total"],
            "ndcg10": ndcg_at(ids, grades, 10), "recall20": recall_at(ids, set(q["relevant"]), 20),
            "n_relevant": len(q["relevant"]),
            "top": res["hits"][0]["document"].get("title", "") if res["hits"] else "",
            "chips": [c["label"] for c in und.get("chips", [])], "quality": und.get("match_quality"),
            "source": und.get("source"), "llm": llm_status(res),
            "relaxed": [r["label"] for r in und.get("relaxations", [])],
            "needs_review": q.get("needs_review", False),
        })
    for _ in range(repeats):
        for q in queries:
            res = cl.search({"query": q["query"], "size": 20, "debug": True})
            lat[f"warm:{llm_path(res)}"].append(res["took_ms"])
    return rows, lat


def seg_table(rows: list[dict], base: dict[str, dict] | None) -> tuple[list[str], dict[str, float]]:
    by: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by[r["type"]].append(r)
    out = ["| Segment | n | M1 nDCG@10 | **M2 nDCG@10** | Δ | M1 R@20 | M2 R@20 | zero-result |",
           "|---|---:|---:|---:|---:|---:|---:|---:|"]
    m2: dict[str, float] = {}

    def line(name: str, rs: list[dict]) -> None:
        nd = statistics.mean(r["ndcg10"] for r in rs)
        rc = statistics.mean(r["recall20"] for r in rs)
        zr = sum(r["total"] == 0 for r in rs) / len(rs)
        m2[name] = nd
        b = [base[r["id"]] for r in rs if r["id"] in base] if base else []
        nm = f"**{name}**" if name == "All" else name
        if b:
            bnd = statistics.mean(x["ndcg10"] for x in b)
            brc = statistics.mean(x["recall20"] for x in b)
            out.append(f"| {nm} | {len(rs)} | {bnd:.3f} | **{nd:.3f}** | {nd - bnd:+.3f} | {brc:.3f} | {rc:.3f} | "
                       f"{zr:.0%} |")
        else:
            out.append(f"| {nm} | {len(rs)} | — | **{nd:.3f}** | — | — | {rc:.3f} | {zr:.0%} |")

    line("All", rows)
    for s in SEGMENTS:
        if by.get(s):
            line(s, by[s])
    for s in sorted(set(by) - set(SEGMENTS)):
        line(s, by[s])
    return out, m2


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--base-url", default=os.environ.get("ZERCH_URL", "http://localhost:8000"))
    ap.add_argument("--search-key", help="search key, or the admin key to also measure uncached LLM planner calls "
                                         "(the plan-cache bypass header is admin-only)")
    ap.add_argument("--setup", action="store_true")
    ap.add_argument("--bootstrap-token", default=os.environ.get("ZERCH_BOOTSTRAP_TOKEN"))
    ap.add_argument("--repeats", type=int, default=5)
    ap.add_argument("--label", default="M2 query understanding")
    ap.add_argument("--planner", default="see docker-compose.yml", help="planner LLM, for the report header")
    ap.add_argument("--report", default=str(REPORT))
    args = ap.parse_args()

    key = setup(args.base_url, args.bootstrap_token) if args.setup else args.search_key
    if not key:
        sys.exit("pass --search-key or --setup")
    cl = Client(args.base_url, key)
    queries = load_jsonl(EVAL / "queries.jsonl")
    base = {r["id"]: r for r in json.loads(BASELINE.read_text())} if BASELINE.exists() else None

    rows, lat = evaluate(cl, queries, args.repeats)

    neg = []  # nothing relevant exists for these
    for q in load_jsonl(EVAL / "negatives.jsonl"):
        res = cl.search({"query": q["query"], "size": 5, "debug": True})
        neg.append({"query": q["query"], "quality": (res.get("understood") or {}).get("match_quality"),
                    "total": res["total"], "top": res["hits"][0]["document"].get("title", "") if res["hits"] else ""})

    hold_rows: list[dict] = []  # graded with the same predicate rules; never tuned on
    holdout = load_jsonl(EVAL / "holdout.jsonl")
    if holdout:
        grade = grade_fn()
        docs = load_jsonl(CATALOG)
        for h in holdout:
            h["relevant"] = [d["id"] for d in docs if grade(d, h["predicate"]) == 2]
            h["partial"] = [d["id"] for d in docs if grade(d, h["predicate"]) == 1]
            h.setdefault("type", "holdout")
        hold_rows, _ = evaluate(cl, holdout, 0)

    # LLM-path probe: in-catalog queries with words the rules can't read. Pass A is uncached (timeouts
    # fall back to the rules plan); pass B runs after late LLM answers have landed in the plan cache.
    probe = load_jsonl(EVAL / "llm_queries.jsonl")
    probe_rows: list[dict] = []
    if probe:
        grade = grade_fn()
        docs = load_jsonl(CATALOG)
        for h in probe:
            h["relevant"] = [d["id"] for d in docs if grade(d, h["predicate"]) == 2]
            h["partial"] = [d["id"] for d in docs if grade(d, h["predicate"]) == 1]
        for h in probe:
            res = cl.search({"query": h["query"], "size": 20, "debug": True}, bypass_plans=True)
            ids = [x["id"] for x in res["hits"]]
            grades = {d: 1 for d in h["partial"]} | {d: 2 for d in h["relevant"]}
            dbg = (res.get("debug") or {}).get("llm") or {}
            probe_rows.append({"query": h["query"], "llm": dbg.get("llm", "not_needed"), "llm_ms": dbg.get("llm_ms"),
                               "took": res["took_ms"], "ndcg_a": ndcg_at(ids, grades, 10), "_grades": grades,
                               "sem_a": (res.get("understood") or {}).get("semantic_text")})
        time.sleep(8)
        for pr in probe_rows:
            res = cl.search({"query": pr["query"], "size": 20, "debug": True})
            ids = [x["id"] for x in res["hits"]]
            pr["ndcg_b"] = ndcg_at(ids, pr.pop("_grades"), 10)
            pr["source_b"] = (res.get("understood") or {}).get("source")
            pr["sem_b"] = (res.get("understood") or {}).get("semantic_text")

    seg_lines, m2 = seg_table(rows, base)
    reviewed = [r for r in rows if not r["needs_review"]]
    n_docs = sum(1 for line in CATALOG.read_text().splitlines() if line.strip())
    llm_needed = [r for r in rows if r["llm"] != "not_needed"]
    outcome = Counter(r["llm"] for r in llm_needed)
    warm_llm = lat.get("warm:cache", []) + lat.get("warm:llm", [])
    cache_hits = len(lat.get("warm:cache", []))
    rules_p95 = pct(lat.get("warm:rules", []), .95)
    llm_p95 = pct(lat.get("pass1:llm", []), .95)

    def verdict(ok: bool | None) -> str:
        return "—" if ok is None else ("✅ met" if ok else "❌ missed")

    base_seg = {}
    if base:
        for s in SEGMENTS:
            b = [base[r["id"]]["ndcg10"] for r in rows if r["type"] == s and r["id"] in base]
            if b:
                base_seg[s] = statistics.mean(b)
    regress = {s: m2[s] - base_seg[s] for s in base_seg if s in m2}
    worst = min(regress.items(), key=lambda kv: kv[1]) if regress else None

    L = [f"# Eval report — {args.label}", "",
         f"- Date: {datetime.now(UTC).strftime('%Y-%m-%d %H:%M UTC')} · commit `{git_rev()}` · "
         f"{platform.machine()} {platform.system()}",
         f"- Catalog: `data/demo_catalog.jsonl` ({n_docs} docs) · {len(rows)} queries · "
         f"{len(neg)} out-of-catalog negatives · {len(hold_rows)} holdout queries",
         f"- Planner LLM: {args.planner}",
         (f"- Baseline: `eval/baselines/m1.json` (M1 on the reviewed query set, nDCG@10 "
          f"{statistics.mean(b['ndcg10'] for b in base.values()):.3f}); M1 report kept in `eval/report_m1.md`")
         if base else "- Baseline: none",
         "", "## Targets", "", "| Target | Result | |", "|---|---|---|"]
    for s, t in TARGETS.items():
        L.append(f"| {s} nDCG@10 ≥ {t} | {m2.get(s, 0):.3f} | {verdict(m2.get(s, 0) >= t)} |")
    if worst:
        L.append(f"| no segment regresses by more than {MAX_REGRESSION} | worst: {worst[0]} {worst[1]:+.3f} | "
                 f"{verdict(worst[1] >= -MAX_REGRESSION)} |")
    L.append(f"| server p95 ≤ {P95_RULES_MS:.0f} ms, rules-only path | {ms(rules_p95)} | "
             f"{verdict(None if rules_p95 is None else rules_p95 <= P95_RULES_MS)} |")
    L.append(f"| server p95 ≤ {P95_LLM_MS:.0f} ms, LLM path uncached | {ms(llm_p95)} "
             f"(n={len(lat.get('pass1:llm', []))}) | {verdict(None if llm_p95 is None else llm_p95 <= P95_LLM_MS)} |")
    L += ["", "## Relevance vs M1", ""] + seg_lines
    if len(reviewed) != len(rows):
        L += ["", f"Excluding the {len(rows) - len(reviewed)} queries still marked `needs_review`:", ""]
        L += seg_table(reviewed, base)[0]
    if NOTES.exists():
        L += ["", NOTES.read_text().strip()]
    L += ["", "## Query planner", "",
          f"- LLM needed (rules plan unsure): **{len(llm_needed)}/{len(rows)}** queries "
          f"({len(llm_needed) / len(rows):.0%}). Outcomes on the uncached pass: "
          + (", ".join(f"{k} {v}" for k, v in sorted(outcome.items())) or "none"),
          "- Plan cache hit rate on repeat runs (LLM-needed queries): "
          + (f"**{cache_hits / len(warm_llm):.0%}** ({cache_hits}/{len(warm_llm)})" if warm_llm else "n/a"),
          f"- Queries where a filter was relaxed after zero results: {sum(1 for r in rows if r['relaxed'])}",
          "", "### Latency by path (server `took_ms`, query embeddings warm)", "",
          "| Path | n | p50 | p95 | p99 |", "|---|---:|---:|---:|---:|"]
    for k, label in (("warm:rules", "rules only"), ("pass1:llm", "LLM, uncached (incl. timeouts)"),
                     ("warm:cache", "LLM plan from cache"), ("warm:llm", "LLM again (cache not filled yet)")):
        xs = lat.get(k, [])
        if xs:
            L.append(f"| {label} | {len(xs)} | {ms(pct(xs, .5))} | {ms(pct(xs, .95))} | {ms(pct(xs, .99))} |")
    if probe_rows:
        called = [p for p in probe_rows if p["llm"] != "not_needed"]
        lat_called = [p["took"] for p in called]
        L += ["", f"### LLM path probe (`eval/llm_queries.jsonl`, {len(probe_rows)} queries with words the rules "
              "can't read)", "",
              f"- Reached the LLM: {len(called)}/{len(probe_rows)}; outcomes: "
              + ", ".join(f"{k} {v}" for k, v in sorted(Counter(p['llm'] for p in called).items())),
              f"- Server latency, uncached: p50 {ms(pct(lat_called, .5))}, p95 {ms(pct(lat_called, .95))}",
              f"- nDCG@10 uncached (timeouts fall back to rules): **{statistics.mean(p['ndcg_a'] for p in probe_rows):.3f}**"
              f" · with the LLM plan from cache: **{statistics.mean(p['ndcg_b'] for p in probe_rows):.3f}**", "",
              "| query | LLM (uncached) | took | nDCG uncached | nDCG cached plan | semantic text (cached plan) |",
              "|---|---|---:|---:|---:|---|"]
        for p in probe_rows:
            L.append(f"| {p['query']} | {p['llm']} | {ms(p['took'])} | {p['ndcg_a']:.2f} | {p['ndcg_b']:.2f} | "
                     f"{(p['sem_b'] or '').replace('|', '/')} |")
    L += ["", "Cold-embedding and 10k-document numbers: `eval/latency_10k.md` (`scripts/bench.py`).", "",
          "## Out-of-catalog queries", "",
          f"`match_quality` on {len(neg)} queries with nothing relevant in the catalog: "
          + ", ".join(f"{k} {v}" for k, v in sorted(Counter(n['quality'] for n in neg).items())), "",
          "| query | match_quality | total | top result |", "|---|---|---:|---|"]
    for n in neg:
        L.append(f"| {n['query']} | {n['quality']} | {n['total']} | {n['top'][:60].replace('|', '/')} |")
    if hold_rows:
        L += ["", "## Holdout (never tuned on)", ""] + seg_table(hold_rows, None)[0]
    else:
        L += ["", "## Holdout", "", "`eval/holdout.jsonl` is empty. Add queries (format in `eval/README.md`) and rerun."]
    L += ["", "## Per query", "",
          "| id | type | query | M1 | M2 | R@20 | understood | quality | top result |",
          "|---|---|---|---:|---:|---:|---|---|---|"]
    for r in rows:
        b = base.get(r["id"], {}).get("ndcg10") if base else None
        chips = ", ".join(r["chips"]) + (f" (relaxed: {', '.join(r['relaxed'])})" if r["relaxed"] else "")
        llm = "" if r["llm"] == "not_needed" else f" [llm: {r['llm']}]"
        b_txt = "" if b is None else f"{b:.2f}"
        L.append(f"| {r['id']} | {r['type']} | {r['query']} | {b_txt} | {r['ndcg10']:.2f} | {r['recall20']:.2f} | "
                 f"{chips.replace('|', '/')}{llm} | {r['quality']} | {r['top'][:55].replace('|', '/')} |")
    L.append("")
    # keep the M3 chat section (written by eval/run_chat.py) when regenerating
    old = Path(args.report).read_text() if Path(args.report).exists() else ""
    m3 = old[old.index("<!-- M3:BEGIN -->"): old.index("<!-- M3:END -->") + len("<!-- M3:END -->")] \
        if "<!-- M3:BEGIN -->" in old and "<!-- M3:END -->" in old else ""
    Path(args.report).write_text("\n".join(L) + ("\n" + m3 + "\n" if m3 else ""))
    RESULTS.mkdir(exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S")
    (RESULTS / f"{stamp}.json").write_text(json.dumps({"rows": rows, "negatives": neg, "holdout": hold_rows,
                                                       "llm_probe": probe_rows, "latency": lat}, indent=1))
    print("\n".join(L[: L.index("## Per query")]))
    print(f"wrote {args.report}")


if __name__ == "__main__":
    main()
