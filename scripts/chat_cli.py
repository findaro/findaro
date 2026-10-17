"""Terminal client for /v1/chat (manual testing).

    uv run python scripts/chat_cli.py --key fdr_search_...        # interactive
    uv run python scripts/chat_cli.py --key ... "black shoes" "sasta wala" "is the second one leather?"

Type a message; a clarifier's chips are numbered, type the number to pick one. Ctrl-D quits.
"""

from __future__ import annotations

import argparse
import json
import sys
import time

import httpx


def stream(client: httpx.Client, body: dict) -> tuple[dict, list[dict]]:
    events: dict = {}
    chips: list[dict] = []
    t0 = time.perf_counter()
    with client.stream("POST", "/v1/chat", json=body, timeout=60) as r:
        if r.status_code != 200:
            print(f"error {r.status_code}: {r.read().decode()}")
            return {}, []
        event = None
        for line in r.iter_lines():
            if line.startswith("event: "):
                event = line[7:]
            elif line.startswith("data: ") and event:
                data = json.loads(line[6:])
                ms = (time.perf_counter() - t0) * 1000
                if event == "session":
                    events["session"] = data
                elif event == "plan":
                    und = data.get("understood") or {}
                    chips_ = ", ".join(c["label"] for c in und.get("chips", []))
                    dl = data.get("delta", {})
                    print(f"  [{dl.get('turn_type')}] understood: {und.get('semantic_text', '')!r} {chips_}"
                          f"  (+{dl.get('added')} -{dl.get('removed')})")
                elif event == "results":
                    print(f"  results in {ms:.0f} ms: {data['total']} ({data.get('match_quality')})")
                    for i, it in enumerate(data["items"][:5], 1):
                        doc = it["document"]
                        mark = " ~" if it["id"] in data.get("close_matches", []) else ""
                        print(f"    {i}. [{it['id']}] {str(doc.get('title', ''))[:70]} {doc.get('price', '')}{mark}")
                elif event == "clarify":
                    chips = data["chips"]
                    print(f"  ? {data['question']}  " + "  ".join(
                        f"({i}) {c['label']}{' ' + str(c['count']) if c.get('count') else ''}"
                        for i, c in enumerate(chips, 1)))
                elif event == "text":
                    if "first_text" not in events:
                        events["first_text"] = ms
                        print("  > ", end="")
                    print(data["delta"], end="", flush=True)
                elif event == "done":
                    print(f"\n  done {data.get('timings')}")
    return events, chips


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", default="http://localhost:8000")
    ap.add_argument("--key", required=True)
    ap.add_argument("messages", nargs="*")
    args = ap.parse_args()
    client = httpx.Client(base_url=args.base_url, headers={"authorization": f"Bearer {args.key}"})
    sid, chips = None, []
    msgs = iter(args.messages) if args.messages else None
    while True:
        try:
            msg = next(msgs) if msgs else input("you> ")
        except (StopIteration, EOFError):
            break
        if msgs:
            print(f"you> {msg}")
        body: dict = {"session_id": sid, "message": msg}
        if msg.strip().isdigit() and chips and 0 < int(msg) <= len(chips):
            c = chips[int(msg) - 1]
            body = {"session_id": sid, "message": c["label"], "apply": c["plan_patch"]}
        events, chips = stream(client, body)
        sid = (events.get("session") or {}).get("session_id", sid)
    sys.exit(0)


if __name__ == "__main__":
    main()
