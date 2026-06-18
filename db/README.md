# `/db` — The durable Postgres core

This directory owns the **schema** — the contract the whole system depends on
(see [`../docs/adr/0001-postgres-as-durable-core.md`](../docs/adr/0001-postgres-as-durable-core.md)).

- `migrations/` — versioned, reversible SQL migrations. **The schema is changed
  only here**, never via the Directus UI or manual edits.
- `seeds/` — reference/lookup data and fixtures for local/dev environments.

Migration tooling is selected in **Phase 1** (`dbmate` / `sqitch` / Flyway —
plain-SQL, Directus-independent). Until then these folders are placeholders.
