# D1-Database

A self-hosted, API-first **Laboratory Information Management System (LIMS)** for
materials-science research: sample genealogy, dynamic manufacturing/test logs,
deeply nested tooling tracking, high-capacity (10–100 GB) data ingestion, and
LLM-driven natural-language querying — replacing a brittle AppSheet-over-Google-
Sheets setup.

> **Status:** 🚧 Phase 0 (repository foundation). Private & proprietary — see
> [`NOTICE.md`](./NOTICE.md). Multi-phase build; see [`plan.md`](./plan.md).

## Why

The lab outgrew spreadsheets: no real relational hierarchies, no way to ingest
multi-gigabyte instrument files, weak provenance, no audit trail, and rigid
hardcoded columns. The full problem statement is in
[`system_requirements_specification.md`](./system_requirements_specification.md).

## Architecture at a glance

**Postgres is the durable core; Directus is a swappable adapter.** All logic the
system depends on (schema, constraints, audit, concurrency, views) lives in the
database as native objects; Directus only provides UI/API/RBAC on top and can be
replaced without losing the system. Project-specific compute lives in isolated
plugin containers.

```
   Humans  ───────►  DIRECTUS  (swappable adapter: admin UI · REST/GraphQL · RBAC)
   Machines ──────►  └─ introspects, never mutates structure ─┐
   (MATLAB/ABFP)                                               ▼
                     POSTGRESQL ── THE DURABLE CORE
                     migrations · FK · COMMENTs · v_ views · audit triggers ·
                     OCC version cols · pgvector
                                     │  documented API contract + queue + MinIO
        ┌────────────────┬──────────┴───────────┬────────────────────┐
        ▼                ▼                        ▼                    ▼
   heavy-data       text-to-SQL /            custom analysis      equipment
   worker           LLM (Ollama)             (per-project)        integrations
```

See [`docs/adr/`](./docs/adr/) for the decisions behind this and
[`plan.md`](./plan.md) for the staggered, phase-by-phase roadmap.

## Repository layout

| Path | Contents |
|---|---|
| [`db/`](./db/) | SQL migrations, seeds — the schema (the contract) |
| [`core/`](./core/) | Directus configuration-as-code |
| [`plugins/`](./plugins/) | Project-specific compute, one container per folder |
| [`infra/`](./infra/) | Compose stack, env templates, backup/restore |
| [`docs/`](./docs/) | ADRs, runbooks, data dictionary, legacy-data analysis |
| [`tests/`](./tests/) | Integration & end-to-end tests |

## Quick start

> The stack is built out in Phases 1–2. Today this bootstraps tooling only.

```sh
cp .env.example .env      # then edit secrets
make setup                # install pre-commit hooks & dev tooling
make up                   # (Phase 2+) bring up the Docker stack
```

Requires Docker (Desktop/WSL2 on Windows) and `pre-commit`. Run `make help` for
all targets.

## Tech stack

PostgreSQL 15+ (with `pgvector`) · Directus · MinIO (S3-compatible) · Redis ·
Python workers · Ollama (local LLM) · Docker Compose.

## Key documents

- [`plan.md`](./plan.md) — the staggered implementation plan & status tracker
- [`system_requirements_specification.md`](./system_requirements_specification.md) — requirements
- [`docs/legacy-data-analysis.md`](./docs/legacy-data-analysis.md) — analysis of the legacy AppSheet/Sheets data
- [`docs/experiment-sheets-and-naming.md`](./docs/experiment-sheets-and-naming.md) — experiment sheets & deterministic naming
- [`CONTRIBUTING.md`](./CONTRIBUTING.md) · [`SECURITY.md`](./SECURITY.md)
