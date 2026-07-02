-- migrate:up
-- Campaigns: an optional grouping layer between a project and its children.
-- One table with a discriminator: a machining_trial groups manufacturing_operations,
-- a testing_campaign groups test_sessions. A campaign always belongs to a project and
-- can carry defaults (owner, equipment, material) that its children inherit on create.

CREATE TABLE campaigns (
    campaign_id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    project_id           UUID NOT NULL REFERENCES projects(project_id) ON DELETE CASCADE,
    campaign_type        TEXT NOT NULL
        CHECK (campaign_type IN ('machining_trial', 'testing_campaign')),
    campaign_code        TEXT,
    name                 TEXT NOT NULL,
    owner                UUID REFERENCES directus_users(id) ON DELETE SET NULL,
    default_equipment_id UUID REFERENCES equipment(equipment_id) ON DELETE SET NULL,
    default_material_id  UUID REFERENCES materials(material_id) ON DELETE SET NULL,
    start_date           DATE,
    end_date             DATE,
    status               TEXT,
    notes                TEXT,
    created_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    version              INTEGER     NOT NULL DEFAULT 1
);

COMMENT ON TABLE campaigns
    IS 'Optional grouping under a project: machining trial (operations) or testing campaign (sessions).';

-- Optional child membership (a child may still live directly under a project).
ALTER TABLE manufacturing_operations
    ADD COLUMN campaign_id UUID REFERENCES campaigns(campaign_id) ON DELETE SET NULL;
ALTER TABLE test_sessions
    ADD COLUMN campaign_id UUID REFERENCES campaigns(campaign_id) ON DELETE SET NULL;

CREATE INDEX idx_campaigns_project_id          ON campaigns (project_id);
CREATE INDEX idx_campaigns_campaign_type       ON campaigns (campaign_type);
CREATE INDEX idx_mfg_ops_campaign_id           ON manufacturing_operations (campaign_id);
CREATE INDEX idx_test_sessions_campaign_id     ON test_sessions (campaign_id);

-- OCC: bump version + updated_at on every UPDATE (reuses the shared function).
CREATE TRIGGER occ_campaigns
    BEFORE UPDATE ON campaigns
    FOR EACH ROW EXECUTE FUNCTION occ_update_trigger_function();

-- Teach the shared audit function about campaign_id so audit rows resolve to the
-- campaign's own id (not its project_id). Supersedes the body in 20260618000009_audit.sql.
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
            v_row_before ->> 'campaign_id',
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
            v_row_after ->> 'campaign_id',
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
        v_row_before := to_jsonb(OLD);
        v_row_after  := to_jsonb(NEW);
        v_record_id  := COALESCE(
            v_row_after ->> 'sample_id',
            v_row_after ->> 'operation_id',
            v_row_after ->> 'session_id',
            v_row_after ->> 'campaign_id',
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
        table_name, record_id, action_type, actor_identity,
        row_before, row_after, changed_fields
    ) VALUES (
        TG_TABLE_NAME, v_record_id, TG_OP,
        current_setting('d1.actor_identity', TRUE),
        v_row_before, v_row_after, v_changed
    );

    RETURN NEW;
END;
$$;

CREATE TRIGGER audit_campaigns
    AFTER INSERT OR UPDATE OR DELETE ON campaigns
    FOR EACH ROW EXECUTE FUNCTION audit_trigger_function();

-- migrate:down
DROP TRIGGER IF EXISTS audit_campaigns ON campaigns;
DROP TRIGGER IF EXISTS occ_campaigns ON campaigns;
ALTER TABLE test_sessions DROP COLUMN IF EXISTS campaign_id;
ALTER TABLE manufacturing_operations DROP COLUMN IF EXISTS campaign_id;
DROP TABLE IF EXISTS campaigns;
-- Note: audit_trigger_function keeps the (backward-compatible) campaign_id line; no revert needed.
