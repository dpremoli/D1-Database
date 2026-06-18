-- migrate:up
-- Immutable, append-only audit log. Captures INSERT / UPDATE / DELETE on all core
-- tables via a generic trigger. Implements ADR-0003 (trigger-based audit).
-- The actor identity is injected via SET LOCAL d1.actor_identity = '...' at
-- session start by the API layer (Directus flow or FastAPI middleware).

CREATE TABLE audit_logs (
    log_id          BIGSERIAL   NOT NULL,
    event_timestamp TIMESTAMPTZ NOT NULL DEFAULT now(),
    table_name      TEXT        NOT NULL,
    record_id       TEXT        NOT NULL,
    action_type     TEXT        NOT NULL,
    actor_identity  TEXT,
    row_before      JSONB,
    row_after       JSONB,
    changed_fields  JSONB,
    CONSTRAINT audit_logs_pkey PRIMARY KEY (log_id),
    CONSTRAINT audit_logs_action_type_check
        CHECK (action_type IN ('INSERT', 'UPDATE', 'DELETE'))
);

-- audit_logs is append-only; deny UPDATE and DELETE at the DB level.
-- noqa: disable=PRS
CREATE RULE audit_logs_no_update AS ON UPDATE TO audit_logs DO INSTEAD NOTHING;
CREATE RULE audit_logs_no_delete AS ON DELETE TO audit_logs DO INSTEAD NOTHING;
-- noqa: enable=PRS

COMMENT ON TABLE audit_logs
    IS 'Append-only immutable audit trail. Every INSERT/UPDATE/DELETE on a core table'
       ' produces one row here via the audit_trigger_function trigger.';
COMMENT ON COLUMN audit_logs.record_id
    IS 'Primary-key value of the affected row, cast to TEXT for portability.';
COMMENT ON COLUMN audit_logs.actor_identity
    IS 'User ID or machine-token identity, set via SET LOCAL d1.actor_identity.';
COMMENT ON COLUMN audit_logs.row_before
    IS 'Full row state before the mutation (NULL for INSERT).';
COMMENT ON COLUMN audit_logs.row_after
    IS 'Full row state after the mutation (NULL for DELETE).';
COMMENT ON COLUMN audit_logs.changed_fields
    IS 'For UPDATE: JSONB object keyed by column with {old, new} sub-objects.';

-- ---------------------------------------------------------------------------
-- Generic audit trigger function.
-- Reads actor identity from the session-local GUC d1.actor_identity.
-- record_id tries the most common PK column names in turn.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION audit_trigger_function()
    RETURNS TRIGGER
    LANGUAGE plpgsql
    SECURITY DEFINER
AS $$
DECLARE
    v_row_before    JSONB;
    v_row_after     JSONB;
    v_record_id     TEXT;
    v_changed       JSONB;
BEGIN
    IF TG_OP = 'DELETE' THEN
        v_row_before := to_jsonb(OLD);
        v_row_after  := NULL;
        v_record_id  := COALESCE(
            v_row_before ->> 'sample_id',
            v_row_before ->> 'operation_id',
            v_row_before ->> 'session_id',
            v_row_before ->> 'lot_id',
            v_row_before ->> 'material_id',
            v_row_before ->> 'project_id',
            v_row_before ->> 'tool_box_id',
            v_row_before ->> 'insert_id',
            v_row_before ->> 'edge_id',
            v_row_before ->> 'equipment_id',
            v_row_before ->> 'tool_id',
            v_row_before ->> 'insert_type_id',
            v_row_before ->> 'method_id',
            v_row_before ->> 'parameter_id',
            v_row_before ->> 'symbol',
            v_row_before ->> 'iso_code',
            'unknown'
        );
        v_changed := NULL;
    ELSIF TG_OP = 'INSERT' THEN
        v_row_before := NULL;
        v_row_after  := to_jsonb(NEW);
        v_record_id  := COALESCE(
            v_row_after ->> 'sample_id',
            v_row_after ->> 'operation_id',
            v_row_after ->> 'session_id',
            v_row_after ->> 'lot_id',
            v_row_after ->> 'material_id',
            v_row_after ->> 'project_id',
            v_row_after ->> 'tool_box_id',
            v_row_after ->> 'insert_id',
            v_row_after ->> 'edge_id',
            v_row_after ->> 'equipment_id',
            v_row_after ->> 'tool_id',
            v_row_after ->> 'insert_type_id',
            v_row_after ->> 'method_id',
            v_row_after ->> 'parameter_id',
            v_row_after ->> 'symbol',
            v_row_after ->> 'iso_code',
            'unknown'
        );
        v_changed := NULL;
    ELSE
        -- UPDATE
        v_row_before := to_jsonb(OLD);
        v_row_after  := to_jsonb(NEW);
        v_record_id  := COALESCE(
            v_row_after ->> 'sample_id',
            v_row_after ->> 'operation_id',
            v_row_after ->> 'session_id',
            v_row_after ->> 'lot_id',
            v_row_after ->> 'material_id',
            v_row_after ->> 'project_id',
            v_row_after ->> 'tool_box_id',
            v_row_after ->> 'insert_id',
            v_row_after ->> 'edge_id',
            v_row_after ->> 'equipment_id',
            v_row_after ->> 'tool_id',
            v_row_after ->> 'insert_type_id',
            v_row_after ->> 'method_id',
            v_row_after ->> 'parameter_id',
            v_row_after ->> 'symbol',
            v_row_after ->> 'iso_code',
            'unknown'
        );
        SELECT jsonb_object_agg(
            k,
            jsonb_build_object('old', v_row_before -> k, 'new', v_row_after -> k)
        )
        INTO v_changed
        FROM jsonb_each(v_row_after) AS t (k, v)
        WHERE (v_row_before -> k) IS DISTINCT FROM (v_row_after -> k);
    END IF;

    INSERT INTO audit_logs (
        table_name,
        record_id,
        action_type,
        actor_identity,
        row_before,
        row_after,
        changed_fields
    ) VALUES (
        TG_TABLE_NAME,
        v_record_id,
        TG_OP,
        current_setting('d1.actor_identity', TRUE),
        v_row_before,
        v_row_after,
        v_changed
    );

    RETURN NEW;
END;
$$;

-- ---------------------------------------------------------------------------
-- Attach audit triggers to all core mutable tables.
-- ---------------------------------------------------------------------------
CREATE TRIGGER audit_physical_samples
    AFTER INSERT OR UPDATE OR DELETE ON physical_samples
    FOR EACH ROW EXECUTE FUNCTION audit_trigger_function();

CREATE TRIGGER audit_manufacturing_operations
    AFTER INSERT OR UPDATE OR DELETE ON manufacturing_operations
    FOR EACH ROW EXECUTE FUNCTION audit_trigger_function();

CREATE TRIGGER audit_test_sessions
    AFTER INSERT OR UPDATE OR DELETE ON test_sessions
    FOR EACH ROW EXECUTE FUNCTION audit_trigger_function();

CREATE TRIGGER audit_raw_stock_lots
    AFTER INSERT OR UPDATE OR DELETE ON raw_stock_lots
    FOR EACH ROW EXECUTE FUNCTION audit_trigger_function();

CREATE TRIGGER audit_tool_boxes
    AFTER INSERT OR UPDATE OR DELETE ON tool_boxes
    FOR EACH ROW EXECUTE FUNCTION audit_trigger_function();

CREATE TRIGGER audit_cutting_inserts
    AFTER INSERT OR UPDATE OR DELETE ON cutting_inserts
    FOR EACH ROW EXECUTE FUNCTION audit_trigger_function();

CREATE TRIGGER audit_insert_edges
    AFTER INSERT OR UPDATE OR DELETE ON insert_edges
    FOR EACH ROW EXECUTE FUNCTION audit_trigger_function();

CREATE TRIGGER audit_projects
    AFTER INSERT OR UPDATE OR DELETE ON projects
    FOR EACH ROW EXECUTE FUNCTION audit_trigger_function();

-- migrate:down

DROP TRIGGER IF EXISTS audit_projects ON projects;
DROP TRIGGER IF EXISTS audit_insert_edges ON insert_edges;
DROP TRIGGER IF EXISTS audit_cutting_inserts ON cutting_inserts;
DROP TRIGGER IF EXISTS audit_tool_boxes ON tool_boxes;
DROP TRIGGER IF EXISTS audit_raw_stock_lots ON raw_stock_lots;
DROP TRIGGER IF EXISTS audit_test_sessions ON test_sessions;
DROP TRIGGER IF EXISTS audit_manufacturing_operations ON manufacturing_operations;
DROP TRIGGER IF EXISTS audit_physical_samples ON physical_samples;
DROP FUNCTION IF EXISTS audit_trigger_function();
DROP RULE IF EXISTS audit_logs_no_delete ON audit_logs;
DROP RULE IF EXISTS audit_logs_no_update ON audit_logs;
DROP TABLE IF EXISTS audit_logs CASCADE;
