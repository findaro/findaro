"""Create the demo project on the box (runs there with the system python3, stdlib only).

    python3 - <api_host> <demo_host> < demo_project.py

Reuses /srv/zerch/demo-project.json (chmod 600; holds the admin key) while its search key still works.
Reads the bootstrap token from /srv/zerch/.env. Prints nothing secret.
"""

import json
import os
import sys
import time
import urllib.error
import urllib.request

ZERCH = "/srv/zerch"
STATE = f"{ZERCH}/demo-project.json"
API, DEMO = f"https://{sys.argv[1]}", f"https://{sys.argv[2]}"


def call(method, path, key=None, body=None):
    req = urllib.request.Request(API + path, method=method, data=None if body is None else json.dumps(body).encode(),
                                 headers={"content-type": "application/json", "user-agent": "zerch-deploy",
                                          **({"authorization": f"Bearer {key}"} if key else {})})
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.loads(r.read() or b"null")


def wait_for_api():
    for _ in range(120):
        try:
            call("GET", "/healthz")
            return
        except (urllib.error.URLError, OSError):
            time.sleep(5)
    sys.exit(f"{API} isn't reachable")


def still_works(p):
    try:
        call("POST", "/v1/search", p["search_key"], {"query": "x"})
        return True
    except urllib.error.HTTPError:
        return False


def create():
    env = dict(line.split("=", 1) for line in open(f"{ZERCH}/.env").read().splitlines() if "=" in line
               and not line.startswith("#"))
    p = call("POST", "/v1/projects", env["ZERCH_BOOTSTRAP_TOKEN"], {"name": "demo"})
    old = os.umask(0o077)
    with open(STATE, "w") as f:
        json.dump(p, f)
    os.umask(old)
    docs = [json.loads(line) for line in open(f"{ZERCH}/app/data/demo_catalog.jsonl") if line.strip()]
    job = call("POST", f"/v1/projects/{p['project_id']}/documents", p["admin_key"], docs)
    deadline = time.time() + 1800
    while (st := call("GET", job["status_url"], p["admin_key"]))["status"] in ("queued", "running"):
        if time.time() > deadline:
            sys.exit("demo import didn't finish in 30 minutes; check `docker compose logs worker`")
        time.sleep(5)
    if st["status"] != "succeeded":
        sys.exit(f"demo import failed: {st.get('status')} {st.get('error')}")
    print(f"imported {st.get('succeeded')} documents into {p['project_id']}")
    return p


wait_for_api()
p = json.load(open(STATE)) if os.path.exists(STATE) else None
if not (p and still_works(p)):
    p = create()
call("PUT", f"/v1/projects/{p['project_id']}/settings", p["admin_key"], {"allowed_origins": [DEMO]})
print(f"demo project {p['project_id']}, allowed origin {DEMO}")
