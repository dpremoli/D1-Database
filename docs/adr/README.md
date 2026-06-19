# Architecture Decision Records (ADRs)

Each ADR captures one significant, hard-to-reverse decision: its context, the
choice, and the consequences. They exist so a future session or reviewer can
understand *why* the system is the way it is without re-litigating it.

Format: lightweight [MADR](https://adr.github.io/madr/)-style. Status is one of
`Proposed` / `Accepted` / `Superseded by ADR-XXXX`.

| ADR | Title | Status |
|---|---|---|
| [0001](./0001-postgres-as-durable-core.md) | PostgreSQL is the durable core | Accepted |
| [0002](./0002-directus-as-swappable-adapter.md) | Directus is a swappable adapter | Accepted |
| [0003](./0003-trigger-based-immutable-audit.md) | Trigger-based immutable audit log | Accepted |
| [0004](./0004-jsonb-for-dynamic-method-params.md) | JSONB for dynamic method params | Accepted |
| [0005](./0005-directus-rbac-structure.md) | Directus RBAC structure | Accepted |
| [0006](./0006-heavy-data-pipeline.md) | Direct-to-MinIO heavy-data pipeline | Accepted |

New ADRs: copy the structure of an existing one, take the next number, and add a
row above.
