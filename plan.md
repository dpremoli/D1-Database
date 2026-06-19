# D1-Database — Implementation Plan

> A self-hosted, API-first Laboratory Information Management System (LIMS) for
> materials-science sample genealogy, dynamic manufacturing logs, nested tooling
> tracking, high-capacity data ingestion, and LLM-driven text-to-SQL querying.
>
> Requirements source of truth: [`system_requirements_specification.md`](./system_requirements_specification.md).
> This document is the *how* and *when*; the spec is the *what* and *why*.

---

## Context

The lab runs on AppSheet over flat Google Sheets, which breaks down on relational
hierarchies, programmatic high-volume ingest (10–100 GB files), scalability,
multi-user accountability, and rigid schemas. The target is a PostgreSQL-centric,
fully containerised, vendor-agnostic system, deliberately structured so a local
LLM can reliably generate SQL against it.

This is a **multi-session, multi-month build**, authored primarily by Claude with
the maintainer reviewing — so every phase produces explicit docs/ADRs and is
**resumable cold** in a later session. The plan is **staggered**: each phase is
runnable and testable, and later phases depend on earlier ones. **Foundation-first.**

---

## Decisions locked (from planning interview)

| Decision | Choice | Rationale |
|---|---|---|
| **Core engine** | **Directus** over our own Postgres schema | Free admin UI, API, RBAC, file handling → minimal code to author/maintain |
| **Lock-in stance** | **Directus is a swappable adapter; Postgres is the durable core** | Maintainer wants the option to drop Directus later without losing the system |
| **Schema ownership** | **Our versioned SQL migrations own the schema**; Directus only *introspects* | Schema + data survive a Directus removal; stays LLM-friendly |
| **Audit log** | **Postgres trigger-based** append-only `audit_logs` (not Directus revisions) | Captures direct/machine writes, immutable, survives adapter swap (spec §4) |
| **Project-specific compute** | Lives in **separate plugin containers**, never in the core | Heavy-data parsing, text-to-SQL/LLM, custom analysis, equipment integrations |
| **Core↔plugin contract** | *Deferred to Phase 3/4* — but designed Directus-agnostic | Must be reimplementable if Directus is dropped |
| **Front-end** | **Deferred** — rely on Directus admin UI + `v_` views first | Custom traceability timeline is a later phase |
| **Sequencing** | Foundation-first | Maintainer preference |
| **Deployment** | **Docker on Windows now** (Docker Desktop/WSL2), Linux-portable | Keep compose OS-agnostic |
| **Data migration** | **Later**; Sheets export received & analysed ([`docs/legacy-data-analysis.md`](./docs/legacy-data-analysis.md)) | 17 sheets mapped; informs Phase 1; import is Phase 8 |
| **License / visibility** | **Private for now**; license chosen before any public release | — |

---

## North-star architecture

```
                    ┌─────────────────────────────────────────┐
   Humans  ───────► │  DIRECTUS  (swappable adapter)           │
   (browser)        │  admin UI · REST/GraphQL · RBAC          │
                    └───────────────┬─────────────────────────┘
   Machines ──────► (static token)  │ introspects, never mutates structure
   (MATLAB/rigs)                    ▼
                    ┌─────────────────────────────────────────┐
                    │  POSTGRESQL  ── THE DURABLE CORE         │
                    │  our migrations · FK constraints ·       │
                    │  COMMENTs · v_ views · audit triggers ·  │
                    │  OCC version cols · pgvector             │
                    └───────────────┬─────────────────────────┘
                                    │  documented API contract + queue + MinIO
        ┌───────────────┬──────────┴───────────┬───────────────────┐
        ▼               ▼                       ▼                   ▼
  PLUGIN: heavy-   PLUGIN: text-to-       PLUGIN: custom      PLUGIN: equipment
  data worker      SQL / LLM (Ollama,     analysis logic      integrations
  (memmap parse)   pgvector)              (per-project)       (MATLAB/rig adapters)
```

**The rule that prevents lock-in:** no business logic that the system *depends
on* lives in Directus config. Constraints, audit, concurrency, derived views,
and as much RBAC as practical are native Postgres objects. Directus is presentation.

---

## Guiding principles (apply to every phase)

- **Postgres is the contract.** Descriptive names, units in column names, FK
  constraints, `COMMENT` strings, and `v_` views are the product backbone and
  the thing the LLM reads. We hand-design it; no framework auto-generates it.
- **Adapter-swappable.** At any phase we could, in principle, replace Directus
  with a thin FastAPI layer over the *same* schema. We don't build that now, but
  we never take a dependency that would forbid it.
- **Everything is infrastructure-as-code.** One `docker compose up` from a clean
  machine to a running stack.
- **Migrations only.** No manual DB edits; every change is a reviewed, reversible
  migration. Directus must not auto-alter structure.
- **Resumable docs.** Each phase leaves an ADR + runbook so a future cold session
  (or reviewer) has full context.
- **Vertical, testable phases.** Each phase ships something demoable.

---

## Phase 0 — Repository & Project Foundation
*Goal: a professional, reproducible, private repo skeleton. No business logic.*

- Initial commit; `.gitignore` (Python, Node, Docker, OS, `.env`/secrets),
  `.editorconfig`. **No `LICENSE` yet** (private); add a brief proprietary notice.
- `README.md` (vision, the north-star diagram, quick-start, status).
- `docs/adr/` — ADRs for the locked decisions above (ADR-0001 Postgres-as-core,
  ADR-0002 Directus-as-swappable-adapter, ADR-0003 trigger-based audit).
- `CONTRIBUTING.md`, `SECURITY.md`, `.github/` issue/PR templates, CI skeleton
  (lint + migration check on push).
- Tooling: `pre-commit` (ruff/black, sqlfluff, hadolint), Conventional Commits,
  `Makefile` for common commands.
- `docker-compose.yml` skeleton + `.env.example`.
- Repo layout stubbed:
  ```
  /db        SQL migrations, seed data, schema docs, audit triggers
  /core      Directus config-as-code (roles, collections, flows) — version-controlled
  /plugins   one folder per plugin container (worker, llm, analysis, equipment)
  /infra     compose, env templates, backup/restore scripts
  /docs      ADRs, runbooks, data-dictionary, API contract
  /tests     integration / e2e
  ```

**Done when:** clone → `make setup` → green CI on an empty pipeline.

---

## Phase 1 — Core Relational Schema (the keystone)
*Goal: the durable Postgres core — genealogy, integrity, AI-readiness, audit.*
*Input: Sheets export analysed — see [`docs/legacy-data-analysis.md`](./docs/legacy-data-analysis.md).*

Implements spec §2 + §6 together (interdependent). Entity design is now grounded
in the 17 real sheets, not assumptions.

- Migration tooling: `dbmate`/`sqitch`/Flyway (plain-SQL, Directus-independent).
- Tables with FK constraints and descriptive, unit-bearing names:
  - `raw_stock_lots` (swarf/powder/billet/chemical; inbound & remaining mass,
    supplier, grade, data sheets). **NEW** — no such ledger exists today;
    provenance is currently free-text on FAST Runs (weakest current link).
  - `manufacturing_methods`, `method_parameters` (`parameter_name`, `data_type`,
    `unit_of_measure`) — the dynamic process-template engine. Validated by the
    real data: FAST Runs vs Machining Operations share almost no columns.
  - `physical_samples` ← *Inventory*, with a **dual identifier**:
    `sample_id` (GUID/UUID) is the hidden, permanent **primary key** (all FKs
    point here); `sample_code` (e.g. `10-AA-MF-2023-06-03`) is a human-readable,
    sequential **pseudonym** — unique-constrained, deterministically generated,
    deliberately legible so a physical sample found years later is identifiable.
    **Add sample→sample genealogy** (`parent_sample_id` + `sample_composition`
    junction) — the real `Parent`/`Contains`/`Contains_All` columns show discs
    cut into child pieces.
  - `manufacturing_operations` (FKs + `recorded_metadata JSONB`) ← unifies
    *FAST Runs* + *Machining Operations*; optional `insert_edge_id` and
    `file_storage_pointer` for ops that consume edges / produce big files.
  - Nested tooling: `tool_boxes` ← *Insert Boxes Inventory* → `cutting_inserts`
    ← *Inserts* → `insert_edges` ← *Inserts Edges* (3 levels confirmed exact).
  - `test_sessions` (UUID, FKs incl. `insert_edge_id`, `file_storage_pointer`).
  - `projects` / campaigns (e.g. `AI4340`) ← experiment sheets roll up to a
    project with controlled-document numbering (AMRC GESS). **NEW** grouping
    above operations — see [`docs/experiment-sheets-and-naming.md`](./docs/experiment-sheets-and-naming.md).
  - Reference/lookup tables: `materials`/`alloys` (← *Alloy Codes*), `equipment`
    (← *Machines*), `tools`, `insert_types`, ISO material classification.
  - Sample ↔ raw-stock provenance (many-to-many).
  - Capture provenance on operations that produce files: capture software +
    version (`ABFP`) and sampling frequency [kHz] — needed to read files later.
  - NC programs (G-code) as text/file artifacts linked to operations.
  - **Shared deterministic code-generation service** (one place): produces the
    compositional human-readable IDs — `sample_code`
    (`{seq}-{alloy}-{method}-{date}`), pass code (`…-F9`/`…-R1`), and force-file
    ID (`…-20MPM_0.05feed_0.1DoC`). All are projections of FK + parameter data,
    never primary keys. Dual identity also applies to inserts/edges (`H13A-#2-fC`).
  - **Honour `Export Controlled?`** flags in the visibility/RBAC model (potential
    ITAR/ECJU concern) — carry the flag from day one.
- **AI-readiness from day one:** `COMMENT ON TABLE/COLUMN` everywhere (the
  semantic dictionary); native FKs for a coherent `information_schema`; `v_*`
  flattened views (e.g. `v_complete_sample_history`).
- **Audit & concurrency (native):** append-only `audit_logs` + generic trigger
  capturing `INSERT/UPDATE/DELETE` JSON deltas; `version`/`updated_at` for OCC.
- **JSONB-vs-LLM resolution:** core entities/relationships stay typed+FK; JSONB
  only for genuinely variable method params; document the JSONB key space in the
  dictionary and surface it via views. (ADR.)
- `pgvector` extension enabled (columns added in Phase 6).
- Seed/fixture data + schema-diagram docs (`tbls`/`schemaspy`).

**Done when:** migrations apply up/down cleanly; seed loads; audit triggers fire;
generated schema docs render the relationships.

---

## Phase 2 — Infrastructure & Orchestration
*Goal: the whole stack runs from one compose file with persistent volumes.*

Implements spec §7.

- `docker-compose.yml`: PostgreSQL 15+ (with pgvector), MinIO (+console), Redis,
  Directus, reverse proxy. Healthchecks, named volumes, restart policies.
- Windows/Docker-Desktop notes; keep compose Linux-portable.
- Centralised `.env` config + documented secrets model.
- MinIO bucket bootstrap + retention policy.
- **Backup & restore:** scripted `pg_dump` + MinIO mirror; a *tested* restore
  runbook in `docs/runbooks/`. (Schema is plain SQL, so backups are adapter-free.)

**Done when:** `docker compose up` on a clean host → healthy stack; backup → wipe
→ restore reproduces state.

---

## Phase 3 — Core Tracking Layer (Directus) + API Contract
*Goal: authenticated, role-aware tracking over the schema, with OCC + audit intact.*

Implements spec §4 and the §2 dynamic-template UX. **Config-as-code in `/core`.**

- Point Directus at the existing schema (introspect, do **not** let it alter
  structure). Configure collections, relations, and the dynamic-template forms.
- RBAC roles `Operator` / `Researcher` / `Administrator`; document the mapping so
  it's reproducible (and re-implementable if Directus is dropped).
- Machine nodes: revocable **static tokens** as machine users
  (`Rig_1_Fast_Sampling_Node`) — also the auth path for plugins/equipment.
- Surface `GET /items/samples/{id}` full profile (the MATLAB pre-test query, §3).
- Verify OCC rejects stale writes; verify every mutation hits `audit_logs`.
- **Publish the documented API contract** in `/docs` — the Directus-agnostic
  interface plugins will use (so a FastAPI swap stays feasible).

**Done when:** a machine token authenticates, fetches a sample, logs an
operation; a stale update is rejected; the mutation appears in `audit_logs`;
Directus config is reproducible from version control.

---

## Phase 4 — Heavy-Data Pipeline (first plugin) ✅ Done
*Goal: 10–100 GB files move without touching the core's memory. Establishes the plugin pattern.*

Implemented: `plugins/heavy-data-worker/` — Flask webhook receiver + rq worker
container. D1F binary format (64-byte header + float32 row-major); streaming
stats (chunked reads, ≤ `WORKER_MEMORY_LIMIT_MB` peak); strided-read SVG plotter
(≤ 10 k points); MinIO multipart presign/complete API; Directus PATCH write-back.
Plugin contract documented in `docs/plugin-contract.md`; ADR in
`docs/adr/0006-heavy-data-pipeline.md`; runbook in
`docs/runbooks/heavy-data-pipeline.md`. CI adds a `worker-build` job (docker
build + pytest). Integration test at `tests/phase4_heavy_data.sh`.

---

## Phase 5 — Plugin Framework: Analysis & Equipment
*Goal: generalise Phase 4's contract into a reusable plugin template.*

- Plugin scaffolding/template (Dockerfile + contract client) others can copy.
- **Custom analysis** container template (per-project compute, swappable).
- **Equipment integration** adapter pattern (MATLAB clients / acquisition rigs).
- Each plugin authenticates via token, consumes the documented contract only —
  no direct schema coupling beyond the published interface.

**Done when:** a second, non-trivial plugin is stood up from the template with no
core changes.

---

## Phase 6 — AI-Readiness & Local Text-to-SQL (plugin)
*Goal: a local LLM answers NL questions against the DB safely.*

Implements spec §6 (parts not already in Phase 1).

- Complete/expand `v_*` views as LLM query targets; export the semantic
  dictionary (from `COMMENT`s) as LLM context.
- Local **Ollama** (Llama-3/Mistral) with a guarded text-to-SQL path: **read-only
  Postgres role**, statement timeout, view allow-list — no destructive statements.
- `pgvector`: embed unstructured test notes / algorithm outputs; hybrid
  semantic + relational search.
- NL→SQL evaluation set to measure accuracy/regression.

**Done when:** a curated question set returns correct SQL against a read-only role.

---

## Phase 7 — Traceability UI (deferred front-end)
*Goal: bi-directional cradle-to-grave navigation. Spec §5.*

- Start by leaning on Directus relational browsing over the `v_*` views.
- Then a dedicated **cradle-to-grave timeline**: stock lot → operations → tests.
- Forward (expand node → operator/asset/metadata) and reverse (file/session →
  insert edge → insert → tool box → originating stock) traceability.

**Done when:** any sample's full lineage is walkable forward and backward without
dead ends.

---

## Phase 8 — Legacy Data Migration
*Goal: import existing AppSheet/Sheets data once the schema is proven.*

- Use the maintainer's Sheets export: extract → map to schema → validate → load.
- Idempotent, re-runnable migration scripts; reconciliation report.
- Provenance preserved (audit log notes the migration source).

**Done when:** legacy data loads with a validated reconciliation report.

---

## Phase 9 — Hardening, Security, Ops & the "Drop-Directus" Drill
*Goal: production confidence + proof the lock-in escape hatch is real.*

- Tests: unit, integration, e2e across the §3 pipeline.
- Security: token revocation, RBAC boundaries, MinIO policy, **text-to-SQL
  injection surface**, dependency scanning.
- Performance: large-file pipeline load tests; index tuning.
- Observability: structured logs, health/metrics.
- **Drop-Directus drill:** stand up a minimal FastAPI read API over the *same*
  schema to *prove* the core is adapter-independent (validation, not a migration).
- Docs pass: runbooks, data dictionary, ADRs current.

**Done when:** a new operator can deploy, back up, restore, and operate from docs
alone; the drop-Directus drill succeeds.

---

## Open / deferred decisions (revisit at the noted phase)

- **Core↔plugin contract specifics** — finalize in Phase 4 (kept Directus-agnostic).
- **RBAC durability** — how much to anchor in Postgres roles/RLS vs Directus
  roles, for swap-safety. Decide in Phase 3.
- **Queue** — Redis/Celery (lean) vs RabbitMQ. Decide in Phase 4.
- **License** — before any public release.
- **Sample identifier** — GUID vs serialized barcode (spec allows both). Phase 1.

---

## Status tracker

| Phase | Status | Notes |
|------:|--------|-------|
| 0 | ✅ Done | Repo foundation — structure, ADRs, tooling, CI, smoke test (48 checks green) |
| 1 | ✅ Done | Postgres core — 12 migrations, 6 views, audit+OCC triggers, code-gen functions, seeds, ADR-0004, data-dictionary, CI migrations job |
| 2 | ✅ Done | Compose stack — healthchecks, restart policies, Caddy proxy, MinIO bootstrap, backup/restore scripts + runbook |
| 3 | ✅ Done | Directus RBAC (3 roles, machine tokens), API contract doc, ADR-0005, phase3 test script, core/apply.sh config-as-code |
| 4 | ✅ Done | Heavy-data pipeline — D1F worker, presigned multipart upload, streaming stats, SVG plots, plugin-contract doc, CI worker-build job |
| 5 | ☐ Not started | Plugin framework (analysis/equipment) |
| 6 | ☐ Not started | Text-to-SQL + pgvector |
| 7 | ☐ Not started | Traceability UI (deferred) |
| 8 | ☐ Not started | Legacy data migration |
| 9 | ☐ Not started | Hardening + drop-Directus drill |
