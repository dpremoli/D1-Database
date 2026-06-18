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

New ADRs: copy the structure of an existing one, take the next number, and add a
row above.
