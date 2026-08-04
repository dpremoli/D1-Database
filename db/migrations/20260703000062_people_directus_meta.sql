-- migrate:up
-- ① People unification, step 3 of 3: Directus metadata. Registers the people
-- collection, wires the new owner/operator/PI person pickers to people, and hides
-- the old backup columns (owner UUID→users, operator INT→Machine_Operators, PI).
-- The researcher junctions (project_investigators, sample_co_owners) keep their
-- user_id M2M for now; their backfilled person_id column is hidden.



-- People collection ----------------------------------------------------------
INSERT INTO directus_collections (collection, icon, note, display_template, hidden, sort)
VALUES ('people', 'groups', 'Everyone attributed on records — operators, researchers, owners', '{{full_name}}', false, 3)
ON CONFLICT (collection) DO NOTHING;

-- Idempotent: clear then insert people's own field metadata.
DELETE FROM directus_fields WHERE collection='people';
INSERT INTO directus_fields (collection, field, special, interface, options, display, readonly, hidden, sort, width, required, note) VALUES ('people', 'full_name', NULL, 'input', NULL, 'raw', FALSE, FALSE, 1, 'full', TRUE, NULL);
INSERT INTO directus_fields (collection, field, special, interface, options, display, readonly, hidden, sort, width, required, note) VALUES ('people', 'email', NULL, 'input', NULL, 'raw', FALSE, FALSE, 2, 'half', FALSE, NULL);
INSERT INTO directus_fields (collection, field, special, interface, options, display, readonly, hidden, sort, width, required, note) VALUES ('people', 'user_id', 'm2o', 'select-dropdown-m2o', '{"template":"{{first_name}} {{last_name}}","enableCreate":false}', 'related-values', FALSE, FALSE, 3, 'half', FALSE, 'Linked app login (optional — operators need not have one)');
INSERT INTO directus_fields (collection, field, special, interface, options, display, readonly, hidden, sort, width, required, note) VALUES ('people', 'is_operator', 'cast-boolean', 'boolean', NULL, 'boolean', FALSE, FALSE, 4, 'half', FALSE, NULL);
INSERT INTO directus_fields (collection, field, special, interface, options, display, readonly, hidden, sort, width, required, note) VALUES ('people', 'is_researcher', 'cast-boolean', 'boolean', NULL, 'boolean', FALSE, FALSE, 5, 'half', FALSE, NULL);
INSERT INTO directus_fields (collection, field, special, interface, options, display, readonly, hidden, sort, width, required, note) VALUES ('people', 'active', 'cast-boolean', 'boolean', NULL, 'boolean', FALSE, FALSE, 6, 'half', FALSE, NULL);
INSERT INTO directus_fields (collection, field, special, interface, options, display, readonly, hidden, sort, width, required, note) VALUES ('people', 'notes', NULL, 'input-multiline', NULL, 'raw', FALSE, FALSE, 7, 'full', FALSE, NULL);
INSERT INTO directus_fields (collection, field, hidden, readonly, sort, note) VALUES ('people', 'legacy_machine_operator_id', TRUE, TRUE, 90, 'Legacy Machine_Operators.id (provenance).');

-- people.user_id → directus_users relation
INSERT INTO directus_relations (many_collection, many_field, one_collection, one_deselect_action)
SELECT 'people','user_id','directus_users','nullify'
WHERE NOT EXISTS (SELECT 1 FROM directus_relations r WHERE r.many_collection='people' AND r.many_field='user_id');

-- New person pickers (owner / operator / PI) ---------------------------------
DELETE FROM directus_fields WHERE field IN ('owner_person_id','operator_person_id','principal_investigator_person');
INSERT INTO directus_fields (collection, field, special, interface, options, display, display_options, readonly, hidden, sort, width, required, translations) VALUES ('physical_samples', 'owner_person_id', 'm2o', 'select-dropdown-m2o', '{"template":"{{full_name}}","enableCreate":true}', 'related-values', '{"template":"{{full_name}}"}', FALSE, FALSE, 8, 'half', FALSE, '[{"language": "en-US", "translation": "Owner"}]');
INSERT INTO directus_relations (many_collection, many_field, one_collection, one_deselect_action) SELECT 'physical_samples','owner_person_id','people','nullify' WHERE NOT EXISTS (SELECT 1 FROM directus_relations r WHERE r.many_collection='physical_samples' AND r.many_field='owner_person_id');
INSERT INTO directus_fields (collection, field, special, interface, options, display, display_options, readonly, hidden, sort, width, required, translations) VALUES ('manufacturing_operations', 'owner_person_id', 'm2o', 'select-dropdown-m2o', '{"template":"{{full_name}}","enableCreate":true}', 'related-values', '{"template":"{{full_name}}"}', FALSE, FALSE, 8, 'half', FALSE, '[{"language": "en-US", "translation": "Owner"}]');
INSERT INTO directus_relations (many_collection, many_field, one_collection, one_deselect_action) SELECT 'manufacturing_operations','owner_person_id','people','nullify' WHERE NOT EXISTS (SELECT 1 FROM directus_relations r WHERE r.many_collection='manufacturing_operations' AND r.many_field='owner_person_id');
INSERT INTO directus_fields (collection, field, special, interface, options, display, display_options, readonly, hidden, sort, width, required, translations) VALUES ('test_sessions', 'owner_person_id', 'm2o', 'select-dropdown-m2o', '{"template":"{{full_name}}","enableCreate":true}', 'related-values', '{"template":"{{full_name}}"}', FALSE, FALSE, 8, 'half', FALSE, '[{"language": "en-US", "translation": "Owner"}]');
INSERT INTO directus_relations (many_collection, many_field, one_collection, one_deselect_action) SELECT 'test_sessions','owner_person_id','people','nullify' WHERE NOT EXISTS (SELECT 1 FROM directus_relations r WHERE r.many_collection='test_sessions' AND r.many_field='owner_person_id');
INSERT INTO directus_fields (collection, field, special, interface, options, display, display_options, readonly, hidden, sort, width, required, translations) VALUES ('campaigns', 'owner_person_id', 'm2o', 'select-dropdown-m2o', '{"template":"{{full_name}}","enableCreate":true}', 'related-values', '{"template":"{{full_name}}"}', FALSE, FALSE, 8, 'half', FALSE, '[{"language": "en-US", "translation": "Owner"}]');
INSERT INTO directus_relations (many_collection, many_field, one_collection, one_deselect_action) SELECT 'campaigns','owner_person_id','people','nullify' WHERE NOT EXISTS (SELECT 1 FROM directus_relations r WHERE r.many_collection='campaigns' AND r.many_field='owner_person_id');
INSERT INTO directus_fields (collection, field, special, interface, options, display, display_options, readonly, hidden, sort, width, required, translations) VALUES ('etchants', 'owner_person_id', 'm2o', 'select-dropdown-m2o', '{"template":"{{full_name}}","enableCreate":true}', 'related-values', '{"template":"{{full_name}}"}', FALSE, FALSE, 8, 'half', FALSE, '[{"language": "en-US", "translation": "Owner"}]');
INSERT INTO directus_relations (many_collection, many_field, one_collection, one_deselect_action) SELECT 'etchants','owner_person_id','people','nullify' WHERE NOT EXISTS (SELECT 1 FROM directus_relations r WHERE r.many_collection='etchants' AND r.many_field='owner_person_id');
INSERT INTO directus_fields (collection, field, special, interface, options, display, display_options, readonly, hidden, sort, width, required, translations) VALUES ('prep_recipes', 'owner_person_id', 'm2o', 'select-dropdown-m2o', '{"template":"{{full_name}}","enableCreate":true}', 'related-values', '{"template":"{{full_name}}"}', FALSE, FALSE, 8, 'half', FALSE, '[{"language": "en-US", "translation": "Owner"}]');
INSERT INTO directus_relations (many_collection, many_field, one_collection, one_deselect_action) SELECT 'prep_recipes','owner_person_id','people','nullify' WHERE NOT EXISTS (SELECT 1 FROM directus_relations r WHERE r.many_collection='prep_recipes' AND r.many_field='owner_person_id');
INSERT INTO directus_fields (collection, field, special, interface, options, display, display_options, readonly, hidden, sort, width, required, translations) VALUES ('tool_boxes', 'owner_person_id', 'm2o', 'select-dropdown-m2o', '{"template":"{{full_name}}","enableCreate":true}', 'related-values', '{"template":"{{full_name}}"}', FALSE, FALSE, 8, 'half', FALSE, '[{"language": "en-US", "translation": "Owner"}]');
INSERT INTO directus_relations (many_collection, many_field, one_collection, one_deselect_action) SELECT 'tool_boxes','owner_person_id','people','nullify' WHERE NOT EXISTS (SELECT 1 FROM directus_relations r WHERE r.many_collection='tool_boxes' AND r.many_field='owner_person_id');
INSERT INTO directus_fields (collection, field, special, interface, options, display, display_options, readonly, hidden, sort, width, required, translations) VALUES ('cutting_inserts', 'owner_person_id', 'm2o', 'select-dropdown-m2o', '{"template":"{{full_name}}","enableCreate":true}', 'related-values', '{"template":"{{full_name}}"}', FALSE, FALSE, 8, 'half', FALSE, '[{"language": "en-US", "translation": "Owner"}]');
INSERT INTO directus_relations (many_collection, many_field, one_collection, one_deselect_action) SELECT 'cutting_inserts','owner_person_id','people','nullify' WHERE NOT EXISTS (SELECT 1 FROM directus_relations r WHERE r.many_collection='cutting_inserts' AND r.many_field='owner_person_id');
INSERT INTO directus_fields (collection, field, special, interface, options, display, display_options, readonly, hidden, sort, width, required, translations) VALUES ('insert_edges', 'owner_person_id', 'm2o', 'select-dropdown-m2o', '{"template":"{{full_name}}","enableCreate":true}', 'related-values', '{"template":"{{full_name}}"}', FALSE, FALSE, 8, 'half', FALSE, '[{"language": "en-US", "translation": "Owner"}]');
INSERT INTO directus_relations (many_collection, many_field, one_collection, one_deselect_action) SELECT 'insert_edges','owner_person_id','people','nullify' WHERE NOT EXISTS (SELECT 1 FROM directus_relations r WHERE r.many_collection='insert_edges' AND r.many_field='owner_person_id');
INSERT INTO directus_fields (collection, field, special, interface, options, display, display_options, readonly, hidden, sort, width, required, translations) VALUES ('manufacturing_operations', 'operator_person_id', 'm2o', 'select-dropdown-m2o', '{"template":"{{full_name}}","enableCreate":true}', 'related-values', '{"template":"{{full_name}}"}', FALSE, FALSE, 9, 'half', FALSE, '[{"language": "en-US", "translation": "Operator"}]');
INSERT INTO directus_relations (many_collection, many_field, one_collection, one_deselect_action) SELECT 'manufacturing_operations','operator_person_id','people','nullify' WHERE NOT EXISTS (SELECT 1 FROM directus_relations r WHERE r.many_collection='manufacturing_operations' AND r.many_field='operator_person_id');
INSERT INTO directus_fields (collection, field, special, interface, options, display, display_options, readonly, hidden, sort, width, required, translations) VALUES ('test_sessions', 'operator_person_id', 'm2o', 'select-dropdown-m2o', '{"template":"{{full_name}}","enableCreate":true}', 'related-values', '{"template":"{{full_name}}"}', FALSE, FALSE, 9, 'half', FALSE, '[{"language": "en-US", "translation": "Operator"}]');
INSERT INTO directus_relations (many_collection, many_field, one_collection, one_deselect_action) SELECT 'test_sessions','operator_person_id','people','nullify' WHERE NOT EXISTS (SELECT 1 FROM directus_relations r WHERE r.many_collection='test_sessions' AND r.many_field='operator_person_id');
INSERT INTO directus_fields (collection, field, special, interface, options, display, display_options, readonly, hidden, sort, width, required, translations) VALUES ('projects', 'principal_investigator_person', 'm2o', 'select-dropdown-m2o', '{"template":"{{full_name}}","enableCreate":true}', 'related-values', '{"template":"{{full_name}}"}', FALSE, FALSE, 8, 'half', FALSE, '[{"language": "en-US", "translation": "Principal Investigator"}]');
INSERT INTO directus_relations (many_collection, many_field, one_collection, one_deselect_action) SELECT 'projects','principal_investigator_person','people','nullify' WHERE NOT EXISTS (SELECT 1 FROM directus_relations r WHERE r.many_collection='projects' AND r.many_field='principal_investigator_person');

-- Hide the old backup fields so users pick people, not users/operators --------
UPDATE directus_fields SET hidden = TRUE WHERE (collection, field) IN (('physical_samples','owner'),('manufacturing_operations','owner'),('test_sessions','owner'),('campaigns','owner'),('etchants','owner'),('prep_recipes','owner'),('tool_boxes','owner'),('cutting_inserts','owner'),('insert_edges','owner'));
UPDATE directus_fields SET hidden = TRUE WHERE (collection, field) IN (('manufacturing_operations','operator'),('test_sessions','operator'),('projects','principal_investigator'));
INSERT INTO directus_fields (collection, field, hidden, readonly, note) VALUES ('project_investigators','person_id',TRUE,TRUE,'Backfilled people link; M2M UI uses user_id.') ON CONFLICT DO NOTHING;
INSERT INTO directus_fields (collection, field, hidden, readonly, note) VALUES ('sample_co_owners','person_id',TRUE,TRUE,'Backfilled people link; M2M UI uses user_id.') ON CONFLICT DO NOTHING;



-- migrate:down

DELETE FROM directus_relations WHERE many_field IN ('owner_person_id','operator_person_id','principal_investigator_person') OR (many_collection='people' AND many_field='user_id');
DELETE FROM directus_fields WHERE field IN ('owner_person_id','operator_person_id','principal_investigator_person');
DELETE FROM directus_fields WHERE collection='people';
DELETE FROM directus_collections WHERE collection='people';
UPDATE directus_fields SET hidden = FALSE WHERE (collection, field) IN (('physical_samples','owner'),('manufacturing_operations','owner'),('test_sessions','owner'),('campaigns','owner'),('etchants','owner'),('prep_recipes','owner'),('tool_boxes','owner'),('cutting_inserts','owner'),('insert_edges','owner'));
UPDATE directus_fields SET hidden = FALSE WHERE (collection, field) IN (('manufacturing_operations','operator'),('test_sessions','operator'),('projects','principal_investigator'));
DELETE FROM directus_fields WHERE (collection,field) IN (('project_investigators','person_id'),('sample_co_owners','person_id'));

