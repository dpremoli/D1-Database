# ADR-0003 — Trigger-based immutable audit log

- **Status:** Accepted
- **Date:** 2026-06-18
- **Deciders:** Maintainer + Claude (planning session)

## Context

The spec (§4B) requires that **every** data mutation (`INSERT`/`UPDATE`/`DELETE`)
on core entities automatically writes to an isolated, append-only `audit_logs`
table capturing timestamp, actor, action, target, and a JSON state delta. Writes
arrive from two directions: human edits via the UI/API **and** automated machine
nodes (MATLAB/`ABFP`, plugins) writing directly. Directus offers a built-in
"revisions" feature that overlaps with this requirement.

## Decision

Implement audit as a **PostgreSQL trigger-based, append-only `audit_logs`
table** — a generic trigger function attached to core tables. This is the single
source of truth for change history. Directus revisions may *complement* it for
UI-edit ergonomics but are **not** the system of record.

## Consequences

- **Positive:** cannot be bypassed — captures direct/machine writes that never
  pass through the application layer; language-agnostic; survives replacing the
  application layer (consistent with ADR-0001/0002); immutable by design.
- **Negative / cost:** trigger maintenance as the schema evolves; care needed so
  bulk migrations (Phase 8) annotate their source rather than flooding the log.
- **Security relevance:** the legacy `Users` data stored plaintext passwords and
  lacked any change history (`docs/legacy-data-analysis.md`); a tamper-evident
  audit trail directly addresses the accountability gap that motivated the project.
