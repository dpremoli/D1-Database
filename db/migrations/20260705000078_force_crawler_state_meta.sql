-- migrate:up
-- Register force_crawler_state as a Directus singleton so the d1-force-crawler
-- admin module can read/write it via the items API.

INSERT INTO directus_collections (collection, icon, note, singleton, hidden, "group", sort)
VALUES ('force_crawler_state', 'dns', 'Force-crawler daemon control + live status (singleton)', true, true, 'manufacturing_methods', 10)
ON CONFLICT (collection) DO NOTHING;

INSERT INTO directus_fields (collection, field, interface, display, options, width, sort, readonly, hidden)
SELECT collection, field, interface, display, options::json, width, sort, readonly, hidden
FROM (VALUES
    ('force_crawler_state', 'desired_state',     'select-dropdown', 'labels', '{"choices":[{"text":"Running","value":"running"},{"text":"Paused","value":"paused"}]}', 'half', 1, false, false),
    ('force_crawler_state', 'workers',           'input',           'raw',    NULL, 'half', 2, false, false),
    ('force_crawler_state', 'throttle_seconds',  'input',           'raw',    NULL, 'half', 3, false, false),
    ('force_crawler_state', 'file_like',          'input',          'raw',    NULL, 'half', 4, false, false),
    ('force_crawler_state', 'op_code_like',       'input',          'raw',    NULL, 'half', 5, false, false),
    ('force_crawler_state', 'daemon_pid',         'input',          'raw',    NULL, 'half', 10, true, false),
    ('force_crawler_state', 'last_heartbeat_at',  'datetime',       'datetime', NULL, 'half', 11, true, false),
    ('force_crawler_state', 'current_activity',   'input',          'raw',    NULL, 'full', 12, true, false),
    ('force_crawler_state', 'processed_count',    'input',          'raw',    NULL, 'half', 13, true, false),
    ('force_crawler_state', 'error_count',        'input',          'raw',    NULL, 'half', 14, true, false)
) v(collection, field, interface, display, options, width, sort, readonly, hidden)
WHERE NOT EXISTS (
    SELECT 1 FROM directus_fields f WHERE f.collection = v.collection AND f.field = v.field
);

-- Lab Member: read-only (watch progress). Lab Admin has admin_access already.
INSERT INTO directus_permissions (policy, collection, action, permissions, validation, fields)
SELECT '20000002-0000-0000-0000-000000000002', 'force_crawler_state', 'read', '{}', '{}', '*'
WHERE NOT EXISTS (
    SELECT 1 FROM directus_permissions p
    WHERE p.policy = '20000002-0000-0000-0000-000000000002'
      AND p.collection = 'force_crawler_state' AND p.action = 'read'
);

-- migrate:down
DELETE FROM directus_permissions WHERE collection = 'force_crawler_state';
DELETE FROM directus_fields      WHERE collection = 'force_crawler_state';
DELETE FROM directus_collections WHERE collection = 'force_crawler_state';
