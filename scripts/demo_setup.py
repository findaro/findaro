"""Create a demo project, import the demo catalog, and write examples/plain-html/demo.html with its keys.

    docker compose up -d --build && uv run python scripts/demo_setup.py
    open http://localhost:8080/demo.html

Reuses the project in .demo-project.json if it still works. Also copies the built widget next to the page
(run `npm run build` first).
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


def create() -> dict:
    with httpx.Client(base_url=API, timeout=60) as c:
        p = c.post("/v1/projects", json={"name": "demo"}).raise_for_status().json()
        admin = {"authorization": f"Bearer {p['admin_key']}"}
        with open(ROOT / "data" / "demo_catalog.jsonl", "rb") as f:
            job = c.post(f"/v1/projects/{p['project_id']}/import", headers=admin,
                         files={"file": ("demo_catalog.jsonl", f, "application/x-ndjson")}).raise_for_status().json()
        while (st := c.get(job["status_url"], headers=admin).json())["status"] in ("queued", "running"):
            time.sleep(1)
        if st["status"] != "succeeded":
            sys.exit(f"import failed: {st}")
        print(f"imported {st['succeeded']} documents into {p['project_id']}")
    STATE.write_text(json.dumps(p, indent=1))
    return p


def main() -> None:
    p = json.loads(STATE.read_text()) if STATE.exists() else None
    if p:
        r = httpx.post(f"{API}/v1/search", json={"query": "x"}, headers={"authorization": f"Bearer {p['search_key']}"})
        if r.status_code != 200:
            p = None
    p = p or create()
    html = (EXAMPLE / "index.html").read_text()
    html = html.replace("YOUR_PROJECT_ID", p["project_id"]).replace("YOUR_SEARCH_KEY", p["search_key"])
    (EXAMPLE / "demo.html").write_text(html)
    widget = ROOT / "packages" / "widget" / "dist" / "zerch-widget.js"
    if widget.exists():
        shutil.copy(widget, EXAMPLE / "zerch-widget.js")
    else:
        print("warning: run `npm install && npm run build` to build the widget", file=sys.stderr)
    print(f"wrote {EXAMPLE / 'demo.html'}; open http://localhost:8080/demo.html")


if __name__ == "__main__":
    main()
