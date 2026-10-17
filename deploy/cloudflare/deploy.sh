#!/usr/bin/env bash
# Put the hosted Findaro behind Cloudflare (Worker on custom domains), so the origin's address isn't in DNS.
#
#   FINDARO_DEPLOY_SSH=ubuntu@host FINDARO_DEPLOY_KEY=~/.ssh/key \
#   FINDARO_PUBLIC_SITE_HOST=findaro.example.com FINDARO_PUBLIC_API_HOST=findaro-api.example.com \
#   FINDARO_SITE_HOST=<origin site host> FINDARO_API_HOST=<origin api host> deploy/cloudflare/deploy.sh
#
# Needs `wrangler login`. The edge secret is read from the box's /srv/findaro/.env (created there if missing)
# and piped into `wrangler secret put`; it is never printed or written locally.
set -euo pipefail
: "${FINDARO_DEPLOY_SSH:?}" "${FINDARO_PUBLIC_SITE_HOST:?}" "${FINDARO_PUBLIC_API_HOST:?}" "${FINDARO_SITE_HOST:?}" \
  "${FINDARO_API_HOST:?}"
HERE="$(cd "$(dirname "$0")" && pwd)"
SSH=(ssh -o BatchMode=yes ${FINDARO_DEPLOY_KEY:+-i "$FINDARO_DEPLOY_KEY"} "$FINDARO_DEPLOY_SSH")
cd "$HERE"

"${SSH[@]}" 'cd /srv/findaro && umask 077 && { grep -q "^FINDARO_EDGE_SECRET=." .env ||
  echo "FINDARO_EDGE_SECRET=$(openssl rand -hex 32)" >> .env; }'
CONF="$HERE/.wrangler.generated.toml"
trap 'rm -f "$CONF"' EXIT
cat wrangler.toml - > "$CONF" <<TOML

routes = [
  { pattern = "$FINDARO_PUBLIC_SITE_HOST", custom_domain = true },
  { pattern = "$FINDARO_PUBLIC_API_HOST", custom_domain = true },
]

[vars]
PUBLIC_SITE = "$FINDARO_PUBLIC_SITE_HOST"
PUBLIC_API = "$FINDARO_PUBLIC_API_HOST"
ORIGIN_SITE = "$FINDARO_SITE_HOST"
ORIGIN_API = "$FINDARO_API_HOST"
TOML
wrangler deploy -c "$CONF"
"${SSH[@]}" 'grep "^FINDARO_EDGE_SECRET=" /srv/findaro/.env | cut -d= -f2-' |
  wrangler secret put EDGE_SECRET -c "$CONF" >/dev/null
echo "edge deployed: https://$FINDARO_PUBLIC_SITE_HOST  https://$FINDARO_PUBLIC_API_HOST"
