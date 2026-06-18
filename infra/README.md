# `/infra` — Infrastructure-as-code

Everything needed to bring the stack up from a clean machine and keep it safe.

- `../docker-compose.yml` — the single-command stack (root level for convenience).
- `../.env.example` — config template; copy to `.env` (never committed).
- `backup/` — scripted `pg_dump` + MinIO mirror, and the tested restore runbook.

Target runtime: **Docker on Windows** (Docker Desktop / WSL2) for now, kept
Linux-portable. Hardened with healthchecks, volumes, and limits in **Phase 2**.
