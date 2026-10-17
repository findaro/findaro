#!/usr/bin/env bash
# Deploy findaro (git HEAD) to a shared Docker host that runs a shared Caddy (see README.md).
#
#   FINDARO_DEPLOY_SSH="ubuntu@host" FINDARO_DEPLOY_KEY=~/.ssh/key \
#   FINDARO_SITE_HOST=findaro.example.com FINDARO_API_HOST=api.findaro.example.com \
#   [FINDARO_OLD_HOSTS="old.example.com"] [FINDARO_GITHUB_URL=...] [FINDARO_COMPANY_NAME=...] deploy/app-a1/deploy.sh
#
# First run writes /srv/findaro/.env (random secrets, chmod 600) and creates the demo project.
# Secrets never leave the box and are never printed.
set -euo pipefail

: "${FINDARO_DEPLOY_SSH:?user@host}" "${FINDARO_SITE_HOST:?}" "${FINDARO_API_HOST:?}"
GITHUB_URL="${FINDARO_GITHUB_URL:-https://github.com/findaro/findaro}"
COMPANY="${FINDARO_COMPANY_NAME:-findaro}"
HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
SSH=(ssh -o BatchMode=yes ${FINDARO_DEPLOY_KEY:+-i "$FINDARO_DEPLOY_KEY"} "$FINDARO_DEPLOY_SSH")
VERSION="$(git -C "$ROOT" rev-parse --short HEAD)"
WIDGET="$ROOT/packages/widget/dist/findaro-widget.js"

[ -f "$WIDGET" ] || { echo "build the widget first: npm install && npm run build" >&2; exit 1; }
[ -z "$(git -C "$ROOT" status --porcelain -- src packs site pyproject.toml uv.lock Dockerfile docker deploy)" ] ||
  echo "warning: uncommitted changes are not deployed (git HEAD is)" >&2

echo "==> shipping $VERSION"
"${SSH[@]}" 'mkdir -p /srv/findaro && rm -rf /srv/findaro/app.new && mkdir /srv/findaro/app.new'
git -C "$ROOT" archive HEAD | "${SSH[@]}" 'tar -x -C /srv/findaro/app.new && rm -rf /srv/findaro/app && mv /srv/findaro/app.new /srv/findaro/app'
"${SSH[@]}" 'cd /srv/findaro && cp app/deploy/app-a1/compose.yml compose.yml && cp app/deploy/app-a1/backup.sh backup.sh'
"${SSH[@]}" 'cat > /srv/findaro/findaro-widget.js' < "$WIDGET"

echo "==> secrets (first run only), build, start"
"${SSH[@]}" bash -s "$VERSION" <<'REMOTE'
set -euo pipefail
cd /srv/findaro
if [ ! -f .env ]; then
  umask 077
  cat > .env <<ENV
POSTGRES_PASSWORD=$(openssl rand -hex 24)
FINDARO_BOOTSTRAP_TOKEN=$(openssl rand -hex 32)
# LLM off: rules planner + template chat answers. To enable a paid provider set e.g.
# FINDARO_LLM_PROVIDER=none, FINDARO_CHAT_PROVIDER=openai, OPENAI_API_KEY=...
FINDARO_LLM_PROVIDER=none
ENV
fi
chmod 600 .env
sed -i "/^FINDARO_VERSION=/d" .env && echo "FINDARO_VERSION=$1" >> .env
umask 077 && mkdir -p backups/postgres backups/opensearch && chmod 700 backups
# OpenSearch runs as uid 1000 and writes snapshots into backups/opensearch
[ "$(stat -c %u backups/opensearch)" = 1000 ] || sudo -n chown 1000:1000 backups/opensearch
mkdir -p site
docker compose build --pull api opensearch
docker tag "findaro:$1" findaro:latest
docker compose up -d --remove-orphans
# drop this app's older image tags (only findaro:<sha>; never a global prune on a shared box)
docker images --format '{{.Repository}}:{{.Tag}}' | grep -E '^findaro:[0-9a-f]{7,}$' | grep -vx "findaro:$1" |
  xargs -r docker image rm >/dev/null 2>&1 || true
docker builder prune -f --keep-storage 3gb >/dev/null  # build cache only; keeps the newest layers for rebuilds
({ crontab -l 2>/dev/null || true; } | { grep -v '/srv/findaro/backup.sh' || true; }; echo '17 21 * * * /srv/findaro/backup.sh >> /srv/findaro/backups/backup.log 2>&1') | crontab -
REMOTE

echo "==> caddy site"
sed -e "s/__SITE_HOST__/$FINDARO_SITE_HOST/g" -e "s/__API_HOST__/$FINDARO_API_HOST/g" "$HERE/findaro.caddy.tmpl" |
  if [ -n "${FINDARO_OLD_HOSTS:-}" ]; then sed "s/__OLD_HOSTS__/$FINDARO_OLD_HOSTS/"; else sed '/__OLD_HOSTS__/,/^}/d'; fi |
  "${SSH[@]}" 'cat > /srv/caddy/sites/findaro.caddy.new
cd /srv/caddy
cp sites/findaro.caddy sites/findaro.caddy.bak 2>/dev/null || true
mv sites/findaro.caddy.new sites/findaro.caddy
if docker exec -w /etc/caddy caddy-caddy-1 caddy validate --config Caddyfile --adapter caddyfile >/dev/null 2>&1; then
  docker exec -w /etc/caddy caddy-caddy-1 caddy reload --config Caddyfile --adapter caddyfile
  rm -f sites/findaro.caddy.bak
else
  echo "caddy config invalid; restoring previous findaro site" >&2
  if [ -f sites/findaro.caddy.bak ]; then mv sites/findaro.caddy.bak sites/findaro.caddy; else rm -f sites/findaro.caddy; fi
  exit 1
fi'

echo "==> demo project"
"${SSH[@]}" python3 /srv/findaro/app/deploy/app-a1/demo_project.py "$FINDARO_API_HOST" "$FINDARO_SITE_HOST"

echo "==> website"
"${SSH[@]}" python3 /srv/findaro/app/deploy/app-a1/render_site.py "https://$FINDARO_SITE_HOST" "https://$FINDARO_API_HOST" \
  "$GITHUB_URL" "$COMPANY"
"${SSH[@]}" 'cd /srv/findaro && docker compose restart site >/dev/null'  # the bind mount points at the replaced dir
echo "done: https://$FINDARO_SITE_HOST  https://$FINDARO_API_HOST/healthz"
