# `/infra` — Infrastructure-as-code

Everything needed to bring the stack up from a clean machine and keep it safe.

- `../docker-compose.yml` — single-command stack (Phase 2: healthchecks, restart
  policies, Caddy reverse proxy, MinIO bucket bootstrap).
- `../.env.example` — config template; copy to `.env` (never committed).
- `caddy/Caddyfile` — Caddy reverse proxy config (HTTP on port 80 → Directus).
- `backup/backup.sh` — compressed `pg_dump` + MinIO upload.
- `backup/restore.sh` — download from MinIO + `psql` restore.

**Quick-start (Phase 2):**

```bash
cp .env.example .env        # fill in secrets
make up                     # bring stack up
make bootstrap-minio        # create d1-files + d1-backups buckets (once)
make migrate && make seed   # apply schema + reference data
```

**Backup / restore:**

```bash
make backup                                               # create and upload
BACKUP_FILE=d1_<ts>.sql.gz make restore                  # restore from MinIO
```

See `docs/runbooks/backup-restore.md` for the full runbook.

Target runtime: **Docker on Windows** (Docker Desktop / WSL2), Linux-portable.
