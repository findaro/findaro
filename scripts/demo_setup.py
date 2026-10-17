"""Create a demo project, import the demo catalog, and write examples/plain-html/demo.html and ai-demo.html with its keys.

    docker compose up -d --build && uv run python scripts/demo_setup.py
    open http://localhost:8080/demo.html

Reuses the project in .demo-project.json if it still works. Also copies the built widget next to the page
(run `npm run build` first) and loads the local Ollama models so the first chat answer is fast.
"""

from __future__ import annotations

import json
import shutil
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
STATE = ROOT / ".demo-project.json"
EXAMPLE = ROOT / "examples" / "plain-html"
API = "http://localhost:8000"


def wait_for_api(timeout_s: int = 600) -> None:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        try:
            if httpx.get(f"{API}/healthz", timeout=5).status_code == 200:
                return
        except httpx.HTTPError:
            pass
        time.sleep(2)
    sys.exit(f"API at {API} isn't up; start it with `docker compose up -d --build`")


def create() -> dict:
    import os

    token = os.environ.get("FINDARO_BOOTSTRAP_TOKEN")
    headers = {"authorization": f"Bearer {token}"} if token else {}
    with httpx.Client(base_url=API, timeout=60) as c:
        p = c.post("/v1/projects", json={"name": "demo"}, headers=headers).raise_for_status().json()
        admin = {"authorization": f"Bearer {p['admin_key']}"}
        with open(ROOT / "data" / "demo_catalog.jsonl", "rb") as f:
            job = c.post(f"/v1/projects/{p['project_id']}/import", headers=admin,
                         files={"file": ("demo_catalog.jsonl", f, "application/x-ndjson")}).raise_for_status().json()
        deadline = time.time() + 900
        while (st := c.get(job["status_url"], headers=admin).json())["status"] in ("queued", "running"):
            if time.time() > deadline:
                sys.exit("demo catalog import didn't finish in 15 minutes; check `docker compose logs worker`")
            time.sleep(1)
        if st["status"] != "succeeded":
            sys.exit(f"import failed: {st}")
        print(f"imported {st['succeeded']} documents into {p['project_id']}")
    STATE.write_text(json.dumps(p, indent=1))
    return p


def warm_models() -> None:
    """Load the local chat and planner models now so the first demo question isn't slow."""
    import os

    url = os.environ.get("FINDARO_OLLAMA_URL", "http://localhost:11434")
    for model in ("llama3.1:8b", "llama3.2:3b"):
        try:
            r = httpx.post(f"{url}/api/generate", json={"model": model, "prompt": "", "keep_alive": "30m"},
                           timeout=120)
            if r.status_code == 200:
                print(f"warmed {model}")
            else:
                print(f"warning: Ollama can't load {model} ({r.status_code}); run `ollama pull {model}`. "
                      "Chat answers fall back to plain templates without it.", file=sys.stderr)
        except httpx.HTTPError as e:
            print(f"warning: Ollama isn't reachable at {url} ({e}); install it from https://ollama.com and run "
                  f"`ollama pull {model}`. Chat answers fall back to plain templates without it.", file=sys.stderr)


def main() -> None:
    wait_for_api()
    p = json.loads(STATE.read_text()) if STATE.exists() else None
    if p:
        r = httpx.post(f"{API}/v1/search", json={"query": "x"}, headers={"authorization": f"Bearer {p['search_key']}"})
        if r.status_code != 200:
            p = None
    p = p or create()
    for template, out in (("index.html", "demo.html"), ("ai.html", "ai-demo.html")):
        html = (EXAMPLE / template).read_text()
        html = html.replace("YOUR_PROJECT_ID", p["project_id"]).replace("YOUR_SEARCH_KEY", p["search_key"])
        (EXAMPLE / out).write_text(html)
    widget = ROOT / "packages" / "widget" / "dist" / "findaro-widget.js"
    if widget.exists():
        shutil.copy(widget, EXAMPLE / "findaro-widget.js")
    else:
        print("warning: run `npm install && npm run build` to build the widget", file=sys.stderr)
    warm_models()
    print(f"wrote {EXAMPLE / 'demo.html'} and ai-demo.html; open http://localhost:8080/demo.html or /ai-demo.html")


if __name__ == "__main__":
    main()
