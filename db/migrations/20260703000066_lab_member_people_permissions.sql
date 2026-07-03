-- migrate:up
-- Grant Lab Member (app_access, no admin) access to the collections introduced by
-- the lab-data-model refactors. Lab Admin has admin_access so needs nothing here.
--   people                 — manage + resolve owner/operator M2O pickers
--   facilities             — read (machine picker + equipment display)
--   test_sessions_subject  — the test → subject (M2A) junction, written when a test
--                            is created
-- Mirrors the full-CRUD, fields='*' shape used for physical_samples.

INSERT INTO directus_permissions (policy, collection, action, permissions, validation, fields)
SELECT '20000002-0000-0000-0000-000000000002', c.collection, a.action, '{}', '{}', '*'
FROM (VALUES
    ('people'),
    ('test_sessions_subject')
) c(collection)
CROSS JOIN (VALUES ('create'), ('read'), ('update'), ('delete')) a(action)
WHERE NOT EXISTS (
    SELECT 1 FROM directus_permissions p
    WHERE p.policy = '20000002-0000-0000-0000-000000000002'
      AND p.collection = c.collection AND p.action = a.action
);

INSERT INTO directus_permissions (policy, collection, action, permissions, validation, fields)
SELECT '20000002-0000-0000-0000-000000000002', 'facilities', 'read', '{}', '{}', '*'
WHERE NOT EXISTS (
    SELECT 1 FROM directus_permissions p
    WHERE p.policy = '20000002-0000-0000-0000-000000000002'
      AND p.collection = 'facilities' AND p.action = 'read'
);

-- migrate:down
DELETE FROM directus_permissions
WHERE policy = '20000002-0000-0000-0000-000000000002'
  AND collection IN ('people', 'test_sessions_subject', 'facilities');
