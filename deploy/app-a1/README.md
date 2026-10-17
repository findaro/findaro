# Deploying to a shared single-box host

For a small ARM64 (or x86) Docker host that already runs a shared Caddy reverse proxy on an external Docker
network called `web`, with one directory per app under `/srv` and one site file per app under
`/srv/caddy/sites/`.

```bash
npm install && npm run build      # the widget for the demo page
FINDARO_DEPLOY_SSH=ubuntu@<host> FINDARO_DEPLOY_KEY=~/.ssh/<key> \
FINDARO_SITE_HOST=findaro.<domain> FINDARO_API_HOST=api.findaro.<domain> \
deploy/app-a1/deploy.sh
```

What it does:

0. One-time: `sudo install -d -o ubuntu -g ubuntu /srv/findaro`.
1. Copies `git archive HEAD` to `/srv/findaro/app` and builds the images on the box (native architecture).
2. First run only: writes `/srv/findaro/.env` with a random Postgres password and bootstrap token (chmod 600).
   Secrets stay on the box; nothing prints them.
3. Starts the `findaro` compose project, writes `/srv/caddy/sites/findaro.caddy`, validates the Caddy config and
   reloads it (an invalid config is rolled back).
4. Creates the demo project if needed (admin key kept in `/srv/findaro/demo-project.json`, chmod 600), restricts
   its search key to the demo origin, and renders the site with its key (the live demo is `site/public/demo/`).

Layout and limits (`compose.yml`):

| Service | Networks | Memory | Notes |
|---|---|---|---|
| `findaro-api` | web, internal | 1280m | non-root, read-only rootfs, no capabilities |
| worker | internal | 1280m | same hardening, no internet |
| opensearch | internal | 2g (1g heap) | security plugin off; only reachable on `internal` |
| postgres | internal | 256m | |
| redis | internal | 128m | cache, rate limits, pending usage counters; no persistence |
| `findaro-site` | web, internal | 160m | website + `/api/request-access`; same image, engine not loaded |

`internal` is a Docker `internal: true` network: data services can't reach the internet and other apps on
the box can't reach them. No service publishes host ports.

LLM: off by default (`FINDARO_LLM_PROVIDER=none` in `.env`): rules-only query understanding and template chat
answers. Local Ollama models are too slow for the planner timeout on a 2-core box. To use a paid provider, edit
`/srv/findaro/.env` (e.g. `FINDARO_CHAT_PROVIDER=openai` + `OPENAI_API_KEY=...`) and `docker compose up -d`.

Ops:

```bash
cd /srv/findaro && docker compose ps && docker compose logs -f --tail=100 api worker
docker stats --no-stream $(docker compose ps -q)
# Bootstrap token, for creating projects: grep ^FINDARO_BOOTSTRAP_TOKEN= /srv/findaro/.env
```
