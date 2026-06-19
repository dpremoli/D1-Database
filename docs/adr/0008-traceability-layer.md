# ADR-0008 — Cradle-to-Grave Traceability as Postgres Functions

- **Status:** Accepted
- **Date:** 2026-06-19
- **Deciders:** Maintainer + Claude (Phase 7)

## Context

Spec §5 requires bi-directional, cradle-to-grave traceability: from any sample
you must be able to walk **forward** (into the child pieces cut from it, and the
operations and tests performed on them) and **backward** (up the genealogy to the
raw stock lot it originated from), with no dead ends.

The genealogy is already modelled relationally:

- `sample_genealogy(child_sample_id, parent_sample_id, relationship_type, fraction)`
  — the self-referential parent/child graph (discs cut into coupons, etc.).
- `sample_stock_provenance(sample_id, lot_id, mass_used_grams)` — which raw
  `raw_stock_lots` fed which samples.
- `manufacturing_operations` and `test_sessions` — the events performed on a
  sample.

The one-hop view `v_sample_genealogy_flat` only exposes direct parent/child
pairs. Multi-level lineage (a coupon → its disc → its billet → its stock lot) is
an arbitrary-depth recursion, which a flat view cannot express.

The front-end is deliberately deferred (Phase 7 in the plan notes that we lean on
Directus relational browsing first). The question is therefore **where the
traceability logic lives**, not what UI renders it.

## Decision

Implement traceability as **set-returning PostgreSQL functions** in a versioned
migration (`db/migrations/...traceability.sql`), not in application code or a
Directus extension:

- `f_trace_ancestors(sample)` — recursive child→parent walk to the roots.
- `f_trace_descendants(sample)` — recursive parent→child walk to the leaves.
- `f_trace_stock_origins(sample)` — the raw stock lots feeding a sample or any
  of its ancestors (closes the cradle end).
- `f_sample_timeline(sample)` — manufacturing operations and test sessions for a
  sample, interleaved chronologically.

All functions are `STABLE`, side-effect free, and cycle-guarded with a path
array so malformed data (a genealogy loop) cannot hang the query.

## Rationale

- **Postgres is the durable contract.** Per ADR-0001, business logic the system
  depends on lives in the database, not in a swappable adapter. Traceability is
  core domain logic; encoding it in SQL means it survives a Directus removal and
  is reusable by Directus, ad-hoc SQL, the backup/restore path, and the Phase 6
  LLM text-to-SQL layer — one correct implementation, many consumers.
- **Recursive CTEs are the right tool.** Arbitrary-depth lineage is naturally a
  `WITH RECURSIVE` query. Doing it in application code would mean N+1 round trips
  or re-implementing graph traversal per client.
- **No throwaway UI.** A bespoke React timeline would be deferred work that the
  Directus admin UI and these functions already make navigable. When a dedicated
  timeline UI is built later, it consumes these functions rather than
  duplicating the traversal.
- **Cycle safety over the CYCLE clause.** A manual `path` array with a
  `NOT (id = ANY(path))` guard is explicit and portable; `sample_genealogy`
  already forbids self-loops, but longer cycles from bad imports must still
  terminate.

## Consequences

**Positive**

- Full forward/reverse lineage walkable from any sample with a single function
  call; verified end-to-end by `tests/phase7_traceability.sh`.
- Adapter-independent: the "drop-Directus drill" (Phase 9) inherits traceability
  for free.
- Directly consumable by the Phase 6 read-only LLM role (the functions are
  `SELECT`-able like views).

**Negative / deferred**

- No graphical timeline yet; users navigate via Directus or call the functions
  directly. A dedicated visual cradle-to-grave UI remains optional future work.
- Very deep genealogies (thousands of hops) are not expected here; if they ever
  arise, the recursion depth and path-array size would need review.

## Verification

`tests/phase7_traceability.sh` builds an isolated BILLET → DISC → PIECE-A/B
fixture with a stock lot, an operation, and a test session, then asserts the
ancestor count and root, the stock-origin lot, the descendant count and depth,
and the chronological timeline. Runs in CI after the schema migrations and seed.
