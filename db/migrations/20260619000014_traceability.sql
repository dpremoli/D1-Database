-- migrate:up
-- Phase 7 — cradle-to-grave traceability.
--
-- The front-end is deliberately deferred (Directus relational browsing over the
-- v_* views covers day-to-day navigation). What the system genuinely needs is a
-- durable, adapter-independent way to walk a sample's full lineage *forward*
-- (descendants → their operations and tests) and *backward* (ancestors →
-- originating raw stock) with no dead ends. That backbone lives in Postgres as
-- set-returning functions so Directus, ad-hoc SQL, and the future LLM all share
-- one correct implementation.
--
-- All functions are STABLE and side-effect free. Recursion is cycle-guarded with
-- a path array (sample_genealogy already forbids self-loops, but a longer cycle
-- introduced by bad data must not hang the query).

-- ---------------------------------------------------------------------------
-- f_trace_ancestors(sample) — walk child → parent to the roots.
-- Row at depth 0 is the sample itself; depth N is N hops up the genealogy.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION f_trace_ancestors(p_sample_id UUID)
    RETURNS TABLE (
        depth             INTEGER,
        sample_id         UUID,
        sample_code       TEXT,
        form              TEXT,
        relationship_type TEXT,
        fraction          NUMERIC,
        path              UUID []
    )
    LANGUAGE sql
    STABLE
AS $$
    WITH RECURSIVE up AS (
        SELECT
            0                       AS depth,
            ps.sample_id,
            ps.sample_code::TEXT    AS sample_code,
            ps.form,
            NULL::TEXT              AS relationship_type,
            NULL::NUMERIC           AS fraction,
            ARRAY[ps.sample_id]     AS path
        FROM physical_samples AS ps
        WHERE ps.sample_id = p_sample_id

        UNION ALL

        SELECT
            up.depth + 1,
            parent.sample_id,
            parent.sample_code::TEXT,
            parent.form,
            sg.relationship_type,
            sg.fraction,
            up.path || parent.sample_id
        FROM up
        INNER JOIN sample_genealogy AS sg ON sg.child_sample_id = up.sample_id
        INNER JOIN physical_samples AS parent
            ON parent.sample_id = sg.parent_sample_id
        WHERE NOT (parent.sample_id = ANY (up.path))
    )
    SELECT depth, sample_id, sample_code, form, relationship_type, fraction, path
    FROM up;
$$;

COMMENT ON FUNCTION f_trace_ancestors(UUID)
    IS 'Reverse traceability: every ancestor of a sample (depth 0 = the sample'
       ' itself), walking child→parent through sample_genealogy. Cycle-guarded.';

-- ---------------------------------------------------------------------------
-- f_trace_descendants(sample) — walk parent → child to the leaves.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION f_trace_descendants(p_sample_id UUID)
    RETURNS TABLE (
        depth             INTEGER,
        sample_id         UUID,
        sample_code       TEXT,
        form              TEXT,
        relationship_type TEXT,
        fraction          NUMERIC,
        path              UUID []
    )
    LANGUAGE sql
    STABLE
AS $$
    WITH RECURSIVE down AS (
        SELECT
            0                       AS depth,
            ps.sample_id,
            ps.sample_code::TEXT    AS sample_code,
            ps.form,
            NULL::TEXT              AS relationship_type,
            NULL::NUMERIC           AS fraction,
            ARRAY[ps.sample_id]     AS path
        FROM physical_samples AS ps
        WHERE ps.sample_id = p_sample_id

        UNION ALL

        SELECT
            down.depth + 1,
            child.sample_id,
            child.sample_code::TEXT,
            child.form,
            sg.relationship_type,
            sg.fraction,
            down.path || child.sample_id
        FROM down
        INNER JOIN sample_genealogy AS sg ON sg.parent_sample_id = down.sample_id
        INNER JOIN physical_samples AS child
            ON child.sample_id = sg.child_sample_id
        WHERE NOT (child.sample_id = ANY (down.path))
    )
    SELECT depth, sample_id, sample_code, form, relationship_type, fraction, path
    FROM down;
$$;

COMMENT ON FUNCTION f_trace_descendants(UUID)
    IS 'Forward traceability: every descendant of a sample (depth 0 = the sample'
       ' itself), walking parent→child through sample_genealogy. Cycle-guarded.';

-- ---------------------------------------------------------------------------
-- f_trace_stock_origins(sample) — the raw stock lots that fed this sample or
-- any of its ancestors. Closes the cradle end of the chain.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION f_trace_stock_origins(p_sample_id UUID)
    RETURNS TABLE (
        via_sample_id   UUID,
        via_sample_code TEXT,
        depth           INTEGER,
        lot_id          UUID,
        lot_code        TEXT,
        stock_type      TEXT,
        supplier_name   TEXT,
        mass_used_grams NUMERIC
    )
    LANGUAGE sql
    STABLE
AS $$
    SELECT
        a.sample_id          AS via_sample_id,
        a.sample_code        AS via_sample_code,
        a.depth,
        rsl.lot_id,
        rsl.lot_code::TEXT   AS lot_code,
        rsl.stock_type,
        rsl.supplier_name,
        ssp.mass_used_grams
    FROM f_trace_ancestors(p_sample_id) AS a
    INNER JOIN sample_stock_provenance AS ssp ON ssp.sample_id = a.sample_id
    INNER JOIN raw_stock_lots AS rsl ON rsl.lot_id = ssp.lot_id;
$$;

COMMENT ON FUNCTION f_trace_stock_origins(UUID)
    IS 'Full reverse traceability to raw material: every raw_stock_lot feeding a'
       ' sample or any of its ancestors, with the ancestor it entered through.';

-- ---------------------------------------------------------------------------
-- f_sample_timeline(sample) — unified chronological event stream for a sample:
-- manufacturing operations and test sessions interleaved by date.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION f_sample_timeline(p_sample_id UUID)
    RETURNS TABLE (
        event_date TIMESTAMPTZ,
        event_type TEXT,
        event_id   UUID,
        label      TEXT,
        detail     JSONB
    )
    LANGUAGE sql
    STABLE
AS $$
    SELECT
        mo.operation_date            AS event_date,
        'manufacturing_operation'    AS event_type,
        mo.operation_id              AS event_id,
        mo.pass_code::TEXT           AS label,
        jsonb_build_object(
            'method_id', mo.method_id,
            'sequence', mo.operation_sequence,
            'operator', mo.operator_name
        )                            AS detail
    FROM manufacturing_operations AS mo
    WHERE mo.sample_id = p_sample_id

    UNION ALL

    SELECT
        ts.session_date,
        'test_session',
        ts.session_id,
        ts.test_type,
        jsonb_build_object(
            'status', ts.status,
            'file_storage_pointer', ts.file_storage_pointer
        )
    FROM test_sessions AS ts
    WHERE ts.sample_id = p_sample_id

    ORDER BY event_date ASC NULLS LAST;
$$;

COMMENT ON FUNCTION f_sample_timeline(UUID)
    IS 'Chronological cradle-to-grave event stream (manufacturing operations +'
       ' test sessions) for a single sample, ordered by date.';

-- migrate:down

DROP FUNCTION IF EXISTS f_sample_timeline(UUID);
DROP FUNCTION IF EXISTS f_trace_stock_origins(UUID);
DROP FUNCTION IF EXISTS f_trace_descendants(UUID);
DROP FUNCTION IF EXISTS f_trace_ancestors(UUID);
