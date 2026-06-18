# `/core` — Directus configuration-as-code

Directus is the **swappable adapter** over the Postgres core: it provides the
admin UI, REST/GraphQL API, RBAC, and file handling, but owns **no business
logic the system depends on**
(see [`../docs/adr/0002-directus-as-swappable-adapter.md`](../docs/adr/0002-directus-as-swappable-adapter.md)).

This directory version-controls Directus configuration so it is reproducible
and reviewable. Directus **introspects** the schema; it must never alter structure.

## Files

| File | Purpose |
|---|---|
| `roles.json` | Operator, Researcher, Administrator role definitions |
| `permissions.json` | Permission matrix — what each role can read/write |
| `apply.sh` | Bootstrap script: applies roles + permissions via API, provisions machine user, snapshots schema |
| `schema-snapshot.yaml` | Generated schema snapshot (created by `apply.sh`; commit after first run) |

## Quick-start (Phase 3)

```bash
# 1. Stack must be up and migrations applied
make up && make migrate && make seed

# 2. Apply config-as-code
DIRECTUS_URL=http://localhost:8055 \
DIRECTUS_ADMIN_EMAIL=admin@example.com \
DIRECTUS_ADMIN_PASSWORD=your_password \
bash core/apply.sh
```

`apply.sh` is idempotent — roles and machine users it finds already existing
are skipped. The Rig_1 machine token is printed once to stdout; store it in
your secrets manager (1Password, Vault, etc.).

## RBAC summary

| Role | Access |
|---|---|
| **Operator** | Create + update samples, operations, test sessions, tooling; read reference tables; no audit_logs |
| **Researcher** | Read everything, including audit_logs; no writes |
| **Administrator** | Full access + system settings |

Machine users (e.g. `Rig_1_Fast_Sampling_Node`) use the **Operator** role
with a static bearer token. See [ADR-0005](../docs/adr/0005-directus-rbac-structure.md)
and the [API contract](../docs/api-contract.md).
