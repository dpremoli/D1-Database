# ADR-0001 — PostgreSQL is the durable core

- **Status:** Accepted
- **Date:** 2026-06-18
- **Deciders:** Maintainer + Claude (planning session)

## Context

The system must be highly maintainable, free, open-source, self-hosted, and
structured so a local LLM can reliably generate SQL against it
(`system_requirements_specification.md` §6). It also has a hard requirement to
**survive the removal of any application framework** (see ADR-0002): the
maintainer explicitly wants the option to drop Directus later without losing the
system.

## Decision

**PostgreSQL is the single source of truth and the durable core.** Every piece
of logic the system *depends on* is expressed as a native database object, not
application/framework configuration:

- Schema, types, and **`FOREIGN KEY` constraints** (relational integrity in the DB).
- **`COMMENT` strings** on every table/column (the semantic dictionary for the LLM).
- **`v_` views** for flattened, LLM-friendly query targets.
- **Audit** via triggers (ADR-0003) and **optimistic concurrency** via version
  columns.
- The schema is owned by **versioned SQL migrations** in [`/db`](../../db/);
  nothing else may alter structure.

## Consequences

- **Positive:** maximal portability and longevity; a coherent `information_schema`
  for text-to-SQL; backups are plain SQL and adapter-independent; any application
  layer (Directus today, FastAPI tomorrow) is replaceable over the same schema.
- **Negative / cost:** we forgo framework conveniences that auto-manage schema;
  we must hand-design and migrate the schema deliberately; some logic that a
  framework offers (e.g. revisions) we reimplement natively.
- **Validated by data:** the legacy export confirmed divergent process types and
  deep hierarchies that demand real relational modelling, not spreadsheet tabs
  (see `docs/legacy-data-analysis.md`).
