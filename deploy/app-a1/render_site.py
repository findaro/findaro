"""Render the website into /srv/findaro/site (runs on the box with the system python3, stdlib only).

    python3 render_site.py <site_url> <api_url> <github_url> <company_name>

Copies app/site/{public,server}, fills the placeholders listed in site/README.md and adds the built widget. The live
demo is the site's own page, public/demo/index.html. The search key it writes is the demo project's browser-safe key.
Stylesheet, script and widget URLs get a content hash (?v=…) so a CDN in front never serves a stale copy.
"""

import hashlib
import json
import shutil
import sys
from pathlib import Path

FINDARO = Path("/srv/findaro")
site_url, api_url, github_url, company = sys.argv[1:5]
demo = json.loads((FINDARO / "demo-project.json").read_text())
values = {
    "__SITE_URL__": site_url, "__API_URL__": api_url, "__GITHUB_URL__": github_url, "__COMPANY_NAME__": company,
    "__DEMO_PROJECT__": demo["project_id"], "__DEMO_SEARCH_KEY__": demo["search_key"],
}

new = FINDARO / "site.new"
shutil.rmtree(new, ignore_errors=True)
shutil.copytree(FINDARO / "app/site/public", new / "public")
shutil.copytree(FINDARO / "app/site/server", new / "server")
shutil.copy(FINDARO / "findaro-widget.js", new / "public/findaro-widget.js")

for f in (new / "public").rglob("*"):
    if f.suffix in (".html", ".xml", ".txt", ".js", ".css", ".json", ".webmanifest") and f.name != "findaro-widget.js":
        text = f.read_text()
        for k, v in values.items():
            text = text.replace(k, v)
        f.write_text(text)

# cache-busting: /assets/site.css -> /assets/site.css?v=<hash of its content>
versioned = {}
for rel in ("assets/site.css", "assets/site.js", "findaro-widget.js"):
    f = new / "public" / rel
    if f.exists():
        versioned["/" + rel] = "/" + rel + "?v=" + hashlib.sha256(f.read_bytes()).hexdigest()[:10]
for f in (new / "public").rglob("*.html"):
    text = f.read_text()
    for url, with_v in versioned.items():
        text = text.replace(f'href="{url}"', f'href="{with_v}"').replace(f'src="{url}"', f'src="{with_v}"')
    f.write_text(text)

old = FINDARO / "site.old"
shutil.rmtree(old, ignore_errors=True)
if (FINDARO / "site").exists():
    (FINDARO / "site").rename(old)
new.rename(FINDARO / "site")
shutil.rmtree(old, ignore_errors=True)
print(f"website rendered for {site_url}")
