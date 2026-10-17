# Deploying to a shared single-box host

For a small ARM64 (or x86) Docker host that already runs a shared Caddy reverse proxy on an external Docker
network called `web`, with one directory per app under `/srv` and one site file per app under
`/srv/caddy/sites/`.

```bash
npm install && npm run build      # the widget for the demo page
ZERCH_DEPLOY_SSH=ubuntu@<host> ZERCH_DEPLOY_KEY=~/.ssh/<key> \
ZERCH_API_HOST=zerch.<domain> ZERCH_DEMO_HOST=zerch-demo.<domain> \
deploy/app-a1/deploy.sh
```

What it does:

0. One-time: `sudo install -d -o ubuntu -g ubuntu /srv/zerch`.
1. Copies `git archive HEAD` to `/srv/zerch/app` and builds the images on the box (native architecture).
2. First run only: writes `/srv/zerch/.env` with a random Postgres password and bootstrap token (chmod 600).
   Secrets stay on the box; nothing prints them.
3. Starts the `zerch` compose project, writes `/srv/caddy/sites/zerch.caddy`, validates the Caddy config and
   reloads it (an invalid config is rolled back).
4. Creates the demo project if needed (admin key kept in `/srv/zerch/demo-project.json`, chmod 600), restricts
   its search key to the demo origin, and writes the demo page.

Layout and limits (`compose.yml`):

| Service | Networks | Memory | Notes |
|---|---|---|---|
| `zerch-api` | web, internal | 1280m | non-root, read-only rootfs, no capabilities |
| worker | internal | 1280m | same hardening, no internet |
| opensearch | internal | 2g (1g heap) | security plugin off; only reachable on `internal` |
| postgres | internal | 256m | |
| redis | internal | 160m | cache only, no persistence |
| `zerch-demo` | web | 48m | nginx serving `/srv/zerch/demo`, read-only |

`internal` is a Docker `internal: true` network: data services can't reach the internet and other apps on
the box can't reach them. No service publishes host ports.

LLM: off by default (`ZERCH_LLM_PROVIDER=none` in `.env`): rules-only query understanding and template chat
answers. Local Ollama models are too slow for the planner timeout on a 2-core box. To use a paid provider, edit
`/srv/zerch/.env` (e.g. `ZERCH_CHAT_PROVIDER=openai` + `OPENAI_API_KEY=...`) and `docker compose up -d`.

Ops:

```bash
cd /srv/zerch && docker compose ps && docker compose logs -f --tail=100 api worker
docker stats --no-stream $(docker compose ps -q)
# Bootstrap token, for creating projects: grep ^ZERCH_BOOTSTRAP_TOKEN= /srv/zerch/.env
```
