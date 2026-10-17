"""Render the website into /srv/zerch/site (runs on the box with the system python3, stdlib only).

    python3 render_site.py <site_url> <api_url> <github_url> <company_name>

Copies app/site/{public,server}, fills the placeholders listed in site/README.md, adds the widget and a demo
store page (examples/plain-html) at /demo/. The search key it writes is the demo project's browser-safe key.
"""

import json
import shutil
import sys
from pathlib import Path

ZERCH = Path("/srv/zerch")
site_url, api_url, github_url, company = sys.argv[1:5]
demo = json.loads((ZERCH / "demo-project.json").read_text())
values = {
    "__SITE_URL__": site_url, "__API_URL__": api_url, "__GITHUB_URL__": github_url, "__COMPANY_NAME__": company,
    "__DEMO_PROJECT__": demo["project_id"], "__DEMO_SEARCH_KEY__": demo["search_key"],
}

new = ZERCH / "site.new"
shutil.rmtree(new, ignore_errors=True)
shutil.copytree(ZERCH / "app/site/public", new / "public")
shutil.copytree(ZERCH / "app/site/server", new / "server")
shutil.copy(ZERCH / "zerch-widget.js", new / "public/zerch-widget.js")
page = (ZERCH / "app/examples/plain-html/index.html").read_text()
page = (page.replace("YOUR_PROJECT_ID", "__DEMO_PROJECT__").replace("YOUR_SEARCH_KEY", "__DEMO_SEARCH_KEY__")
        .replace("http://localhost:8000", "__API_URL__").replace('src="./zerch-widget.js"', 'src="/zerch-widget.js"'))
(new / "public/demo").mkdir(exist_ok=True)
(new / "public/demo/index.html").write_text(page)

for f in (new / "public").rglob("*"):
    if f.suffix in (".html", ".xml", ".txt", ".js", ".css", ".json", ".webmanifest") and f.name != "zerch-widget.js":
        text = f.read_text()
        for k, v in values.items():
            text = text.replace(k, v)
        f.write_text(text)

old = ZERCH / "site.old"
shutil.rmtree(old, ignore_errors=True)
if (ZERCH / "site").exists():
    (ZERCH / "site").rename(old)
new.rename(ZERCH / "site")
shutil.rmtree(old, ignore_errors=True)
print(f"website rendered for {site_url}")
