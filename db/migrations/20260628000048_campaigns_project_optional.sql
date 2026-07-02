-- migrate:up
-- A campaign may exist without a project (grouping is useful before a project is
-- assigned). Drop NOT NULL on project_id and relax the FK to SET NULL.
ALTER TABLE campaigns ALTER COLUMN project_id DROP NOT NULL;
ALTER TABLE campaigns DROP CONSTRAINT IF EXISTS campaigns_project_id_fkey;
ALTER TABLE campaigns
    ADD CONSTRAINT campaigns_project_id_fkey
    FOREIGN KEY (project_id) REFERENCES projects(project_id) ON DELETE SET NULL;

-- migrate:down
ALTER TABLE campaigns DROP CONSTRAINT IF EXISTS campaigns_project_id_fkey;
ALTER TABLE campaigns
    ADD CONSTRAINT campaigns_project_id_fkey
    FOREIGN KEY (project_id) REFERENCES projects(project_id) ON DELETE CASCADE;
-- (project_id left nullable on down; re-adding NOT NULL would fail if null rows exist.)
