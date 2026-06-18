#!/usr/bin/env bash
# D1-Database — restore script.
#
# Downloads a backup from MinIO and restores it into PostgreSQL.
# Requires the stack to be running (docker compose up -d).
#
# Usage:
#   BACKUP_FILE=d1_20260618T120000Z.sql.gz bash infra/backup/restore.sh
#
# For a local-only restore (skip MinIO download if file already exists locally):
#   SKIP_DOWNLOAD=1 BACKUP_FILE=d1_20260618T120000Z.sql.gz bash infra/backup/restore.sh
#
# Environment (loaded from .env if present):
#   POSTGRES_USER, POSTGRES_DB, MINIO_ROOT_USER, MINIO_ROOT_PASSWORD
#   BACKUP_DIR   — local directory for dumps (default: ./backups)
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$ROOT"

[[ -f .env ]] && set -a && source .env && set +a

: "${BACKUP_FILE:?BACKUP_FILE must be set, e.g. BACKUP_FILE=d1_20260618T120000Z.sql.gz}"

POSTGRES_USER="${POSTGRES_USER:-d1}"
POSTGRES_DB="${POSTGRES_DB:-d1_database}"
MINIO_ROOT_USER="${MINIO_ROOT_USER:-minioadmin}"
MINIO_ROOT_PASSWORD="${MINIO_ROOT_PASSWORD:-change_me_too}"
BACKUP_DIR="${BACKUP_DIR:-./backups}"
SKIP_DOWNLOAD="${SKIP_DOWNLOAD:-0}"

echo "=== D1-Database Restore: $BACKUP_FILE ==="

if [[ "$SKIP_DOWNLOAD" == "1" && -f "$BACKUP_DIR/$BACKUP_FILE" ]]; then
    echo "[1/3] Using local copy (SKIP_DOWNLOAD=1): $BACKUP_DIR/$BACKUP_FILE"
else
    echo "[1/3] Downloading from MinIO (d1-backups/$BACKUP_FILE) …"
    mkdir -p "$BACKUP_DIR"
    docker run --rm \
        --network d1-database_d1net \
        -v "$ROOT/$BACKUP_DIR:/backups" \
        -e MC_HOST_local="http://${MINIO_ROOT_USER}:${MINIO_ROOT_PASSWORD}@minio:9000" \
        minio/mc:latest \
        mc cp "local/d1-backups/$BACKUP_FILE" "/backups/$BACKUP_FILE"
    echo "      → $BACKUP_DIR/$BACKUP_FILE"
fi

echo "[2/3] Restoring into PostgreSQL …"
echo
echo "  ╔══════════════════════════════════════════════════════╗"
echo "  ║  WARNING: this will DROP and recreate all objects    ║"
echo "  ║  in '$POSTGRES_DB'. All current data will be lost.   ║"
echo "  ║  Press Ctrl-C within 10 seconds to abort.           ║"
echo "  ╚══════════════════════════════════════════════════════╝"
echo
sleep 10

# The dump was created with --clean --if-exists, so it drops each object
# before recreating it. Running it through psql is sufficient.
zcat "$BACKUP_DIR/$BACKUP_FILE" \
    | docker compose exec -T postgres \
        psql -U "$POSTGRES_USER" "$POSTGRES_DB" > /dev/null

echo "[3/3] Restore complete."
echo
echo "  Verify: make schema-test"
