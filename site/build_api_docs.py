#!/usr/bin/env python3
"""Render packages/sdk/openapi.json into site/public/docs/api.html.

Standard library only. The page chrome (head, header, docs sidebar, footer) is copied from
site/public/docs/index.html, between its <!-- content:start --> / <!-- content:end --> markers, so the
generated page always matches the hand-written docs pages.

    python3 site/build_api_docs.py            # writes site/public/docs/api.html
    python3 site/build_api_docs.py --check    # exits 1 if the committed file is out of date

Regenerate after the API changes (scripts/export_openapi.py refreshes the spec).
"""
from __future__ import annotations

import html
import json
import re
import sys
from pathlib import Path

SITE = Path(__file__).resolve().parent
SPEC = SITE.parent / "packages" / "sdk" / "openapi.json"
TEMPLATE = SITE / "public" / "docs" / "index.html"
OUT = SITE / "public" / "docs" / "api.html"

TITLE = "API reference · Findaro docs"
DESC = "Findaro HTTP API reference: projects, documents, import jobs, schema, search and chat (Server-Sent Events)."

# Endpoint groups, in page order: (anchor, title, path predicate)
GROUPS = [
    ("projects", "Projects",
     lambda p: p == "/v1/projects" or re.fullmatch(r"/v1/projects/\{project_id\}(/settings)?", p)),
    ("documents", "Documents and import", lambda p: "/documents" in p or p.endswith("/import")),
    ("jobs", "Jobs", lambda p: "/jobs" in p),
    ("schema-ep", "Schema", lambda p: p.endswith("/schema")),
    ("search", "Search", lambda p: p == "/v1/search"),
    ("chat", "Chat", lambda p: p == "/v1/chat"),
]

# What the spec can't say on its own: which key each endpoint takes, and bodies/responses FastAPI leaves untyped.
NOTES: dict[tuple[str, str], dict[str, str]] = {
    ("post", "/v1/projects"): {
        "auth": "Bootstrap token, if the server sets <code>FINDARO_BOOTSTRAP_TOKEN</code> (self-hosted). On the hosted "
                "beta we create projects for you.",
        "returns": '<code>{"project_id", "admin_key", "search_key", "name"}</code>. The keys are shown only once.',
    },
    ("get", "/v1/projects/{project_id}"): {
        "returns": "<code>project_id</code>, <code>name</code>, <code>created_at</code>, <code>document_count</code>, "
                   "<code>has_schema</code>, <code>schema_version</code>, <code>reindex_pending</code>, "
                   "<code>allowed_origins</code>.",
    },
    ("delete", "/v1/projects/{project_id}"): {"returns": "204 No Content. Deletes the project, its index and keys."},
    ("put", "/v1/projects/{project_id}/settings"): {
        "returns": '<code>{"allowed_origins": [...]}</code>. Origins look like <code>https://shop.example.com</code> '
                   "or <code>https://*.example.com</code>.",
    },
    ("post", "/v1/projects/{project_id}/documents"): {
        "body": 'A JSON array of documents, or <code>{"documents": [...]}</code>. Up to 10,000 per request. '
                "Documents are upserted by their id field.",
        "returns": '202 with <code>{"job_id", "status": "queued", "status_url"}</code>.',
    },
    ("post", "/v1/projects/{project_id}/import"): {
        "body": "Multipart form with <code>file</code>: <code>.csv</code>, <code>.jsonl</code> or <code>.json</code>, "
                "up to 50 MB. <code>format</code> overrides detection from the file name.",
        "returns": '202 with <code>{"job_id", "status": "queued", "status_url"}</code>.',
    },
    ("delete", "/v1/projects/{project_id}/documents/{doc_id}"): {"returns": "202 with a job (see Jobs)."},
    ("post", "/v1/projects/{project_id}/documents/delete"): {"returns": "202 with a job (see Jobs)."},
    ("get", "/v1/projects/{project_id}/documents/{doc_id}"): {"returns": "The stored document."},
    ("get", "/v1/projects/{project_id}/jobs/{job_id}"): {
        "returns": "Job status: <code>queued</code>, <code>running</code>, <code>succeeded</code>, "
                   "<code>completed_with_errors</code> or <code>failed</code>, with counts and row errors.",
    },
    ("get", "/v1/projects/{project_id}/jobs"): {"returns": "Recent jobs, newest first."},
    ("get", "/v1/projects/{project_id}/schema"): {
        "returns": "<code>{\"schema\": {\"fields\": [{\"name\", \"role\", ...}]}, ...}</code>: the inferred or "
                   "overridden field roles.",
    },
    ("put", "/v1/projects/{project_id}/schema"): {
        "body": "The same <code>fields</code> list GET returns. Each entry can set <code>role</code>, "
                "<code>weight</code>, <code>searchable</code>, <code>filterable</code>, <code>facet</code> and "
                "<code>sortable</code>.",
        "returns": "Starts a background reindex into a new index followed by an atomic alias swap. Search keeps "
                   "working throughout.",
    },
    ("post", "/v1/search"): {"auth": "Search key or admin key."},
    ("post", "/v1/chat"): {"auth": "Search key or admin key."},
}
ROLES = ("id, title, description, text, facet, keyword, numeric, price, currency, category, boolean, "
         "image_url, url, ignore")


def esc(s: object) -> str:
    return html.escape(str(s), quote=True)


def md(s: str) -> str:
    """Escape, then render `code` spans. Descriptions are short; nothing else is needed."""
    return re.sub(r"`([^`]+)`", r"<code>\1</code>", esc(s))


def op_id(method: str, path: str) -> str:
    return "op-" + method + "-" + re.sub(r"[^a-z0-9_]+", "-", path.lower()).strip("-")


def ref_name(ref: str) -> str:
    return ref.rsplit("/", 1)[-1]


def schema_link(name: str) -> str:
    return f'<a href="#schema-{esc(name)}"><code>{esc(name)}</code></a>'


def type_of(s: dict) -> str:
    """A short, linked description of a JSON schema's type."""
    if "$ref" in s:
        return schema_link(ref_name(s["$ref"]))
    if "anyOf" in s:
        parts = [p for p in s["anyOf"] if p.get("type") != "null"]
        out = " | ".join(type_of(p) for p in parts) or "null"
        if len(parts) < len(s["anyOf"]):
            out += " | null"
        return out
    if "enum" in s:
        return " | ".join(f"<code>{esc(json.dumps(v))}</code>" for v in s["enum"])
    t = s.get("type")
    if t == "array":
        return "array of " + type_of(s.get("items", {}))
    if t == "object":
        ap = s.get("additionalProperties")
        if isinstance(ap, dict) and ap:
            return "object of " + type_of(ap)
        return "object"
    if t:
        return esc(t)
    return "any"


def constraints(s: dict) -> str:
    bits = []
    for key, label in (("minimum", "min"), ("maximum", "max"), ("minLength", "min length"),
                       ("maxLength", "max length"), ("minItems", "min items"), ("maxItems", "max items"),
                       ("maxProperties", "max keys")):
        if key in s:
            v = s[key]
            if isinstance(v, float) and v.is_integer():
                v = int(v)
            bits.append(f"{label} {v}")
    return ", ".join(bits)


def props_table(schema: dict) -> str:
    props = schema.get("properties") or {}
    if not props:
        return ""
    req = set(schema.get("required") or [])
    rows = []
    for name, p in props.items():
        notes = []
        if p.get("description"):
            notes.append(md(p["description"]))
        if "default" in p and p["default"] is not None:
            notes.append(f"Default <code>{esc(json.dumps(p['default'], ensure_ascii=False))}</code>.")
        c = constraints(p)
        if c:
            notes.append(esc(c[0].upper() + c[1:]) + ".")
        rows.append(
            f"<tr><td><code>{esc(name)}</code>{' <small>required</small>' if name in req else ''}</td>"
            f'<td class="type">{type_of(p)}</td><td>{" ".join(notes)}</td></tr>')
    return ('<table class="schema-table"><thead><tr><th>Field</th><th>Type</th><th>Notes</th></tr></thead><tbody>'
            + "".join(rows) + "</tbody></table>")


def render_op(method: str, path: str, op: dict) -> str:
    note = NOTES.get((method, path), {})
    out = [f'<div class="endpoint" id="{op_id(method, path)}">',
           f'<h3><span class="method {method}">{method.upper()}</span> {esc(path)}</h3>',
           f'<div class="meta">{esc(op.get("summary", ""))}</div>']
    if op.get("description"):
        out.append(f'<p class="desc-pre">{md(op["description"])}</p>')
    auth = note.get("auth", "Admin key (server-side only; refused from browsers).")
    out.append(f"<p><strong>Auth:</strong> {auth}</p>")

    params = op.get("parameters") or []
    if params:
        rows = "".join(
            f"<tr><td><code>{esc(p['name'])}</code></td><td>{esc(p['in'])}</td>"
            f'<td class="type">{type_of(p.get("schema", {}))}</td>'
            f"<td>{'required' if p.get('required') else 'optional'}</td></tr>" for p in params)
        out.append("<h4>Parameters</h4><table class=\"schema-table\"><thead><tr><th>Name</th><th>In</th><th>Type</th>"
                   f"<th></th></tr></thead><tbody>{rows}</tbody></table>")

    body = op.get("requestBody")
    if body or note.get("body"):
        out.append("<h4>Request body</h4>")
        if note.get("body"):
            out.append(f"<p>{note['body']}</p>")
        elif body:
            for ctype, c in body.get("content", {}).items():
                out.append(f"<p><code>{esc(ctype)}</code>: {type_of(c.get('schema', {}))}</p>")

    out.append("<h4>Responses</h4><ul>")
    for status, r in op.get("responses", {}).items():
        if status == "422":
            continue
        line = f"<li><code>{esc(status)}</code> "
        schema = next(iter(r.get("content", {}).values()), {}).get("schema", {})
        if note.get("returns"):
            line += note["returns"]
        elif "$ref" in schema:
            line += type_of(schema)
        else:
            line += md(r.get("description", ""))
        out.append(line + "</li>")
    out.append('<li><code>422</code> Invalid request (error code <code>invalid_request</code>, with '
               "<code>details</code>).</li></ul>")

    events = op.get("x-sse-events")
    if events:
        rows = "".join(f"<tr><td><code>{esc(k)}</code></td><td>{type_of(v)}</td></tr>" for k, v in events.items())
        out.append("<h4>Server-Sent Events</h4><p>Each event's <code>data:</code> line is JSON matching its schema. "
                   "Order: session, plan, results, clarify (optional), text (repeated), done.</p>"
                   f'<table class="schema-table"><thead><tr><th>Event</th><th>Data</th></tr></thead><tbody>{rows}'
                   "</tbody></table>")
    out.append("</div>")
    return "\n".join(out)


def render(spec: dict) -> str:
    ops = [(m, p, o) for p, item in spec["paths"].items() for m, o in item.items()]
    parts = ["<h1>API reference</h1>",
             f'<p class="lede">{md(spec["info"].get("description", ""))} Version '
             f'{esc(spec["info"].get("version", ""))}. Generated from the OpenAPI spec '
             '(<code>packages/sdk/openapi.json</code>).</p>',
             '<h2 id="basics">Basics</h2><ul>',
             "<li><strong>Base URL:</strong> <code>__API_URL__</code> (hosted beta), or your own server.</li>",
             "<li><strong>Auth:</strong> <code>Authorization: Bearer &lt;key&gt;</code> or "
             "<code>X-Findaro-Key: &lt;key&gt;</code>.</li>",
             "<li><strong>Keys:</strong> the <em>admin key</em> manages data and is refused from browsers; the "
             "<em>search key</em> can only call search and chat, and browser requests are accepted only from the "
             "project's <code>allowed_origins</code>.</li>",
             '<li><strong>Errors:</strong> <code>{"error": {"code": "...", "message": "...", "details": ...}}</code>. '
             "Invalid requests are 422 with code <code>invalid_request</code>; 401 means a missing or wrong key; "
             "429 means the per-key rate limit was hit.</li>",
             "<li><strong>Caching:</strong> search results are cached for 60 s per data version; send "
             "<code>Cache-Control: no-cache</code> to bypass.</li>",
             f"<li><strong>Schema roles:</strong> {esc(ROLES)}.</li>",
             "</ul>",
             '<nav aria-label="On this page"><p><strong>Endpoints:</strong> ']
    links = []
    for anchor, title, _ in GROUPS:
        links.append(f'<a href="#{anchor}">{esc(title)}</a>')
    links.append('<a href="#schemas">Schemas</a>')
    parts.append(" · ".join(links) + "</p></nav>")

    seen = set()
    for anchor, title, pred in GROUPS:
        group = [(m, p, o) for m, p, o in ops if pred(p) and (m, p) not in seen]
        if not group:
            continue
        parts.append(f'<h2 id="{anchor}">{esc(title)}</h2>')
        for m, p, o in group:
            seen.add((m, p))
            parts.append(render_op(m, p, o))
    rest = [(m, p, o) for m, p, o in ops if (m, p) not in seen]
    if rest:
        parts.append('<h2 id="other">Other</h2>')
        parts.extend(render_op(m, p, o) for m, p, o in rest)

    parts.append('<h2 id="schemas">Schemas</h2>')
    for name, s in spec.get("components", {}).get("schemas", {}).items():
        if name.startswith("Body_") or name in ("HTTPValidationError", "ValidationError"):
            continue
        parts.append(f'<div class="endpoint" id="schema-{esc(name)}"><h3>{esc(name)}</h3>')
        if s.get("description"):
            parts.append(f'<p class="desc-pre">{md(s["description"])}</p>')
        table = props_table(s)
        parts.append(table or f"<p>Type: {type_of(s)}</p>")
        parts.append("</div>")
    parts.append('<div class="pager"><a href="/docs/sdk.html">← SDK</a><a href="/docs/self-hosting.html">'
                 "Self-hosting →</a></div>")
    return "\n".join(parts)


def page(content: str) -> str:
    tpl = TEMPLATE.read_text(encoding="utf-8")
    start, end = "<!-- content:start -->", "<!-- content:end -->"
    if start not in tpl or end not in tpl:
        sys.exit(f"{TEMPLATE}: missing content markers")
    head, rest = tpl.split(start, 1)
    _, tail = rest.split(end, 1)
    head = re.sub(r"<title>.*?</title>", f"<title>{esc(TITLE)}</title>", head, count=1)
    head = re.sub(r'(<meta (?:name="description"|property="og:description") content=")[^"]*"',
                  lambda m: m.group(1) + esc(DESC) + '"', head)
    head = re.sub(r'(<meta property="og:title" content=")[^"]*"', lambda m: m.group(1) + esc(TITLE) + '"', head)
    head = re.sub(r'(<link rel="canonical" href="|<meta property="og:url" content=")__SITE_URL__/docs/"',
                  r'\1__SITE_URL__/docs/api.html"', head)
    head = head.replace('<a href="/docs/" aria-current="page">Overview</a>', '<a href="/docs/">Overview</a>')
    head = head.replace('<a href="/docs/api.html">API reference</a>',
                        '<a href="/docs/api.html" aria-current="page">API reference</a>')
    head = head.replace("<!doctype html>\n", "<!doctype html>\n<!-- Generated by site/build_api_docs.py from "
                        "packages/sdk/openapi.json. Do not edit by hand. -->\n", 1)
    return head + start + "\n" + content + "\n" + end + tail


def main() -> None:
    spec = json.loads(SPEC.read_text(encoding="utf-8"))
    out = page(render(spec))
    if "--check" in sys.argv:
        current = OUT.read_text(encoding="utf-8") if OUT.exists() else ""
        if current != out:
            sys.exit(f"{OUT} is out of date: run python3 site/build_api_docs.py")
        print("api.html is up to date")
        return
    OUT.write_text(out, encoding="utf-8")
    print(f"wrote {OUT.relative_to(SITE.parent)}")


if __name__ == "__main__":
    main()
