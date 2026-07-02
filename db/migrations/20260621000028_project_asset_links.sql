-- migrate:up
-- Add direct project_id FK to equipment, tools, and tool_boxes so assets can
-- be assigned to a primary project. Reverse lookup (which projects used a given
-- machine / edge) flows naturally through manufacturing_operations.project_id
-- via Directus O2M back-links and the node graph.

ALTER TABLE equipment
    ADD COLUMN IF NOT EXISTS project_id UUID
        REFERENCES projects(project_id) ON DELETE SET NULL;

ALTER TABLE tools
    ADD COLUMN IF NOT EXISTS project_id UUID
        REFERENCES projects(project_id) ON DELETE SET NULL;

ALTER TABLE tool_boxes
    ADD COLUMN IF NOT EXISTS project_id UUID
        REFERENCES projects(project_id) ON DELETE SET NULL;

-- migrate:down
ALTER TABLE tool_boxes  DROP COLUMN IF EXISTS project_id;
ALTER TABLE tools       DROP COLUMN IF EXISTS project_id;
ALTER TABLE equipment   DROP COLUMN IF EXISTS project_id;
