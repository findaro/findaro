"""Read the query log (logs/queries.jsonl): what was searched or asked, how it was understood, what came back.

    uv run python scripts/queries.py            # last 20 entries
    uv run python scripts/queries.py -n 50 --chat
    uv run python scripts/queries.py --follow   # keep printing new entries
    uv run python scripts/queries.py --json     # raw lines (pipe to jq)
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

LOG = Path(__file__).resolve().parent.parent / "logs" / "queries.jsonl"


def show(e: dict) -> str:
    t = e.get("ts", "")[11:19]
    hits = ", ".join(f"{h['id']} {h.get('title', '')[:40]}" for h in (e.get("top") or [])[:3])
    if e.get("kind") == "search":
        head = f"{t} SEARCH  {e.get('query')!r}"
        if e.get("patch"):
            head += f" patch={e['patch']}"
        return (f"{head}\n         understood: {e.get('chips')} · {e.get('match_quality')} · {e.get('total')} results"
                f" · {e.get('took_ms')} ms\n         top: {hits}")
    lines = [f"{t} CHAT    {e.get('message')!r}  [{e.get('turn_type')}: {e.get('reason')}] "
             f"session {str(e.get('session'))[-6:]} turn {e.get('turn')}"]
    if e.get("product_ids"):
        lines.append(f"         about: {e['product_ids']}")
    if e.get("results_changed"):
        lines.append(f"         understood: {e.get('chips')} · {e.get('match_quality')} · {e.get('total')} results")
        lines.append(f"         top: {hits}")
    if e.get("clarify"):
        lines.append(f"         clarify: {e['clarify']['question']} {e['clarify']['chips']}")
    lines.append(f"         answer ({e.get('answer_source')}): {e.get('answer')}")
    if e.get("general"):
        lines.append(f"         general: {e['general']}")
    for d in e.get("dropped") or []:
        lines.append(f"         dropped: {d['sentence'][:100]!r} ({d['why']})")
    tm = e.get("timings") or {}
    lines.append(f"         first token {tm.get('first_token')} ms · total {tm.get('total')} ms")
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("-n", type=int, default=20)
    ap.add_argument("--chat", action="store_true", help="chat turns only")
    ap.add_argument("--search", action="store_true", help="searches only")
    ap.add_argument("--follow", "-f", action="store_true")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--file", type=Path, default=LOG)
    args = ap.parse_args()
    if not args.file.exists():
        raise SystemExit(f"no log at {args.file} (is ZERCH_QUERY_LOG set? `docker compose up -d api` sets it)")

    def keep(e: dict) -> bool:
        return not (args.chat and e.get("kind") != "chat") and not (args.search and e.get("kind") != "search")

    def emit(line: str) -> None:
        try:
            e = json.loads(line)
        except ValueError:
            return
        if keep(e):
            print(line.rstrip() if args.json else show(e) + "\n", flush=True)

    with args.file.open(encoding="utf-8") as f:
        for line in [ln for ln in f if keep(json.loads(ln) if ln.strip() else {})][-args.n:]:
            emit(line)
        while args.follow:
            line = f.readline()
            if line:
                emit(line)
            else:
                time.sleep(0.5)


if __name__ == "__main__":
    main()
