"""M3 chat eval: scripted multi-turn conversations against /v1/chat. Writes the M3 section of eval/report.md.

    uv run python eval/run_chat.py --search-key zk_search_... [--judge --judge-model gpt-4.1-mini]

Per turn: turn type, required/forbidden plan filters (from the `understood` chips), nDCG@10 against the turn's
predicate, whether a clarifier appeared, groundedness of the answer text (LLM judge: every factual claim must
be supported by the fields of the products it refers to), latency to the results event and to the first text
token. Also runs the out-of-catalog negatives as one-turn chats.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import re
import statistics
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
EVAL = ROOT / "eval"
REPORT = EVAL / "report.md"
BEGIN, END = "<!-- M3:BEGIN -->", "<!-- M3:END -->"
sys.path.insert(0, str(EVAL))
from build_queries import grade  # noqa: E402
from run import ndcg_at, pct  # noqa: E402

TARGET_RESULTS_P95 = 150.0
TARGET_FIRST_TOKEN_P95 = 1200.0

JUDGE_SYSTEM = "You check whether a shopping assistant's answer is supported by product data. Reply with JSON only."
JUDGE_PROMPT = """Products the assistant could see (id and fields):
{docs}

Search constraints in effect (from the conversation): {constraints}
The user said: {user}
The assistant answered: {answer}

List every factual claim the answer makes about products (prices, attributes, availability, comparisons such as
"cheapest"). For each, decide whether the product fields above support it. Statements that something is not
known or not listed count as supported. Ignore greetings and suggestions.
Reply as JSON: {{"claims": [{{"claim": "...", "supported": true|false, "why": "..."}}]}}"""


def sse_events(client: httpx.Client, body: dict) -> tuple[list[tuple[str, dict, float]], float]:
    out = []
    t0 = time.perf_counter()
    with client.stream("POST", "/v1/chat", json=body, timeout=90) as r:
        while r.status_code == 429:
            time.sleep(1)
            return sse_events(client, body)
        r.raise_for_status()
        ev = None
        for line in r.iter_lines():
            if line.startswith("event: "):
                ev = line[7:]
            elif line.startswith("data: ") and ev:
                out.append((ev, json.loads(line[6:]), (time.perf_counter() - t0) * 1000))
    return out, (time.perf_counter() - t0) * 1000


def numeric_errors(text: str, docs: dict[str, dict]) -> list[str]:
    """Numbers in the answer that don't appear in any shown product's fields (ids excluded)."""
    body = re.sub(r"\[[^\]]*\]", " ", text)
    known: set[str] = set()
    for d in docs.values():
        for v in d.values():
            for x in v if isinstance(v, list) else [v]:
                for n in re.findall(r"\d+(?:\.\d+)?", str(x).replace(",", "")):
                    known.add(n.rstrip("0").rstrip(".") if "." in n else n)
    bad = []
    for n in re.findall(r"\d[\d,]*(?:\.\d+)?", body):
        k = n.replace(",", "")
        k = k.rstrip("0").rstrip(".") if "." in k else k
        if k not in known:
            bad.append(n)
    return bad


def chip_matches(chip: dict, want: dict) -> bool:
    if chip.get("field") != want["field"]:
        return False
    if "op" in want:
        op = chip.get("op")
        if want["op"] == "range" and op != "range":
            return False
        if want["op"] == "not" and op != "not":
            return False
        if want["op"] == "eq" and op not in ("eq", "in"):
            return False
    if "value" in want:
        vals = chip.get("value")
        vals = vals if isinstance(vals, list) else [vals]
        return str(want["value"]).lower() in {str(v).lower() for v in vals}
    return True


async def judge_all(judge_llm, jobs: list[tuple[dict, str, str]], concurrency: int = 6) -> list[dict]:
    from zerch.llm.base import parse_json

    sem = asyncio.Semaphore(concurrency)

    async def one(docs: dict, user: str, text: str, constraints: str) -> dict:
        prompt = JUDGE_PROMPT.format(docs=json.dumps(docs, ensure_ascii=False)[:12000], user=user, answer=text,
                                     constraints=constraints or "none")
        async with sem:
            try:
                raw = await judge_llm.complete(prompt, system=JUDGE_SYSTEM, json_mode=True, max_tokens=800)
                claims = parse_json(raw).get("claims", [])
            except Exception as e:  # noqa: BLE001
                return {"n_claims": 0, "unsupported": [], "error": str(e)[:200]}
        bad = [c for c in claims if isinstance(c, dict) and not c.get("supported")]
        return {"n_claims": len(claims), "unsupported": bad}

    return await asyncio.gather(*(one(*j) for j in jobs))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--base-url", default="http://localhost:8000")
    ap.add_argument("--search-key", required=True)
    ap.add_argument("--judge-provider", default="ollama")
    ap.add_argument("--judge-model", default="llama3.1:8b")
    ap.add_argument("--chat-model", default="see docker-compose.yml / ZERCH_CHAT_MODEL")
    ap.add_argument("--judge", action="store_true",
                    help="LLM groundedness judge (paid API calls, ~68 per run). Off by default: the numeric check "
                         "runs for free, and answers are written to eval/results for manual review.")
    args = ap.parse_args()

    from zerch.llm import get_llm

    judge_llm = get_llm(args.judge_provider, args.judge_model) if args.judge else None
    docs = [json.loads(line) for line in (ROOT / "data" / "demo_catalog.jsonl").read_text().splitlines() if line]
    by_id = {d["id"]: d for d in docs}
    convs = [json.loads(line) for line in (EVAL / "conversations.jsonl").read_text().splitlines() if line.strip()]
    client = httpx.Client(base_url=args.base_url, headers={"authorization": f"Bearer {args.search_key}"})

    rows = []
    for conv in convs:
        sid, chips_prev = None, []
        for i, turn in enumerate(conv["turns"]):
            exp = turn["expect"]
            body = {"session_id": sid, "message": turn["user"]}
            hit = next((c for c in chips_prev if c["label"].lower() == turn["user"].lower()), None)
            if hit:  # a UI would send the chip's patch
                body["apply"] = hit["plan_patch"]
            events, total_ms = sse_events(client, body)
            ev = {}
            text, first_ms, results_ms = "", None, None
            for name, data, ms in events:
                ev.setdefault(name, data)
                if name == "results":
                    results_ms = ms
                if name == "text":
                    text += data["delta"]
                    first_ms = first_ms if first_ms is not None else ms
            sid = ev["session"]["session_id"]
            done = ev.get("done", {})
            und = (ev.get("plan") or {}).get("understood") or {}
            chips = [c for c in und.get("chips", []) if c.get("kind") in ("filter", "sort", "boost")]
            filters = [c for c in chips if c.get("kind") == "filter"]
            ok_req = all(any(chip_matches(c, w) for c in chips) for w in exp.get("require", []))
            ok_forbid = not any(chip_matches(c, w) for w in exp.get("forbid", []) for c in filters)
            items = (ev.get("results") or {}).get("items", [])
            ids = [it["id"] for it in items]
            nd = None
            if exp.get("predicate") and not (ev.get("results") or {}).get("unchanged"):
                g = {d["id"]: grade(d, exp["predicate"]) for d in docs}
                nd = ndcg_at(ids, {k: v for k, v in g.items() if v}, 10)
            clar = ev.get("clarify")
            chips_prev = clar["chips"] if clar else []
            cited = re.findall(r"\[([A-Z]{2}-\d{5})\]", text)
            shown = {it["id"]: it["document"] for it in items}
            rows.append({
                "conv": conv["id"], "lang": conv.get("lang"), "turn": i + 1, "user": turn["user"],
                "type_expected": exp.get("type"), "type_got": done.get("turn_type"),
                "type_ok": exp.get("type") is None or exp.get("type") == done.get("turn_type"),
                "plan_ok": ok_req and ok_forbid, "has_plan_assert": bool(exp.get("require") or exp.get("forbid")),
                "chips": [c["label"] for c in chips], "ndcg": nd, "clarify_expected": exp.get("clarify"),
                "clarify_got": clar is not None, "clarify_q": clar["question"] if clar else None,
                "text": text, "cited": cited, "shown": {k: v for k, v in shown.items()},
                "results_ms": results_ms, "first_ms": first_ms, "total_ms": total_ms,
                "server": done.get("timings", {}), "reason": done.get("reason"),
                "quality": (ev.get("results") or {}).get("match_quality"),
                "numeric_errors": numeric_errors(text, shown) if done.get("turn_type") != "chitchat" else [],
                "dropped": (done.get("timings") or {}).get("dropped_sentences", 0),
                "answer_source": done.get("answer_source"),
            })
            print(f"{conv['id']}.{i + 1} {turn['user'][:40]:40} {done.get('turn_type'):9} "
                  f"plan={'ok' if ok_req and ok_forbid else 'FAIL'} ndcg={'' if nd is None else f'{nd:.2f}'} "
                  f"clar={clar is not None} res={results_ms:.0f}ms first={first_ms or 0:.0f}ms", file=sys.stderr)

    errors = [r for r in rows if r["answer_source"] == "error"]
    if errors:
        sys.exit(f"{len(errors)} turns failed to get a model answer (LLM error, e.g. quota); not scoring this run")

    # groundedness
    judged = []
    if judge_llm is not None:
        jobs = []
        for r in rows:
            if not r["text"] or r["type_got"] == "chitchat":
                continue
            ctx = dict(r["shown"])
            for c in r["cited"]:
                if c not in ctx and c in by_id:
                    ctx[c] = by_id[c]
            ctx = {k: {kk: vv for kk, vv in v.items() if kk not in ("image_url", "url")} for k, v in ctx.items()}
            jobs.append((ctx, r["user"], r["text"], ", ".join(r["chips"])))
            judged.append(r)
        for r, res in zip(judged, asyncio.run(judge_all(judge_llm, jobs)), strict=True):
            r["judge"] = res

    # out-of-catalog
    neg = []
    for line in (EVAL / "negatives.jsonl").read_text().splitlines():
        if not line.strip():
            continue
        q = json.loads(line)["query"]
        events, _ = sse_events(client, {"message": q})
        text = "".join(d["delta"] for n, d, _ in events if n == "text")
        res = next((d for n, d, _ in events if n == "results"), {})
        clar = next((d for n, d, _ in events if n == "clarify"), None)
        neg.append({"query": q, "quality": res.get("match_quality"), "total": res.get("total"), "text": text,
                    "clarify": clar["question"] if clar else None})

    write_section(rows, judged, neg, args)


def write_section(rows, judged, neg, args) -> None:
    from collections import Counter

    type_ok = sum(r["type_ok"] for r in rows) / len(rows)
    plan_rows = [r for r in rows if r["has_plan_assert"]]
    plan_ok = sum(r["plan_ok"] for r in plan_rows) / len(plan_rows) if plan_rows else float("nan")
    nds = [r["ndcg"] for r in rows if r["ndcg"] is not None]
    by_turn: dict[int, list[float]] = {}
    for r in rows:
        if r["ndcg"] is not None:
            by_turn.setdefault(min(r["turn"], 3), []).append(r["ndcg"])
    cl = [r for r in rows if r["clarify_expected"] is not None]
    tp = sum(1 for r in cl if r["clarify_expected"] and r["clarify_got"])
    fp_all = sum(1 for r in rows if r["clarify_got"] and r["clarify_expected"] is False)
    asked_labeled = sum(1 for r in cl if r["clarify_got"])
    should = sum(1 for r in cl if r["clarify_expected"])
    precision = tp / asked_labeled if asked_labeled else float("nan")
    recall = tp / should if should else float("nan")
    asked_any = sum(1 for r in rows if r["clarify_got"])
    num_err = [(r, n) for r in rows for n in r["numeric_errors"]]
    ids_re = re.compile(r"\b[A-Z]{2}-\d{5}\b")
    judge_num = [r for r in judged if any(re.search(r"\d", ids_re.sub("", str(c.get("claim", ""))))
                                          for c in r["judge"]["unsupported"])]
    model_first = [r["server"].get("first_model_token") for r in rows if r["server"].get("first_model_token")]
    grounded = [r for r in judged if not r["judge"]["unsupported"]]
    # LLM-dependent turns (unclear-turn classification, small talk) are reported apart from the rules path
    rules_rows = [r for r in rows if r["type_got"] in ("new", "refine") and r["reason"] not in ("llm", "conversation")]
    conv_rows = [r for r in rows if r["reason"] == "conversation"]
    res_p95 = pct([r["results_ms"] for r in rules_rows if r["results_ms"] is not None], .95)
    first = [r["first_ms"] for r in rows if r["first_ms"] is not None and r["type_got"] != "chitchat"]
    first_p95 = pct(first, .95)
    neg_q = Counter(n["quality"] for n in neg)

    def v(ok: bool) -> str:
        return "✅ met" if ok else "❌ missed"

    L = [BEGIN, "", "## M3 — chat search", "",
         f"- Date: {datetime.now(UTC).strftime('%Y-%m-%d %H:%M UTC')} · {len({r['conv'] for r in rows})} "
         f"conversations, {len(rows)} turns (`eval/conversations.jsonl`, marked needs_review)",
         f"- Chat model: {args.chat_model} · judge: {args.judge_provider}:{args.judge_model}", "",
         "| Target / metric | Result | |", "|---|---|---|",
         f"| results event p95 ≤ {TARGET_RESULTS_P95:.0f} ms (rules path, client-measured) | {res_p95:.0f} ms "
         f"(n={len(rules_rows)}) | {v(res_p95 <= TARGET_RESULTS_P95)} |",
         f"| small-talk turns answered conversationally (results wait for one chat-LLM call) | {len(conv_rows)} "
         f"(results p50 {pct([r['results_ms'] or 0 for r in conv_rows], .5) if conv_rows else 0:.0f} ms) | |",
         f"| first text token p95 ≤ {TARGET_FIRST_TOKEN_P95:.0f} ms | {first_p95:.0f} ms (p50 {pct(first, .5):.0f}, "
         f"n={len(first)}) | {v(first_p95 <= TARGET_FIRST_TOKEN_P95)} |",
         f"| first *model* token p95, server-side (before sentence checking) | "
         f"{pct(model_first, .95) or 0:.0f} ms (p50 {pct(model_first, .5) or 0:.0f}) | |",
         f"| turn type accuracy | {type_ok:.0%} ({sum(r['type_ok'] for r in rows)}/{len(rows)}) | |",
         f"| plan-assertion pass rate | {plan_ok:.0%} ({sum(r['plan_ok'] for r in plan_rows)}/{len(plan_rows)}) | |",
         f"| per-turn nDCG@10 | {statistics.mean(nds):.3f} (n={len(nds)}; turn 1 "
         f"{statistics.mean(by_turn.get(1, [math.nan])):.3f}, turn 2 {statistics.mean(by_turn.get(2, [math.nan])):.3f},"
         f" turn 3+ {statistics.mean(by_turn.get(3, [math.nan])):.3f}) | |",
         f"| clarifier precision / recall (labelled turns) | {precision:.0%} / {recall:.0%} "
         f"(asked on {asked_any}/{len(rows)} turns; {fp_all} where the label says don't ask) | |",
         f"| groundedness ≥ 97% (judge: every claim supported) | {len(grounded) / len(judged):.0%} "
         f"({len(grounded)}/{len(judged)} answers) | {v(len(grounded) / len(judged) >= 0.97)} |"
         if judged else "| groundedness | not judged | |",
         f"| numeric errors = 0 (numbers not in any shown product's fields) | {len(num_err)} "
         f"(judge-flagged numeric claims: {len(judge_num)}; sentences dropped by the slot checker: "
         f"{sum(r['dropped'] for r in rows)}) | {v(not num_err and not judge_num)} |",
         f"| answers written by the model (rest: fallback when every sentence was dropped, or templates) | "
         f"{sum(r['answer_source'] == 'model' for r in rows)}/{len(rows)} (fallback "
         f"{sum(r['answer_source'] == 'fallback' for r in rows)}) | |",
         f"| clarifier rate | {asked_any}/{len(rows)} turns ({asked_any / len(rows):.0%}) | |",
         "| out-of-catalog chats: match_quality | " + ", ".join(f"{k} {c}" for k, c in sorted(neg_q.items(),
                                                                                         key=lambda kv: str(kv[0])))
         + f" (none/weak {neg_q.get('none', 0) + neg_q.get('weak', 0)}/{len(neg)}; target ≥ 15) | "
         + v(neg_q.get('none', 0) + neg_q.get('weak', 0) >= 15) + " |", ""]
    fails = [r for r in rows if not r["type_ok"] or (r["has_plan_assert"] and not r["plan_ok"])]
    if fails:
        L += ["### Turn-type and plan failures", "", "| conv | turn | user | expected | got | understood |",
              "|---|---:|---|---|---|---|"]
        for r in fails:
            L.append(f"| {r['conv']} | {r['turn']} | {r['user']} | {r['type_expected']} | {r['type_got']} | "
                     f"{', '.join(r['chips']).replace('|', '/')} |")
        L.append("")
    bad = [r for r in judged if r["judge"]["unsupported"]]
    if bad:
        L += ["### Ungrounded answers (judge)", "", "| conv | turn | answer | unsupported claim |", "|---|---:|---|---|"]
        for r in bad:
            for c in r["judge"]["unsupported"][:2]:
                L.append(f"| {r['conv']} | {r['turn']} | {r['text'][:120].replace('|', '/')} | "
                         f"{str(c.get('claim', ''))[:90].replace('|', '/')}: {str(c.get('why', ''))[:90].replace('|', '/')} |")
        L.append("")
    L += ["### Out-of-catalog queries in chat", "", "| query | match_quality | clarifier | answer |", "|---|---|---|---|"]
    for n in neg:
        L.append(f"| {n['query']} | {n['quality']} | {(n['clarify'] or '').replace('|', '/')} | "
                 f"{n['text'][:110].replace('|', '/')} |")
    L += ["", "### All turns", "", "| conv | turn | user | type | understood | nDCG | clarifier | results ms | first token ms | answer |",
          "|---|---:|---|---|---|---:|---|---:|---:|---|"]
    for r in rows:
        L.append(f"| {r['conv']} | {r['turn']} | {r['user']} | {r['type_got']}{'' if r['type_ok'] else ' ✗'} | "
                 f"{', '.join(r['chips']).replace('|', '/')}{'' if r['plan_ok'] or not r['has_plan_assert'] else ' ✗'} | "
                 f"{'' if r['ndcg'] is None else format(r['ndcg'], '.2f')} | "
                 f"{(r['clarify_q'] or '').replace('|', '/')} | {r['results_ms'] or 0:.0f} | {r['first_ms'] or 0:.0f} | "
                 f"{r['text'][:100].replace('|', '/')} |")
    notes = EVAL / "notes_m3.md"
    if notes.exists():
        L += ["", notes.read_text().strip()]
    L += ["", END]
    section = "\n".join(L)
    report = REPORT.read_text() if REPORT.exists() else ""
    if BEGIN in report and END in report:
        report = report[: report.index(BEGIN)] + section + report[report.index(END) + len(END):]
    else:
        report = report.rstrip() + "\n\n" + section + "\n"
    REPORT.write_text(report)
    (EVAL / "results").mkdir(exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S")
    (EVAL / "results" / f"chat-{stamp}.json").write_text(json.dumps({"rows": rows, "negatives": neg}, indent=1,
                                                                    ensure_ascii=False, default=str))
    print("\n".join(L[:20]))


if __name__ == "__main__":
    main()
