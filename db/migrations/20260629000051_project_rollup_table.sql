-- migrate:up
-- Directus can't surface a view that has no primary key, so we keep v_project_rollup
-- as the live source of truth and maintain a thin, read-only CACHE table (real PK) that
-- Directus can display. The cache is rebuilt by trigger whenever operations or campaigns
-- change, so it always reflects the live derivation (no hand-maintained denormalisation).
CREATE TABLE project_rollup (
    row_id      TEXT PRIMARY KEY,
    project_id  UUID,
    kind        TEXT,
    code        TEXT,
    detail      TEXT,
    campaign_id UUID
);
CREATE INDEX idx_project_rollup_project_id ON project_rollup (project_id);

CREATE OR REPLACE FUNCTION refresh_project_rollup() RETURNS void LANGUAGE plpgsql AS $$
BEGIN
    DELETE FROM project_rollup;
    INSERT INTO project_rollup (row_id, project_id, kind, code, detail, campaign_id)
    SELECT row_id, project_id, kind, code, detail, campaign_id FROM v_project_rollup;
END;
$$;

CREATE OR REPLACE FUNCTION trg_refresh_project_rollup() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    PERFORM refresh_project_rollup();
    RETURN NULL;
END;
$$;

CREATE TRIGGER refresh_rollup_ops
    AFTER INSERT OR UPDATE OR DELETE ON manufacturing_operations
    FOR EACH STATEMENT EXECUTE FUNCTION trg_refresh_project_rollup();
CREATE TRIGGER refresh_rollup_campaigns
    AFTER INSERT OR UPDATE OR DELETE ON campaigns
    FOR EACH STATEMENT EXECUTE FUNCTION trg_refresh_project_rollup();

SELECT refresh_project_rollup();

-- migrate:down
DROP TRIGGER IF EXISTS refresh_rollup_campaigns ON campaigns;
DROP TRIGGER IF EXISTS refresh_rollup_ops ON manufacturing_operations;
DROP FUNCTION IF EXISTS trg_refresh_project_rollup();
DROP FUNCTION IF EXISTS refresh_project_rollup();
DROP TABLE IF EXISTS project_rollup;
