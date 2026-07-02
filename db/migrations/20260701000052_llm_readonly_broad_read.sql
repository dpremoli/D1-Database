-- migrate:up
-- Broaden the text-to-SQL read surface (ADR-0009 revisited).
--
-- The local LLM's read-only role may now SELECT all lab/domain data and benign
-- Directus metadata, so it can answer questions about any recorded field (e.g.
-- machining feed/speed on manufacturing_operations) — not just the curated v_*
-- views. It must still NEVER read credential- or auth-bearing tables. This is
-- the durable half of the boundary; the application SQL guard enforces the same
-- deny-list as defence-in-depth (see plugins/llm-text-to-sql/app/lib/sql_guard.py).

-- 1. Grant read on everything currently in public...
GRANT SELECT ON ALL TABLES IN SCHEMA public TO d1_llm_readonly;

-- 2. ...and on future tables the d1 owner creates, so new domain tables are
--    queryable without another grant migration. The guard still blocks any
--    future directus_* / sensitive table by name (deny-by-default there).
ALTER DEFAULT PRIVILEGES FOR ROLE d1 IN SCHEMA public
    GRANT SELECT ON TABLES TO d1_llm_readonly;

-- 3. Revoke the credential/secret tables and the auth model. Idempotent and
--    tolerant of tables absent in a given Directus version.
DO $$
DECLARE t text;
BEGIN
    FOREACH t IN ARRAY ARRAY[
        -- credentials / secrets
        'directus_users', 'directus_sessions', 'directus_settings',
        'directus_shares', 'directus_deployments',
        -- JSON config that can embed API keys/tokens
        'directus_flows', 'directus_operations',
        -- auth / permission model
        'directus_policies', 'directus_permissions', 'directus_access',
        'directus_roles',
        -- migration bookkeeping
        'schema_migrations'
    ] LOOP
        IF EXISTS (
            SELECT 1 FROM pg_tables WHERE schemaname = 'public' AND tablename = t
        ) THEN
            EXECUTE format('REVOKE SELECT ON public.%I FROM d1_llm_readonly', t);
        END IF;
    END LOOP;
END $$;

-- migrate:down
-- Restore the original narrow surface: the eight curated views + embeddings only.
REVOKE SELECT ON ALL TABLES IN SCHEMA public FROM d1_llm_readonly;
ALTER DEFAULT PRIVILEGES FOR ROLE d1 IN SCHEMA public
    REVOKE SELECT ON TABLES FROM d1_llm_readonly;
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
GRANT SELECT ON semantic_embeddings TO d1_llm_readonly;
