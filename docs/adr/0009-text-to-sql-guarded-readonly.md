# ADR-0009 — Local Text-to-SQL via a Guarded, Read-Only Path

- **Status:** Accepted
- **Date:** 2026-06-19
- **Deciders:** Maintainer + Claude (Phase 6)

## Context

Spec §6 requires that a **self-hosted** LLM (Llama-3/Mistral via Ollama) can
answer natural-language questions against the database — "text-to-SQL" — without
any data leaving the host. The schema was deliberately built for this from
Phase 1: descriptive, unit-bearing column names, native FK constraints, a
`COMMENT` on every table/column, and flattened `v_*` views (spec §6, ADR-0001).

The hard problem is not generating SQL; it is **trusting** it. An LLM will, at
some rate, emit wrong, unsafe, or injected SQL (`DROP`, `UPDATE`, cross-table
reads of export-controlled rows or the audit log, unbounded scans). We need the
NL→SQL capability without giving a probabilistic text generator write access or
an unbounded read surface.

A second §6 requirement is **hybrid semantic search**: embed unstructured note
text with `pgvector` so questions can match on meaning, not just keywords.

## Decision

Implement text-to-SQL as a **plugin** (`plugins/llm-text-to-sql/`) in front of a
**two-layer safety boundary**, with the durable half of that boundary living in
Postgres (per ADR-0001) so it survives a Directus removal:

1. **Application SQL guard** (`app/lib/sql_guard.py`) — the primary boundary.
   LLM output is parsed with **sqlglot** (a real parser, not regexes) and
   rejected unless it is exactly one read-only `SELECT`/`WITH`/`UNION`,
   references **only** an allow-list of `v_*` views, and contains no DML/DDL/
   utility node. A `LIMIT` is enforced by wrapping the query.

2. **Read-only Postgres role** (`d1_llm_readonly`, in the migration) —
   defence-in-depth. A NOLOGIN privilege bundle with `SELECT` on the
   allow-listed views **only** (never base tables, never `audit_logs`),
   `default_transaction_read_only = on`, and a `statement_timeout`. The plugin
   connects through a login role that inherits it, and additionally pins
   read-only + timeout per connection (role-level `SET`s are not inherited by
   member login roles).

Supporting durable-core objects (same migration):

- `v_schema_dictionary` — table/column `COMMENT`s as a queryable view; the
  plugin builds the LLM prompt straight from it, so the prompt never drifts from
  the live schema.
- `v_llm_query_targets` — the allow-list "menu" of views, mirroring the guard's
  `ALLOWED_RELATIONS` (the menu is a subset of the guard list).
- `semantic_embeddings` (`vector(768)` + HNSW cosine index) and
  `v_embeddings_source_notes` — the pgvector store and its backfill source for
  hybrid search.

The NL→SQL **evaluation set** (`eval/questions.json`) pins curated gold queries;
`tests/test_eval_golds.py` asserts every gold still passes the guard in CI.

## Rationale

- **Two independent layers.** The guard can be bypassed by a parser edge case;
  the role can be mis-provisioned. Requiring *both* to fail before harm occurs
  is the standard defence-in-depth posture for "untrusted SQL".
- **Postgres is the contract (ADR-0001).** The allow-list, read-only role, and
  semantic dictionary are database objects, so the drop-Directus drill (Phase 9)
  and any future FastAPI adapter inherit the safe query surface unchanged.
- **AST parsing over string matching.** sqlglot defeats comment- and
  whitespace-based evasion (`SELECT * FROM /* */ audit_logs`) that a denylist of
  keywords would miss.
- **Prompt from the live dictionary.** Reading `v_schema_dictionary` at request
  time means the model always sees current columns and `COMMENT`s — no second
  copy to maintain, and the units-in-names convention does the LLM's
  disambiguation for it.
- **Embeddings as rebuildable, derived data.** `semantic_embeddings` is keyed by
  `(source_table, source_id, source_column, model_name)` with a `content_hash`
  for incremental, idempotent backfill; it carries no audit trigger because it is
  reconstructible from the source rows.

## Consequences

**Positive**

- NL questions answerable locally with a hard guarantee of read-only,
  allow-listed access; verified by the guard's allow/deny matrix and
  `tests/phase6_text_to_sql.sh` (grant isolation against a real login role).
- Adapter-independent and reusable by the Phase 9 FastAPI drill.
- Hybrid semantic search over note text via pgvector.

**Negative / deferred**

- Ollama and its models are heavy, so the `llm` compose profile is opt-in and
  the models are pulled manually (documented in the runbook). Not started in CI.
- Embedding dimension is pinned to 768 (nomic-embed-text); switching to a model
  with a different dimension needs a follow-up migration.
- Semantic correctness of generated SQL is measured by the live eval mode and
  human review; only the safe-and-runnable property is asserted automatically.

## Verification

- `plugins/llm-text-to-sql/tests/` — SQL-guard allow/deny matrix (incl. stacked
  statements, comment-hidden tables, `SELECT INTO`, base-table and audit reads),
  schema-context building, the `/api/ask` reject-and-run paths, and gold-set
  validation. Runs in CI as the `llm-build` job.
- `tests/phase6_text_to_sql.sh` — asserts the views/table/index/role exist, the
  dictionary is populated, the menu excludes internal views, and a login member
  of `d1_llm_readonly` can read the allow-listed views but **cannot** read base
  tables, the audit log, or write. Runs in CI after the schema migrations.
