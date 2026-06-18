# `/core` — Directus configuration-as-code

Directus is the **swappable adapter** over the Postgres core: it provides the
admin UI, REST/GraphQL API, RBAC, and file handling, but owns **no business
logic the system depends on**
(see [`../docs/adr/0002-directus-as-swappable-adapter.md`](../docs/adr/0002-directus-as-swappable-adapter.md)).

This directory version-controls Directus configuration so it is reproducible and
reviewable — roles/permissions, collection presentation, and Flows. Directus
**introspects** the schema; it must never alter structure.

Populated in **Phase 3**.
