-- migrate:up
-- Phase 6 — AI-readiness & local text-to-SQL foundations (spec §6).
--
-- This migration adds the *durable-core* half of the text-to-SQL capability so it
-- survives a Directus removal and is shared by every consumer (Directus, ad-hoc
-- SQL, the LLM plugin):
--   1. v_schema_dictionary    — the semantic dictionary (table/column COMMENTs)
--                               exposed as a queryable view, so the LLM context
--                               builder reads it with plain SQL.
--   2. v_llm_query_targets     — the allow-list menu of v_* views the LLM may
--                               query, with their business-logic descriptions.
--   3. semantic_embeddings     — pgvector store for unstructured note text, for
--                               hybrid semantic + relational search.
--   4. v_embeddings_source_notes — the canonical set of note columns the embedder
--                               backfills from (one row per embeddable note).
--   5. d1_llm_readonly         — a NOLOGIN privilege bundle granting SELECT on the
--                               allow-listed views only (never base tables), with
--                               read-only + statement-timeout defaults. The LLM
--                               plugin connects through a login role that inherits
--                               it (see docs/runbooks/text-to-sql.md).
--
-- The SQL-guard in the plugin is the primary injection boundary; this role is
-- defence-in-depth so even a guard bypass cannot mutate or read outside the menu.

-- ---------------------------------------------------------------------------
-- v_schema_dictionary — table/column COMMENTs as a flat, queryable dictionary.
-- The LLM context builder selects from this instead of parsing pg_catalog.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE VIEW v_schema_dictionary AS
SELECT
    c.relname                                   AS object_name,
    a.attnum                                    AS column_position,
    a.attname                                   AS column_name,
    a.attnotnull                                AS is_not_null,
    CASE c.relkind
        WHEN 'r' THEN 'table'
        WHEN 'v' THEN 'view'
        WHEN 'm' THEN 'materialized_view'
        ELSE c.relkind::TEXT
    END                                         AS object_type,
    format_type(a.atttypid, a.atttypmod)         AS data_type,
    obj_description(c.oid, 'pg_class')           AS object_comment,
    col_description(c.oid, a.attnum)             AS column_comment
FROM pg_class AS c
INNER JOIN pg_namespace AS n ON c.relnamespace = n.oid
INNER JOIN pg_attribute AS a ON c.oid = a.attrelid
WHERE n.nspname = 'public'
    AND c.relkind IN ('r', 'v')
    AND a.attnum > 0
    AND NOT a.attisdropped
ORDER BY c.relname, a.attnum;

COMMENT ON VIEW v_schema_dictionary
    IS 'Flat semantic dictionary: every public table/view column with its native'
       ' COMMENT, type, and nullability. Primary LLM context source (spec §6).';

-- ---------------------------------------------------------------------------
-- v_llm_query_targets — the allow-listed v_* views the LLM may query.
-- These mirror the SQL-guard allow-list in the plugin; keep the two in sync.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE VIEW v_llm_query_targets AS
SELECT
    c.relname                           AS view_name,
    obj_description(c.oid, 'pg_class')   AS description
FROM pg_class AS c
INNER JOIN pg_namespace AS n ON c.relnamespace = n.oid
WHERE n.nspname = 'public'
    AND c.relkind = 'v'
    AND c.relname LIKE 'v\_%'
    -- v_llm_query_targets is the menu itself; v_embeddings_source_notes is an
    -- internal backfill source, not a user-facing query target.
    AND c.relname NOT IN ('v_llm_query_targets', 'v_embeddings_source_notes')
ORDER BY c.relname;

COMMENT ON VIEW v_llm_query_targets
    IS 'Menu of flattened v_* views the text-to-SQL LLM is allowed to query, with'
       ' their business-logic descriptions. Mirrors the plugin SQL-guard allow-list.';

-- ---------------------------------------------------------------------------
-- semantic_embeddings — pgvector store for unstructured note text.
-- Polymorphic by (source_table, source_id, source_column) so any note column can
-- be embedded without a column per source. content_hash lets the backfill skip
-- unchanged rows; the UNIQUE constraint makes re-embedding an idempotent upsert.
-- Dimension 768 matches Ollama's nomic-embed-text default; changing the embedding
-- model to a different dimension requires a follow-up migration.
-- ---------------------------------------------------------------------------
CREATE TABLE semantic_embeddings (
    embedding_id    UUID            NOT NULL DEFAULT uuid_generate_v4(),
    source_table    TEXT            NOT NULL,
    source_id       UUID            NOT NULL,
    source_column   TEXT            NOT NULL,
    content_text    TEXT            NOT NULL,
    content_hash    TEXT            NOT NULL,
    embedding       VECTOR(768)     NOT NULL,
    model_name      TEXT            NOT NULL,
    created_at      TIMESTAMPTZ     NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ     NOT NULL DEFAULT now(),
    CONSTRAINT semantic_embeddings_pkey PRIMARY KEY (embedding_id),
    CONSTRAINT semantic_embeddings_source_uq
        UNIQUE (source_table, source_id, source_column, model_name)
);

CREATE INDEX semantic_embeddings_hnsw_idx
    ON semantic_embeddings USING hnsw (embedding vector_cosine_ops);

CREATE INDEX semantic_embeddings_source_idx
    ON semantic_embeddings (source_table, source_id);

COMMENT ON TABLE semantic_embeddings
    IS 'pgvector store for unstructured note text (spec §6 hybrid search). One row'
       ' per (source_table, source_id, source_column, model_name); derived data —'
       ' rebuildable from the source rows, so not audited.';
COMMENT ON COLUMN semantic_embeddings.source_table
    IS 'Name of the table the embedded text came from (e.g. physical_samples).';
COMMENT ON COLUMN semantic_embeddings.source_id
    IS 'Primary key (UUID) of the source row the embedded text belongs to.';
COMMENT ON COLUMN semantic_embeddings.source_column
    IS 'Name of the text column embedded (e.g. notes, outcome_notes).';
COMMENT ON COLUMN semantic_embeddings.content_text
    IS 'The exact text that was embedded; kept for re-ranking and display.';
COMMENT ON COLUMN semantic_embeddings.content_hash
    IS 'SHA-256 of content_text; lets the backfill skip unchanged rows.';
COMMENT ON COLUMN semantic_embeddings.embedding
    IS 'pgvector embedding (dimension 768, nomic-embed-text). Cosine distance.';
COMMENT ON COLUMN semantic_embeddings.model_name
    IS 'Embedding model that produced this vector; part of the uniqueness key.';

-- ---------------------------------------------------------------------------
-- v_embeddings_source_notes — every embeddable note in the schema, unified.
-- The embedder backfills from here; adding a new note column means adding one
-- UNION branch (and re-running the backfill), nothing else.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE VIEW v_embeddings_source_notes AS
SELECT
    'physical_samples'      AS source_table,
    ps.sample_id            AS source_id,
    'notes'                 AS source_column,
    ps.notes                AS content_text
FROM physical_samples AS ps
WHERE ps.notes IS NOT NULL AND length(trim(ps.notes)) > 0

UNION ALL

SELECT
    'manufacturing_operations'  AS source_table,
    mo.operation_id             AS source_id,
    'outcome_notes'             AS source_column,
    mo.outcome_notes            AS content_text
FROM manufacturing_operations AS mo
WHERE mo.outcome_notes IS NOT NULL AND length(trim(mo.outcome_notes)) > 0

UNION ALL

SELECT
    'test_sessions'     AS source_table,
    ts.session_id       AS source_id,
    'notes'             AS source_column,
    ts.notes            AS content_text
FROM test_sessions AS ts
WHERE ts.notes IS NOT NULL AND length(trim(ts.notes)) > 0

UNION ALL

SELECT
    'raw_stock_lots'    AS source_table,
    rsl.lot_id          AS source_id,
    'notes'             AS source_column,
    rsl.notes           AS content_text
FROM raw_stock_lots AS rsl
WHERE rsl.notes IS NOT NULL AND length(trim(rsl.notes)) > 0;

COMMENT ON VIEW v_embeddings_source_notes
    IS 'All embeddable free-text notes across the schema, one row each, as the'
       ' canonical backfill source for semantic_embeddings (spec §6).';

-- ---------------------------------------------------------------------------
-- d1_llm_readonly — read-only privilege bundle for the text-to-SQL layer.
-- NOLOGIN group role: the plugin's login user inherits it. Granted SELECT only
-- on the allow-listed views, never base tables. Read-only + statement-timeout
-- defaults bound any session that assumes it.
-- ---------------------------------------------------------------------------
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'd1_llm_readonly') THEN
        CREATE ROLE d1_llm_readonly NOLOGIN;
    END IF;
END
$$;

ALTER ROLE d1_llm_readonly SET default_transaction_read_only = on;
ALTER ROLE d1_llm_readonly SET statement_timeout = '5000ms';
ALTER ROLE d1_llm_readonly SET idle_in_transaction_session_timeout = '10000ms';

GRANT USAGE ON SCHEMA public TO d1_llm_readonly;

-- Allow-listed data views (the LLM's query surface).
GRANT SELECT ON
    v_complete_sample_history,
    v_tooling_hierarchy,
    v_sample_genealogy_flat,
    v_manufacturing_operations_full,
    v_stock_provenance,
    v_test_sessions_full,
    v_schema_dictionary,
    v_llm_query_targets
TO d1_llm_readonly;

-- semantic_embeddings is read by the plugin's own hybrid-search query (not by
-- LLM-authored SQL), so it is granted to the role but kept off the LLM menu.
GRANT SELECT ON semantic_embeddings TO d1_llm_readonly;

-- The traceability functions are SELECT-able lineage helpers.
GRANT EXECUTE ON FUNCTION
    f_trace_ancestors(UUID),
    f_trace_descendants(UUID),
    f_trace_stock_origins(UUID),
    f_sample_timeline(UUID)
TO d1_llm_readonly;

-- migrate:down

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'd1_llm_readonly') THEN
        -- Removes every privilege granted to the role in this database so the
        -- role can be dropped cleanly (CI verifies a clean rollback).
        EXECUTE 'DROP OWNED BY d1_llm_readonly';
        DROP ROLE d1_llm_readonly;
    END IF;
END
$$;

DROP VIEW IF EXISTS v_embeddings_source_notes;
DROP TABLE IF EXISTS semantic_embeddings;
DROP VIEW IF EXISTS v_llm_query_targets;
DROP VIEW IF EXISTS v_schema_dictionary;
