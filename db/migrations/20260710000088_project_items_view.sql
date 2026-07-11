-- migrate:up
-- Replace the project form's separate read-only rollup table + the individual
-- (often-empty) related lists with ONE unified "Project items" presentation
-- interface (d1-project-items): it renders operations / samples / tests / equipment
-- / tools / insert boxes pulled from project_rollup, showing only non-empty
-- sections and tagging campaign-inherited items with a coloured campaign badge.

-- Add the presentation alias field (no DB column).
INSERT INTO directus_fields (collection, field, interface, special, options, width, sort, hidden, readonly)
SELECT 'projects', 'project_items', 'd1-project-items', 'alias,no-data', '{}'::json, 'full', 16, false, true
WHERE NOT EXISTS (SELECT 1 FROM directus_fields f WHERE f.collection='projects' AND f.field='project_items');

-- Hide the separate rollup list and the individual item lists (now covered by the
-- unified, hide-empty, tagged view). campaigns + secondary_investigators stay.
UPDATE directus_fields SET hidden = true
 WHERE collection = 'projects'
   AND field IN ('rollup', 'operations', 'samples', 'project_tools', 'insert_boxes', 'project_equipment', 'project_test_sessions');

-- migrate:down
UPDATE directus_fields SET hidden = false
 WHERE collection = 'projects'
   AND field IN ('rollup', 'operations', 'samples', 'project_tools', 'insert_boxes', 'project_equipment', 'project_test_sessions');
DELETE FROM directus_fields WHERE collection = 'projects' AND field = 'project_items';
