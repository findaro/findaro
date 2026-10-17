#!/usr/bin/env bash
# Deploy zerch (git HEAD) to a shared Docker host that runs a shared Caddy (see README.md).
#
#   ZERCH_DEPLOY_SSH="ubuntu@host" ZERCH_DEPLOY_KEY=~/.ssh/key \
#   ZERCH_SITE_HOST=zerch.example.com ZERCH_API_HOST=api.zerch.example.com \
#   [ZERCH_OLD_HOSTS="old.example.com"] [ZERCH_GITHUB_URL=...] [ZERCH_COMPANY_NAME=...] deploy/app-a1/deploy.sh
#
# First run writes /srv/zerch/.env (random secrets, chmod 600) and creates the demo project.
# Secrets never leave the box and are never printed.
set -euo pipefail

: "${ZERCH_DEPLOY_SSH:?user@host}" "${ZERCH_SITE_HOST:?}" "${ZERCH_API_HOST:?}"
GITHUB_URL="${ZERCH_GITHUB_URL:-https://github.com/rohitsaini1196/zerch}"
COMPANY="${ZERCH_COMPANY_NAME:-zerch}"
HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
SSH=(ssh -o BatchMode=yes ${ZERCH_DEPLOY_KEY:+-i "$ZERCH_DEPLOY_KEY"} "$ZERCH_DEPLOY_SSH")
VERSION="$(git -C "$ROOT" rev-parse --short HEAD)"
WIDGET="$ROOT/packages/widget/dist/zerch-widget.js"

[ -f "$WIDGET" ] || { echo "build the widget first: npm install && npm run build" >&2; exit 1; }
[ -z "$(git -C "$ROOT" status --porcelain -- src packs site pyproject.toml uv.lock Dockerfile docker deploy)" ] ||
  echo "warning: uncommitted changes are not deployed (git HEAD is)" >&2

echo "==> shipping $VERSION"
"${SSH[@]}" 'mkdir -p /srv/zerch && rm -rf /srv/zerch/app.new && mkdir /srv/zerch/app.new'
git -C "$ROOT" archive HEAD | "${SSH[@]}" 'tar -x -C /srv/zerch/app.new && rm -rf /srv/zerch/app && mv /srv/zerch/app.new /srv/zerch/app'
"${SSH[@]}" 'cd /srv/zerch && cp app/deploy/app-a1/compose.yml compose.yml && cp app/deploy/app-a1/backup.sh backup.sh'
"${SSH[@]}" 'cat > /srv/zerch/zerch-widget.js' < "$WIDGET"

echo "==> secrets (first run only), build, start"
"${SSH[@]}" bash -s "$VERSION" <<'REMOTE'
set -euo pipefail
cd /srv/zerch
if [ ! -f .env ]; then
  umask 077
  cat > .env <<ENV
POSTGRES_PASSWORD=$(openssl rand -hex 24)
ZERCH_BOOTSTRAP_TOKEN=$(openssl rand -hex 32)
# LLM off: rules planner + template chat answers. To enable a paid provider set e.g.
# ZERCH_LLM_PROVIDER=none, ZERCH_CHAT_PROVIDER=openai, OPENAI_API_KEY=...
ZERCH_LLM_PROVIDER=none
ENV
fi
chmod 600 .env
sed -i "/^ZERCH_VERSION=/d" .env && echo "ZERCH_VERSION=$1" >> .env
umask 077 && mkdir -p backups/postgres backups/opensearch && chmod 700 backups
# OpenSearch runs as uid 1000 and writes snapshots into backups/opensearch
[ "$(stat -c %u backups/opensearch)" = 1000 ] || sudo -n chown 1000:1000 backups/opensearch
mkdir -p site
docker compose build --pull api opensearch
docker tag "zerch:$1" zerch:latest
docker compose up -d --remove-orphans
({ crontab -l 2>/dev/null || true; } | { grep -v '/srv/zerch/backup.sh' || true; }; echo '17 21 * * * /srv/zerch/backup.sh >> /srv/zerch/backups/backup.log 2>&1') | crontab -
REMOTE

echo "==> caddy site"
sed -e "s/__SITE_HOST__/$ZERCH_SITE_HOST/g" -e "s/__API_HOST__/$ZERCH_API_HOST/g" "$HERE/zerch.caddy.tmpl" |
  if [ -n "${ZERCH_OLD_HOSTS:-}" ]; then sed "s/__OLD_HOSTS__/$ZERCH_OLD_HOSTS/"; else sed '/__OLD_HOSTS__/,/^}/d'; fi |
  "${SSH[@]}" 'cat > /srv/caddy/sites/zerch.caddy.new
cd /srv/caddy
cp sites/zerch.caddy sites/zerch.caddy.bak 2>/dev/null || true
mv sites/zerch.caddy.new sites/zerch.caddy
if docker exec -w /etc/caddy caddy-caddy-1 caddy validate --config Caddyfile --adapter caddyfile >/dev/null 2>&1; then
  docker exec -w /etc/caddy caddy-caddy-1 caddy reload --config Caddyfile --adapter caddyfile
  rm -f sites/zerch.caddy.bak
else
  echo "caddy config invalid; restoring previous zerch site" >&2
  if [ -f sites/zerch.caddy.bak ]; then mv sites/zerch.caddy.bak sites/zerch.caddy; else rm -f sites/zerch.caddy; fi
  exit 1
fi'

echo "==> demo project"
"${SSH[@]}" python3 /srv/zerch/app/deploy/app-a1/demo_project.py "$ZERCH_API_HOST" "$ZERCH_SITE_HOST"

echo "==> website"
"${SSH[@]}" python3 /srv/zerch/app/deploy/app-a1/render_site.py "https://$ZERCH_SITE_HOST" "https://$ZERCH_API_HOST" \
  "$GITHUB_URL" "$COMPANY"
"${SSH[@]}" 'cd /srv/zerch && docker compose restart site >/dev/null'  # the bind mount points at the replaced dir
echo "done: https://$ZERCH_SITE_HOST  https://$ZERCH_API_HOST/healthz"
