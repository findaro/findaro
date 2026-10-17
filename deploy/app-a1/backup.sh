#!/usr/bin/env bash
# Nightly backups for the findaro compose project (installed in the deploy user's crontab by deploy.sh):
# Postgres dump + OpenSearch snapshot into /srv/findaro/backups, keeping 14 days. Both stay on this box;
# copy them off-box for real disaster recovery.
set -euo pipefail
cd /srv/findaro
umask 077
mkdir -p backups/postgres
stamp=$(date -u +%Y%m%d-%H%M)
docker compose exec -T postgres pg_dump -U findaro -d findaro --no-owner | gzip > "backups/postgres/findaro-$stamp.sql.gz"
find backups/postgres -name 'findaro-*.sql.gz' -mtime +14 -delete

os() { docker compose exec -T opensearch curl -fsS -H 'content-type: application/json' "$@"; }
os -X PUT localhost:9200/_snapshot/nightly -d '{"type":"fs","settings":{"location":"/snapshots"}}' >/dev/null
os -X PUT "localhost:9200/_snapshot/nightly/findaro-$stamp?wait_for_completion=true" \
  -d '{"indices":"findaro-*","include_global_state":false}' >/dev/null
for snap in $(os "localhost:9200/_cat/snapshots/nightly?h=id" | sort | head -n -14); do
  os -X DELETE "localhost:9200/_snapshot/nightly/$snap" >/dev/null
done
echo "backup ok $stamp"
