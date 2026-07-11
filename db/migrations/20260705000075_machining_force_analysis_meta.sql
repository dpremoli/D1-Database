-- migrate:up
-- Register machining_force_analysis in Directus: a (hidden) collection whose rows
-- are the force-dashboard's backing data, the three M2O relations (operation,
-- source file, FRM png), an O2M back-reference on manufacturing_operations, and
-- Lab Member read access. The custom d1-force-dashboard module reads this via the
-- items API; the crawler module reads/controls `status`.

-- The collection. Hidden from the nav (derived data surfaced through the op form
-- and the dashboard module), grouped under manufacturing for admin browsing.
INSERT INTO directus_collections (collection, icon, note, display_template, hidden, "group", sort)
VALUES ('machining_force_analysis', 'insights',
        'ABFPA force-analysis results per machining .mat (FRM, envelopes, spectra)',
        '{{operation_id}} — {{status}}', true, 'manufacturing_methods', 9)
ON CONFLICT (collection) DO NOTHING;

-- Field metadata (mostly read-only; the orchestrator writes rows directly in SQL).
INSERT INTO directus_fields (collection, field, interface, display, options, display_options, width, sort, special, readonly, hidden)
SELECT collection, field, interface, display, options::json, display_options::json, width, sort, special, readonly, hidden
FROM (VALUES
    ('machining_force_analysis', 'status', 'select-dropdown', 'labels',
        '{"choices":[{"text":"Pending","value":"pending"},{"text":"Processing","value":"processing"},{"text":"Done","value":"done"},{"text":"Error","value":"error"},{"text":"Skipped","value":"skipped"}]}',
        NULL, 'half', 1, NULL, false, false),
    ('machining_force_analysis', 'operation_id', 'select-dropdown-m2o', 'related-values',
        '{"template":"{{pass_code}}","enableCreate":false}', '{"template":"{{pass_code}}"}', 'half', 2, 'm2o', false, false),
    ('machining_force_analysis', 'directus_files_id', 'file', 'file', NULL, NULL, 'half', 3, 'file', false, false),
    ('machining_force_analysis', 'frm_file', 'file-image', 'image', NULL, NULL, 'half', 4, 'file', false, false),
    ('machining_force_analysis', 'error_message', 'input-multiline', 'raw', NULL, NULL, 'full', 5, NULL, true, false),
    ('machining_force_analysis', 'dyno_gain', 'input', 'raw', NULL, NULL, 'half', 6, NULL, true, false),
    ('machining_force_analysis', 'peak_fz', 'input', 'raw', NULL, NULL, 'half', 7, NULL, true, false),
    ('machining_force_analysis', 'mean_rpm', 'input', 'raw', NULL, NULL, 'half', 8, NULL, true, false),
    ('machining_force_analysis', 'processed_at', 'datetime', 'datetime', NULL, NULL, 'half', 9, NULL, true, false),
    ('machining_force_analysis', 'series', 'input-code', 'raw', NULL, NULL, 'full', 20, 'cast-json', true, true),
    ('machining_force_analysis', 'fft', 'input-code', 'raw', NULL, NULL, 'full', 21, 'cast-json', true, true)
) v(collection, field, interface, display, options, display_options, width, sort, special, readonly, hidden)
WHERE NOT EXISTS (
    SELECT 1 FROM directus_fields f WHERE f.collection = v.collection AND f.field = v.field
);

-- O2M back-reference on the operation form: "Force analyses".
INSERT INTO directus_fields (collection, field, interface, special, options, display, display_options, width, sort, hidden)
SELECT 'manufacturing_operations', 'force_analyses', 'list-o2m', 'o2m',
       '{"template":"{{status}} — {{peak_fz}} N","enableCreate":false,"enableSelect":false}',
       'related-values', '{"template":"{{status}}"}', 'full', 50, false
WHERE NOT EXISTS (
    SELECT 1 FROM directus_fields f
    WHERE f.collection = 'manufacturing_operations' AND f.field = 'force_analyses'
);

-- Relations: operation_id (M2O with O2M back-ref), source file, FRM png.
INSERT INTO directus_relations (many_collection, many_field, one_collection, one_field, one_deselect_action)
SELECT 'machining_force_analysis', 'operation_id', 'manufacturing_operations', 'force_analyses', 'delete'
WHERE NOT EXISTS (
    SELECT 1 FROM directus_relations r
    WHERE r.many_collection = 'machining_force_analysis' AND r.many_field = 'operation_id'
);

INSERT INTO directus_relations (many_collection, many_field, one_collection, one_deselect_action)
SELECT 'machining_force_analysis', 'directus_files_id', 'directus_files', 'nullify'
WHERE NOT EXISTS (
    SELECT 1 FROM directus_relations r
    WHERE r.many_collection = 'machining_force_analysis' AND r.many_field = 'directus_files_id'
);

INSERT INTO directus_relations (many_collection, many_field, one_collection, one_deselect_action)
SELECT 'machining_force_analysis', 'frm_file', 'directus_files', 'nullify'
WHERE NOT EXISTS (
    SELECT 1 FROM directus_relations r
    WHERE r.many_collection = 'machining_force_analysis' AND r.many_field = 'frm_file'
);

-- Lab Member: read-only (dashboard consumption). Lab Admin has admin_access.
INSERT INTO directus_permissions (policy, collection, action, permissions, validation, fields)
SELECT '20000002-0000-0000-0000-000000000002', 'machining_force_analysis', 'read', '{}', '{}', '*'
WHERE NOT EXISTS (
    SELECT 1 FROM directus_permissions p
    WHERE p.policy = '20000002-0000-0000-0000-000000000002'
      AND p.collection = 'machining_force_analysis' AND p.action = 'read'
);

-- migrate:down
DELETE FROM directus_permissions
    WHERE collection = 'machining_force_analysis'
      AND policy = '20000002-0000-0000-0000-000000000002';
DELETE FROM directus_relations WHERE many_collection = 'machining_force_analysis';
DELETE FROM directus_fields    WHERE collection = 'manufacturing_operations' AND field = 'force_analyses';
DELETE FROM directus_fields    WHERE collection = 'machining_force_analysis';
DELETE FROM directus_collections WHERE collection = 'machining_force_analysis';
