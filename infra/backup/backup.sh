#!/usr/bin/env bash
# D1-Database — backup script.
#
# Creates a compressed PostgreSQL dump and uploads it to MinIO.
# Requires the stack to be running (docker compose up -d).
#
# Usage:
#   bash infra/backup/backup.sh
#
# Environment (loaded from .env if present, or set externally):
#   POSTGRES_USER, POSTGRES_DB, MINIO_ROOT_USER, MINIO_ROOT_PASSWORD
#   BACKUP_DIR   — local directory for dumps (default: ./backups)
#   MINIO_API_PORT — MinIO API port on localhost (default: 9000)
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$ROOT"

# Load .env if present (silently skip missing vars we may not need).
[[ -f .env ]] && set -a && source .env && set +a

POSTGRES_USER="${POSTGRES_USER:-d1}"
POSTGRES_DB="${POSTGRES_DB:-d1_database}"
MINIO_ROOT_USER="${MINIO_ROOT_USER:-minioadmin}"
MINIO_ROOT_PASSWORD="${MINIO_ROOT_PASSWORD:-change_me_too}"
MINIO_API_PORT="${MINIO_API_PORT:-9000}"
BACKUP_DIR="${BACKUP_DIR:-./backups}"
TIMESTAMP="$(date -u +%Y%m%dT%H%M%SZ)"
BACKUP_FILE="d1_${TIMESTAMP}.sql.gz"

mkdir -p "$BACKUP_DIR"

echo "=== D1-Database Backup: $TIMESTAMP ==="

echo "[1/3] Dumping PostgreSQL …"
# --clean --if-exists produces DROP IF EXISTS before each object so that
# restoring into a populated database works without manual teardown.
docker compose exec -T postgres \
    pg_dump -U "$POSTGRES_USER" --clean --if-exists "$POSTGRES_DB" \
    | gzip > "$BACKUP_DIR/$BACKUP_FILE"
SIZE="$(du -sh "$BACKUP_DIR/$BACKUP_FILE" | cut -f1)"
echo "      → $BACKUP_DIR/$BACKUP_FILE ($SIZE)"

echo "[2/3] Uploading to MinIO (d1-backups bucket) …"
# MC_HOST_<alias> format: http://user:password@host:port
docker run --rm \
    --network d1-database_d1net \
    -v "$ROOT/$BACKUP_DIR:/backups:ro" \
    -e MC_HOST_local="http://${MINIO_ROOT_USER}:${MINIO_ROOT_PASSWORD}@minio:9000" \
    minio/mc:latest \
    sh -c "mc mb --ignore-existing local/d1-backups \
        && mc cp /backups/$BACKUP_FILE local/d1-backups/$BACKUP_FILE"
echo "      → minio://d1-backups/$BACKUP_FILE"

echo "[3/3] Backup complete."
echo
echo "  Local copy : $BACKUP_DIR/$BACKUP_FILE"
echo "  MinIO key  : d1-backups/$BACKUP_FILE"
echo
echo "  To restore : BACKUP_FILE=$BACKUP_FILE bash infra/backup/restore.sh"
echo "  To prune   : make prune-backups  (removes local copies older than 30 days)"
