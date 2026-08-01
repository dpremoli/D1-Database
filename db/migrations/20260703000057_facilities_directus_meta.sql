-- migrate:up
-- Register the facilities collection + the equipment.facility_id M2O in Directus
-- metadata, mirroring the manufacturers M2O. This makes facilities a proper
-- collection, renders facility_id as a dropdown on equipment, and lets the machine
-- picker resolve the nested facility_id.name for its tiered facility filter.

INSERT INTO directus_collections (collection, icon, note, display_template, hidden, "group", sort)
VALUES ('facilities', 'apartment', 'Labs / centres that house equipment', '{{name}}', false, 'manufacturing_methods', 2)
ON CONFLICT (collection) DO NOTHING;

-- Nice field metadata for the facilities collection itself.
INSERT INTO directus_fields (collection, field, interface, display, width, sort, special)
SELECT * FROM (VALUES
    ('facilities', 'name',  'input',                'raw', 'full', 1, NULL),
    ('facilities', 'code',  'input',                'raw', 'half', 2, NULL),
    ('facilities', 'notes', 'input-multiline',      'raw', 'full', 3, NULL)
) v(collection, field, interface, display, width, sort, special)
WHERE NOT EXISTS (
    SELECT 1 FROM directus_fields f WHERE f.collection = v.collection AND f.field = v.field
);

-- equipment.facility_id -> M2O dropdown on facilities.
INSERT INTO directus_fields (collection, field, special, interface, options, display, display_options, hidden, sort, width)
SELECT 'equipment', 'facility_id', 'm2o', 'select-dropdown-m2o',
       '{"template":"{{name}}","enableCreate":false}', 'related-values', '{"template":"{{name}}"}',
       false, 6, 'half'
WHERE NOT EXISTS (
    SELECT 1 FROM directus_fields f WHERE f.collection = 'equipment' AND f.field = 'facility_id'
);

-- The M2O relation itself.
INSERT INTO directus_relations (many_collection, many_field, one_collection, one_deselect_action)
SELECT 'equipment', 'facility_id', 'facilities', 'nullify'
WHERE NOT EXISTS (
    SELECT 1 FROM directus_relations r WHERE r.many_collection = 'equipment' AND r.many_field = 'facility_id'
);

-- migrate:down
DELETE FROM directus_relations WHERE many_collection = 'equipment' AND many_field = 'facility_id';
DELETE FROM directus_fields    WHERE collection = 'equipment' AND field = 'facility_id';
DELETE FROM directus_fields    WHERE collection = 'facilities';
DELETE FROM directus_collections WHERE collection = 'facilities';
