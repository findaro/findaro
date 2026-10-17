"""Latency benchmark at ~10k documents. Writes eval/latency_10k.md.

Run it with the per-key rate limit lifted, or throughput is capped at the limit:
    FINDARO_RATE_LIMIT_PER_SECOND=0 docker compose up -d api

Builds a 10k-doc catalog by replicating data/demo_catalog.jsonl (new ids, jittered prices), imports
it into a fresh project, then replays the eval queries uncached, sequentially and with concurrency.

    uv run python scripts/bench.py [--docs 10000] [--base-url http://localhost:8000]
"""

from __future__ import annotations

import argparse
import asyncio
import io
import json
import math
import platform
import random
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent


def pct(xs: list[float], q: float) -> float:
    xs = sorted(xs)
    return xs[min(len(xs) - 1, max(0, math.ceil(q * len(xs)) - 1))]


def build_docs(n: int) -> bytes:
    base = [json.loads(line) for line in (ROOT / "data" / "demo_catalog.jsonl").read_text().splitlines() if line]
    rng = random.Random(1)
    out = io.StringIO()
    for i in range(n):
        d = dict(base[i % len(base)])
        rep = i // len(base)
        if rep:
            d["id"] = f"{d['id']}-r{rep}"
            d["price"] = max(49, int(d["price"] * rng.uniform(0.8, 1.2)) // 10 * 10 + 9)
        out.write(json.dumps(d, ensure_ascii=False) + "\n")
    return out.getvalue().encode()


async def run(args: argparse.Namespace) -> None:
    queries = [json.loads(line)["query"] for line in (ROOT / "eval" / "queries.jsonl").read_text().splitlines()
               if line.strip()]
    async with httpx.AsyncClient(base_url=args.base_url, timeout=120) as c:
        p = (await c.post("/v1/projects", json={"name": "bench-10k"})).raise_for_status().json()
        admin = {"authorization": f"Bearer {p['admin_key']}"}
        data = build_docs(args.docs)
        t0 = time.time()
        job = (await c.post(f"/v1/projects/{p['project_id']}/import", headers=admin,
                            files={"file": ("bench.jsonl", data, "application/x-ndjson")})).raise_for_status().json()
        while (st := (await c.get(job["status_url"], headers=admin)).json())["status"] in ("queued", "running"):
            await asyncio.sleep(1)
        ingest_s = time.time() - t0
        print(f"ingested {st['succeeded']} docs in {ingest_s:.1f}s ({st['status']})", file=sys.stderr)
        h = {"authorization": f"Bearer {p['search_key']}", "cache-control": "no-cache"}
        for q in queries:
            if (await c.post("/v1/search", json={"query": q}, headers=h)).status_code == 429:
                await asyncio.sleep(1)

        results = {}
        # Cold: a unique number per request forces a fresh query embedding (CPU e5 inference). A number,
        # not a word: an unknown word would send the query to the LLM planner instead.
        cold_c: list[float] = []
        cold_s: list[float] = []
        t = time.perf_counter()
        for i, q in enumerate(queries * 2):
            t1 = time.perf_counter()
            r = await c.post("/v1/search", json={"query": f"{q} {i + 2}", "size": 20}, headers=h)
            r.raise_for_status()
            cold_c.append((time.perf_counter() - t1) * 1000)
            cold_s.append(r.json()["took_ms"])
        results["1 (cold embedding)"] = (cold_c, cold_s, len(cold_c) / (time.perf_counter() - t))
        for conc in args.concurrency:
            client_ms: list[float] = []
            server_ms: list[float] = []
            work = [q for _ in range(args.repeats) for q in queries]
            sem = asyncio.Semaphore(conc)

            async def one(q: str, client_ms=client_ms, server_ms=server_ms, sem=sem) -> None:
                async with sem:
                    while True:
                        t = time.perf_counter()
                        r = await c.post("/v1/search", json={"query": q, "size": 20}, headers=h)
                        if r.status_code != 429:
                            break
                        await asyncio.sleep(float(r.headers.get("retry-after", "1")))
                    r.raise_for_status()
                    client_ms.append((time.perf_counter() - t) * 1000)
                    server_ms.append(r.json()["took_ms"])

            t = time.perf_counter()
            await asyncio.gather(*(one(q) for q in work))
            wall = time.perf_counter() - t
            results[conc] = (client_ms, server_ms, len(work) / wall)
        await c.delete(f"/v1/projects/{p['project_id']}", headers=admin)

    lines = [
        "# Search latency at 10k documents",
        "",
        f"- Date: {datetime.now(UTC).strftime('%Y-%m-%d %H:%M UTC')} · {platform.machine()} {platform.system()}",
        f"- {st['succeeded']} docs (demo catalog replicated), ingest took {ingest_s:.0f}s incl. embeddings",
        f"- {len(queries)} eval queries × {args.repeats}, `Cache-Control: no-cache` (search cache bypassed; "
        "query embeddings cached after warm-up)",
        "",
        "| concurrency | server p50 | server p95 | client p50 | client p95 | throughput |",
        "|---:|---:|---:|---:|---:|---:|",
    ]
    for conc, (cm, sm, qps) in results.items():
        lines.append(f"| {conc} | {pct(sm, .5):.1f} ms | {pct(sm, .95):.1f} ms | {pct(cm, .5):.1f} ms | "
                     f"{pct(cm, .95):.1f} ms | {qps:.0f} req/s |")
    lines.append("")
    (ROOT / "eval" / "latency_10k.md").write_text("\n".join(lines))
    print("\n".join(lines))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--base-url", default="http://localhost:8000")
    ap.add_argument("--docs", type=int, default=10_000)
    ap.add_argument("--repeats", type=int, default=5)
    ap.add_argument("--concurrency", type=int, nargs="+", default=[1, 4])
    asyncio.run(run(ap.parse_args()))


if __name__ == "__main__":
    main()
