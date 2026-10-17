#!/usr/bin/env bash
# Deploy zerch (git HEAD) to a shared Docker host that runs a shared Caddy (see README.md).
#
#   ZERCH_DEPLOY_SSH="ubuntu@host" ZERCH_DEPLOY_KEY=~/.ssh/key \
#   ZERCH_API_HOST=zerch.example.com ZERCH_DEMO_HOST=zerch-demo.example.com deploy/app-a1/deploy.sh
#
# First run writes /srv/zerch/.env (random secrets, chmod 600) and creates the demo project.
# Secrets never leave the box and are never printed.
set -euo pipefail

: "${ZERCH_DEPLOY_SSH:?user@host}" "${ZERCH_API_HOST:?}" "${ZERCH_DEMO_HOST:?}"
HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
SSH=(ssh -o BatchMode=yes ${ZERCH_DEPLOY_KEY:+-i "$ZERCH_DEPLOY_KEY"} "$ZERCH_DEPLOY_SSH")
VERSION="$(git -C "$ROOT" rev-parse --short HEAD)"
WIDGET="$ROOT/packages/widget/dist/zerch-widget.js"

[ -f "$WIDGET" ] || { echo "build the widget first: npm install && npm run build" >&2; exit 1; }
[ -z "$(git -C "$ROOT" status --porcelain -- src packs pyproject.toml uv.lock Dockerfile docker)" ] ||
  echo "warning: uncommitted service changes are not deployed (git HEAD is)" >&2

echo "==> shipping $VERSION"
"${SSH[@]}" 'mkdir -p /srv/zerch/demo && rm -rf /srv/zerch/app.new && mkdir /srv/zerch/app.new'
git -C "$ROOT" archive HEAD | "${SSH[@]}" 'tar -x -C /srv/zerch/app.new && rm -rf /srv/zerch/app && mv /srv/zerch/app.new /srv/zerch/app'
"${SSH[@]}" 'cat > /srv/zerch/compose.yml' < "$HERE/compose.yml"
"${SSH[@]}" 'cat > /srv/zerch/demo/zerch-widget.js' < "$WIDGET"

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
docker compose build --pull api opensearch
docker tag "zerch:$1" zerch:latest
docker compose up -d --remove-orphans
REMOTE

echo "==> caddy site"
sed -e "s/^API_HOST /$ZERCH_API_HOST /" -e "s/^DEMO_HOST /$ZERCH_DEMO_HOST /" "$HERE/zerch.caddy.tmpl" |
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
"${SSH[@]}" python3 - "$ZERCH_API_HOST" "$ZERCH_DEMO_HOST" < "$HERE/demo_project.py"
sed -e "s#YOUR_PROJECT_ID#__PROJECT__#" "$ROOT/examples/plain-html/index.html" |
  "${SSH[@]}" "cd /srv/zerch && P=\$(python3 -c 'import json;print(json.load(open(\"demo-project.json\"))[\"project_id\"])') &&
    K=\$(python3 -c 'import json;print(json.load(open(\"demo-project.json\"))[\"search_key\"])') &&
    sed -e \"s#__PROJECT__#\$P#\" -e \"s#YOUR_SEARCH_KEY#\$K#\" -e 's#http://localhost:8000#https://$ZERCH_API_HOST#' > demo/index.html"
echo "done: https://$ZERCH_API_HOST/healthz  https://$ZERCH_DEMO_HOST/"
