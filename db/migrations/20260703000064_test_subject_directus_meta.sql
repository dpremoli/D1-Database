-- migrate:up
-- ③ Testable subject, step 2 of 2: Directus M2A metadata. Registers the junction,
-- the two relation legs (parent + polymorphic item), the `subject` alias field on
-- test_sessions, and hides the old sample_id / insert_edge_id fields.



-- Junction collection (hidden system collection).
INSERT INTO directus_collections (collection, icon, hidden, note)
VALUES ('test_sessions_subject', 'import_export', true, 'M2A junction: test -> subject (physical_samples | insert_edges).')
ON CONFLICT (collection) DO NOTHING;

DELETE FROM directus_fields WHERE collection='test_sessions_subject';
INSERT INTO directus_fields (collection, field, special, interface, hidden, readonly, sort) VALUES
    ('test_sessions_subject', 'id',               'uuid', 'input', true, true, 1),
    ('test_sessions_subject', 'test_sessions_id', NULL,   'input', true, true, 2),
    ('test_sessions_subject', 'item',             NULL,   'input', true, true, 3),
    ('test_sessions_subject', 'collection',       NULL,   'input', true, true, 4);

-- Relation leg 1: junction -> parent test_sessions (drives the `subject` field).
INSERT INTO directus_relations (many_collection, many_field, one_collection, one_field, junction_field, one_deselect_action)
SELECT 'test_sessions_subject', 'test_sessions_id', 'test_sessions', 'subject', 'item', 'delete'
WHERE NOT EXISTS (SELECT 1 FROM directus_relations r WHERE r.many_collection='test_sessions_subject' AND r.many_field='test_sessions_id');

-- Relation leg 2: junction.item -> any of the allowed collections (polymorphic).
INSERT INTO directus_relations (many_collection, many_field, one_collection, one_allowed_collections, one_collection_field, junction_field, one_deselect_action)
SELECT 'test_sessions_subject', 'item', NULL, 'physical_samples,insert_edges', 'collection', 'test_sessions_id', 'nullify'
WHERE NOT EXISTS (SELECT 1 FROM directus_relations r WHERE r.many_collection='test_sessions_subject' AND r.many_field='item');

-- The `subject` alias field on test_sessions (the browsable M2A picker).
DELETE FROM directus_fields WHERE collection='test_sessions' AND field='subject';
INSERT INTO directus_fields (collection, field, special, interface, options, display, hidden, sort, width, translations)
VALUES ('test_sessions', 'subject', 'm2a', 'list-m2a', '{"enableCreate":false,"enableSelect":true}', 'related-values', false, 4, 'full',
        '[{"language":"en-US","translation":"Subject (sample or edge)"}]');

-- Hide the old single-target fields (kept as backup columns).
UPDATE directus_fields SET hidden = TRUE WHERE collection='test_sessions' AND field IN ('sample_id','insert_edge_id');



-- migrate:down

UPDATE directus_fields SET hidden = FALSE WHERE collection='test_sessions' AND field IN ('sample_id','insert_edge_id');
DELETE FROM directus_fields WHERE collection='test_sessions' AND field='subject';
DELETE FROM directus_relations WHERE many_collection='test_sessions_subject';
DELETE FROM directus_fields WHERE collection='test_sessions_subject';
DELETE FROM directus_collections WHERE collection='test_sessions_subject';

