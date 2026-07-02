#!/usr/bin/env bash
# Apply all Directus configuration in the correct order, then flush + restart.
# Order matters: inline params recreate fields that field-presets then customise.
set -euo pipefail
PG=${PG_CONTAINER:-d1-database-postgres-1}
DIRECTUS=${DIRECTUS_CONTAINER:-d1-database-directus-1}
REDIS=${REDIS_CONTAINER:-d1-database-redis-1}
HERE="$(cd "$(dirname "$0")" && pwd)"

for f in configure_directus.sql configure_inline_params.sql configure_field_presets.sql configure_sample_prep.sql configure_campaigns.sql configure_operation_files.sql configure_project_rollup.sql; do
  echo "── $f ──"
  docker exec -i "$PG" psql -U d1 -d d1_database < "$HERE/$f" 2>&1 | grep -iE "error" && exit 1 || true
done

docker exec "$REDIS" redis-cli FLUSHALL >/dev/null
docker restart "$DIRECTUS" >/dev/null
echo "Applied all config + restarted Directus."
