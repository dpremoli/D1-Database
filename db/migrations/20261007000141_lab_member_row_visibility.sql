-- migrate:up
-- ADR-0011 (row-level visibility), step 2: put the row filters on the Lab Member policy.
--
-- Until now Lab Member could read and change every sample, operation, test, campaign and project.
-- Owner decisions of 2026-10-07 (docs/adr/0011-row-level-visibility.md): strict enforcement through
-- Directus permission filters (so the Data Studio and the API are restricted, not only the Explorer
-- pages); read follows involvement (owner, co-owner, PI or investigator, campaign owner); update is
-- limited to owners and co-owners; delete to the owner (the PI for projects); create stays open.
-- Child rows follow their parent. Reference data stays unfiltered.
--
-- The filters below are generated from scripts/access_rules.json by
-- `python3 scripts/gen_access_rules.py --values` and embedded here, because a migration is a
-- snapshot of the rules on the day it was written. scripts/configure_users_and_policies.sql carries
-- the same rows (it deletes and re-inserts the policy's rows on every run). tests/phase1_schema.sh
-- fails when the stored permissions differ from the generator's output, so a rule change needs
-- a new migration that pastes the regenerated rows.
--
-- What the rows do, per collection (see the ADR for the exact rules):
--   * UPDATE of an existing Lab Member row sets its `permissions` filter; other columns are kept.
--   * INSERT of a missing row: campaigns, campaign_samples, project_investigators, project_rollup
--     and the three data-file junctions were never granted by this repo's scripts (a deployment may
--     have granted them by hand and then the UPDATE covers them), and a fresh database (CI) has no
--     Lab Member rows for the rest, since only configure_users_and_policies.sql creates them.
--   * Rows of other collections, and of other policies, are not touched.
--
-- Also here:
--   * Indexes on the columns the filters join through (owner, project, user ids). The junction
--     and FK columns the rules also use (campaign_samples, test_sessions.sample_id and campaign_id,
--     manufacturing_operations.campaign_id, sample_genealogy, *_data_files, people.user_id) are
--     indexed by earlier migrations.
--   * The hidden Directus alias projects.samples (an O2M over physical_samples.project_id): the
--     project read rule says "owns or co-owns a sample in it" and a filter needs an alias to
--     traverse. Directus reads relations at start-up: restart it, or clear its cache, to pick it up.
--   * A NOTICE with how many records have no owner. They stay visible only through their project,
--     campaign or co-owners until someone assigns an owner (scripts/transfer_sample_ownership.py).

-- 1. Indexes behind the filters.
CREATE INDEX IF NOT EXISTS idx_physical_samples_owner_person_id ON physical_samples (owner_person_id);
CREATE INDEX IF NOT EXISTS idx_physical_samples_project_id ON physical_samples (project_id);
CREATE INDEX IF NOT EXISTS idx_manufacturing_operations_owner_person_id ON manufacturing_operations (owner_person_id);
CREATE INDEX IF NOT EXISTS idx_manufacturing_operations_project_id ON manufacturing_operations (project_id);
CREATE INDEX IF NOT EXISTS idx_test_sessions_owner_person_id ON test_sessions (owner_person_id);
CREATE INDEX IF NOT EXISTS idx_test_sessions_project_id ON test_sessions (project_id);
CREATE INDEX IF NOT EXISTS idx_campaigns_owner_person_id ON campaigns (owner_person_id);
CREATE INDEX IF NOT EXISTS idx_projects_principal_investigator_person ON projects (principal_investigator_person);
CREATE INDEX IF NOT EXISTS idx_project_investigators_user_id ON project_investigators (user_id);
CREATE INDEX IF NOT EXISTS idx_sample_co_owners_user_id ON sample_co_owners (user_id);

-- 2. The hidden alias projects.samples.
UPDATE directus_relations
SET one_field = 'samples'
WHERE many_collection = 'physical_samples' AND many_field = 'project_id'
  AND one_collection = 'projects' AND one_field IS NULL;

INSERT INTO directus_fields (collection, field, special, interface, options, display, readonly, hidden, sort, width, note)
SELECT 'projects', 'samples', 'o2m', 'list-o2m', '{"enableCreate":false,"enableSelect":false}', 'related-values',
       TRUE, TRUE, 23, 'full',
       'Hidden alias over physical_samples.project_id, used by the Lab Member row filters (ADR-0011).'
WHERE NOT EXISTS (
    SELECT 1 FROM directus_fields WHERE collection = 'projects' AND field = 'samples'
);

-- 3. The Lab Member rows, from scripts/access_rules.json.
CREATE TEMPORARY TABLE lab_member_rules (
    collection  TEXT NOT NULL,
    action      TEXT NOT NULL,
    permissions JSON NOT NULL
);

INSERT INTO lab_member_rules (collection, action, permissions) VALUES
    ('physical_samples', 'create', '{}'),
    ('physical_samples', 'read', '{"_or":[{"owner_person_id":{"user_id":{"_eq":"$CURRENT_USER"}}},{"co_owners":{"_some":{"user_id":{"_eq":"$CURRENT_USER"}}}},{"project_id":{"principal_investigator_person":{"user_id":{"_eq":"$CURRENT_USER"}}}},{"project_id":{"secondary_investigators":{"_some":{"user_id":{"_eq":"$CURRENT_USER"}}}}},{"campaigns":{"_some":{"campaign_id":{"owner_person_id":{"user_id":{"_eq":"$CURRENT_USER"}}}}}}]}'),
    ('physical_samples', 'update', '{"_or":[{"owner_person_id":{"user_id":{"_eq":"$CURRENT_USER"}}},{"co_owners":{"_some":{"user_id":{"_eq":"$CURRENT_USER"}}}}]}'),
    ('physical_samples', 'delete', '{"owner_person_id":{"user_id":{"_eq":"$CURRENT_USER"}}}'),
    ('manufacturing_operations', 'create', '{}'),
    ('manufacturing_operations', 'read', '{"_or":[{"owner_person_id":{"user_id":{"_eq":"$CURRENT_USER"}}},{"sample_id":{"owner_person_id":{"user_id":{"_eq":"$CURRENT_USER"}}}},{"sample_id":{"co_owners":{"_some":{"user_id":{"_eq":"$CURRENT_USER"}}}}},{"sample_id":{"project_id":{"principal_investigator_person":{"user_id":{"_eq":"$CURRENT_USER"}}}}},{"sample_id":{"project_id":{"secondary_investigators":{"_some":{"user_id":{"_eq":"$CURRENT_USER"}}}}}},{"sample_id":{"campaigns":{"_some":{"campaign_id":{"owner_person_id":{"user_id":{"_eq":"$CURRENT_USER"}}}}}}},{"project_id":{"principal_investigator_person":{"user_id":{"_eq":"$CURRENT_USER"}}}},{"project_id":{"secondary_investigators":{"_some":{"user_id":{"_eq":"$CURRENT_USER"}}}}},{"campaign_id":{"owner_person_id":{"user_id":{"_eq":"$CURRENT_USER"}}}}]}'),
    ('manufacturing_operations', 'update', '{"_or":[{"owner_person_id":{"user_id":{"_eq":"$CURRENT_USER"}}},{"sample_id":{"owner_person_id":{"user_id":{"_eq":"$CURRENT_USER"}}}},{"sample_id":{"co_owners":{"_some":{"user_id":{"_eq":"$CURRENT_USER"}}}}}]}'),
    ('manufacturing_operations', 'delete', '{"owner_person_id":{"user_id":{"_eq":"$CURRENT_USER"}}}'),
    ('test_sessions', 'create', '{}'),
    ('test_sessions', 'read', '{"_or":[{"owner_person_id":{"user_id":{"_eq":"$CURRENT_USER"}}},{"sample_id":{"owner_person_id":{"user_id":{"_eq":"$CURRENT_USER"}}}},{"sample_id":{"co_owners":{"_some":{"user_id":{"_eq":"$CURRENT_USER"}}}}},{"sample_id":{"project_id":{"principal_investigator_person":{"user_id":{"_eq":"$CURRENT_USER"}}}}},{"sample_id":{"project_id":{"secondary_investigators":{"_some":{"user_id":{"_eq":"$CURRENT_USER"}}}}}},{"sample_id":{"campaigns":{"_some":{"campaign_id":{"owner_person_id":{"user_id":{"_eq":"$CURRENT_USER"}}}}}}},{"project_id":{"principal_investigator_person":{"user_id":{"_eq":"$CURRENT_USER"}}}},{"project_id":{"secondary_investigators":{"_some":{"user_id":{"_eq":"$CURRENT_USER"}}}}},{"campaign_id":{"owner_person_id":{"user_id":{"_eq":"$CURRENT_USER"}}}}]}'),
    ('test_sessions', 'update', '{"_or":[{"owner_person_id":{"user_id":{"_eq":"$CURRENT_USER"}}},{"sample_id":{"owner_person_id":{"user_id":{"_eq":"$CURRENT_USER"}}}},{"sample_id":{"co_owners":{"_some":{"user_id":{"_eq":"$CURRENT_USER"}}}}}]}'),
    ('test_sessions', 'delete', '{"owner_person_id":{"user_id":{"_eq":"$CURRENT_USER"}}}'),
    ('campaigns', 'create', '{}'),
    ('campaigns', 'read', '{"_or":[{"owner_person_id":{"user_id":{"_eq":"$CURRENT_USER"}}},{"project_id":{"principal_investigator_person":{"user_id":{"_eq":"$CURRENT_USER"}}}},{"project_id":{"secondary_investigators":{"_some":{"user_id":{"_eq":"$CURRENT_USER"}}}}},{"samples":{"_some":{"sample_id":{"owner_person_id":{"user_id":{"_eq":"$CURRENT_USER"}}}}}},{"samples":{"_some":{"sample_id":{"co_owners":{"_some":{"user_id":{"_eq":"$CURRENT_USER"}}}}}}}]}'),
    ('campaigns', 'update', '{"owner_person_id":{"user_id":{"_eq":"$CURRENT_USER"}}}'),
    ('campaigns', 'delete', '{"owner_person_id":{"user_id":{"_eq":"$CURRENT_USER"}}}'),
    ('projects', 'create', '{}'),
    ('projects', 'read', '{"_or":[{"principal_investigator_person":{"user_id":{"_eq":"$CURRENT_USER"}}},{"secondary_investigators":{"_some":{"user_id":{"_eq":"$CURRENT_USER"}}}},{"campaigns":{"_some":{"owner_person_id":{"user_id":{"_eq":"$CURRENT_USER"}}}}},{"samples":{"_some":{"owner_person_id":{"user_id":{"_eq":"$CURRENT_USER"}}}}},{"samples":{"_some":{"co_owners":{"_some":{"user_id":{"_eq":"$CURRENT_USER"}}}}}}]}'),
    ('projects', 'update', '{"principal_investigator_person":{"user_id":{"_eq":"$CURRENT_USER"}}}'),
    ('projects', 'delete', '{"principal_investigator_person":{"user_id":{"_eq":"$CURRENT_USER"}}}'),
    ('sample_co_owners', 'create', '{}'),
    ('sample_co_owners', 'read', '{"_or":[{"sample_id":{"owner_person_id":{"user_id":{"_eq":"$CURRENT_USER"}}}},{"sample_id":{"co_owners":{"_some":{"user_id":{"_eq":"$CURRENT_USER"}}}}},{"sample_id":{"project_id":{"principal_investigator_person":{"user_id":{"_eq":"$CURRENT_USER"}}}}},{"sample_id":{"project_id":{"secondary_investigators":{"_some":{"user_id":{"_eq":"$CURRENT_USER"}}}}}},{"sample_id":{"campaigns":{"_some":{"campaign_id":{"owner_person_id":{"user_id":{"_eq":"$CURRENT_USER"}}}}}}}]}'),
    ('sample_co_owners', 'update', '{"_or":[{"sample_id":{"owner_person_id":{"user_id":{"_eq":"$CURRENT_USER"}}}},{"sample_id":{"co_owners":{"_some":{"user_id":{"_eq":"$CURRENT_USER"}}}}}]}'),
    ('sample_co_owners', 'delete', '{"_or":[{"sample_id":{"owner_person_id":{"user_id":{"_eq":"$CURRENT_USER"}}}},{"sample_id":{"co_owners":{"_some":{"user_id":{"_eq":"$CURRENT_USER"}}}}}]}'),
    ('sample_stock_provenance', 'create', '{}'),
    ('sample_stock_provenance', 'read', '{"_or":[{"sample_id":{"owner_person_id":{"user_id":{"_eq":"$CURRENT_USER"}}}},{"sample_id":{"co_owners":{"_some":{"user_id":{"_eq":"$CURRENT_USER"}}}}},{"sample_id":{"project_id":{"principal_investigator_person":{"user_id":{"_eq":"$CURRENT_USER"}}}}},{"sample_id":{"project_id":{"secondary_investigators":{"_some":{"user_id":{"_eq":"$CURRENT_USER"}}}}}},{"sample_id":{"campaigns":{"_some":{"campaign_id":{"owner_person_id":{"user_id":{"_eq":"$CURRENT_USER"}}}}}}}]}'),
    ('sample_stock_provenance', 'update', '{"_or":[{"sample_id":{"owner_person_id":{"user_id":{"_eq":"$CURRENT_USER"}}}},{"sample_id":{"co_owners":{"_some":{"user_id":{"_eq":"$CURRENT_USER"}}}}}]}'),
    ('sample_stock_provenance', 'delete', '{"_or":[{"sample_id":{"owner_person_id":{"user_id":{"_eq":"$CURRENT_USER"}}}},{"sample_id":{"co_owners":{"_some":{"user_id":{"_eq":"$CURRENT_USER"}}}}}]}'),
    ('sample_data_files', 'create', '{}'),
    ('sample_data_files', 'read', '{"_or":[{"sample_id":{"owner_person_id":{"user_id":{"_eq":"$CURRENT_USER"}}}},{"sample_id":{"co_owners":{"_some":{"user_id":{"_eq":"$CURRENT_USER"}}}}},{"sample_id":{"project_id":{"principal_investigator_person":{"user_id":{"_eq":"$CURRENT_USER"}}}}},{"sample_id":{"project_id":{"secondary_investigators":{"_some":{"user_id":{"_eq":"$CURRENT_USER"}}}}}},{"sample_id":{"campaigns":{"_some":{"campaign_id":{"owner_person_id":{"user_id":{"_eq":"$CURRENT_USER"}}}}}}}]}'),
    ('sample_data_files', 'update', '{"_or":[{"sample_id":{"owner_person_id":{"user_id":{"_eq":"$CURRENT_USER"}}}},{"sample_id":{"co_owners":{"_some":{"user_id":{"_eq":"$CURRENT_USER"}}}}}]}'),
    ('sample_data_files', 'delete', '{"_or":[{"sample_id":{"owner_person_id":{"user_id":{"_eq":"$CURRENT_USER"}}}},{"sample_id":{"co_owners":{"_some":{"user_id":{"_eq":"$CURRENT_USER"}}}}}]}'),
    ('sample_genealogy', 'create', '{}'),
    ('sample_genealogy', 'read', '{"_or":[{"child_sample_id":{"owner_person_id":{"user_id":{"_eq":"$CURRENT_USER"}}}},{"child_sample_id":{"co_owners":{"_some":{"user_id":{"_eq":"$CURRENT_USER"}}}}},{"child_sample_id":{"project_id":{"principal_investigator_person":{"user_id":{"_eq":"$CURRENT_USER"}}}}},{"child_sample_id":{"project_id":{"secondary_investigators":{"_some":{"user_id":{"_eq":"$CURRENT_USER"}}}}}},{"child_sample_id":{"campaigns":{"_some":{"campaign_id":{"owner_person_id":{"user_id":{"_eq":"$CURRENT_USER"}}}}}}},{"parent_sample_id":{"owner_person_id":{"user_id":{"_eq":"$CURRENT_USER"}}}},{"parent_sample_id":{"co_owners":{"_some":{"user_id":{"_eq":"$CURRENT_USER"}}}}},{"parent_sample_id":{"project_id":{"principal_investigator_person":{"user_id":{"_eq":"$CURRENT_USER"}}}}},{"parent_sample_id":{"project_id":{"secondary_investigators":{"_some":{"user_id":{"_eq":"$CURRENT_USER"}}}}}},{"parent_sample_id":{"campaigns":{"_some":{"campaign_id":{"owner_person_id":{"user_id":{"_eq":"$CURRENT_USER"}}}}}}}]}'),
    ('sample_genealogy', 'update', '{"_or":[{"child_sample_id":{"owner_person_id":{"user_id":{"_eq":"$CURRENT_USER"}}}},{"child_sample_id":{"co_owners":{"_some":{"user_id":{"_eq":"$CURRENT_USER"}}}}}]}'),
    ('sample_genealogy', 'delete', '{"_or":[{"child_sample_id":{"owner_person_id":{"user_id":{"_eq":"$CURRENT_USER"}}}},{"child_sample_id":{"co_owners":{"_some":{"user_id":{"_eq":"$CURRENT_USER"}}}}}]}'),
    ('campaign_samples', 'create', '{}'),
    ('campaign_samples', 'read', '{"_or":[{"campaign_id":{"owner_person_id":{"user_id":{"_eq":"$CURRENT_USER"}}}},{"campaign_id":{"project_id":{"principal_investigator_person":{"user_id":{"_eq":"$CURRENT_USER"}}}}},{"campaign_id":{"project_id":{"secondary_investigators":{"_some":{"user_id":{"_eq":"$CURRENT_USER"}}}}}},{"campaign_id":{"samples":{"_some":{"sample_id":{"owner_person_id":{"user_id":{"_eq":"$CURRENT_USER"}}}}}}},{"campaign_id":{"samples":{"_some":{"sample_id":{"co_owners":{"_some":{"user_id":{"_eq":"$CURRENT_USER"}}}}}}}},{"sample_id":{"owner_person_id":{"user_id":{"_eq":"$CURRENT_USER"}}}},{"sample_id":{"co_owners":{"_some":{"user_id":{"_eq":"$CURRENT_USER"}}}}},{"sample_id":{"project_id":{"principal_investigator_person":{"user_id":{"_eq":"$CURRENT_USER"}}}}},{"sample_id":{"project_id":{"secondary_investigators":{"_some":{"user_id":{"_eq":"$CURRENT_USER"}}}}}},{"sample_id":{"campaigns":{"_some":{"campaign_id":{"owner_person_id":{"user_id":{"_eq":"$CURRENT_USER"}}}}}}}]}'),
    ('campaign_samples', 'update', '{"_or":[{"campaign_id":{"owner_person_id":{"user_id":{"_eq":"$CURRENT_USER"}}}},{"sample_id":{"owner_person_id":{"user_id":{"_eq":"$CURRENT_USER"}}}},{"sample_id":{"co_owners":{"_some":{"user_id":{"_eq":"$CURRENT_USER"}}}}}]}'),
    ('campaign_samples', 'delete', '{"_or":[{"campaign_id":{"owner_person_id":{"user_id":{"_eq":"$CURRENT_USER"}}}},{"sample_id":{"owner_person_id":{"user_id":{"_eq":"$CURRENT_USER"}}}},{"sample_id":{"co_owners":{"_some":{"user_id":{"_eq":"$CURRENT_USER"}}}}}]}'),
    ('operation_data_files', 'create', '{}'),
    ('operation_data_files', 'read', '{"_or":[{"operation_id":{"owner_person_id":{"user_id":{"_eq":"$CURRENT_USER"}}}},{"operation_id":{"sample_id":{"owner_person_id":{"user_id":{"_eq":"$CURRENT_USER"}}}}},{"operation_id":{"sample_id":{"co_owners":{"_some":{"user_id":{"_eq":"$CURRENT_USER"}}}}}},{"operation_id":{"sample_id":{"project_id":{"principal_investigator_person":{"user_id":{"_eq":"$CURRENT_USER"}}}}}},{"operation_id":{"sample_id":{"project_id":{"secondary_investigators":{"_some":{"user_id":{"_eq":"$CURRENT_USER"}}}}}}},{"operation_id":{"sample_id":{"campaigns":{"_some":{"campaign_id":{"owner_person_id":{"user_id":{"_eq":"$CURRENT_USER"}}}}}}}},{"operation_id":{"project_id":{"principal_investigator_person":{"user_id":{"_eq":"$CURRENT_USER"}}}}},{"operation_id":{"project_id":{"secondary_investigators":{"_some":{"user_id":{"_eq":"$CURRENT_USER"}}}}}},{"operation_id":{"campaign_id":{"owner_person_id":{"user_id":{"_eq":"$CURRENT_USER"}}}}}]}'),
    ('operation_data_files', 'update', '{"_or":[{"operation_id":{"owner_person_id":{"user_id":{"_eq":"$CURRENT_USER"}}}},{"operation_id":{"sample_id":{"owner_person_id":{"user_id":{"_eq":"$CURRENT_USER"}}}}},{"operation_id":{"sample_id":{"co_owners":{"_some":{"user_id":{"_eq":"$CURRENT_USER"}}}}}}]}'),
    ('operation_data_files', 'delete', '{"_or":[{"operation_id":{"owner_person_id":{"user_id":{"_eq":"$CURRENT_USER"}}}},{"operation_id":{"sample_id":{"owner_person_id":{"user_id":{"_eq":"$CURRENT_USER"}}}}},{"operation_id":{"sample_id":{"co_owners":{"_some":{"user_id":{"_eq":"$CURRENT_USER"}}}}}}]}'),
    ('machining_force_analysis', 'create', '{}'),
    ('machining_force_analysis', 'read', '{"_or":[{"operation_id":{"owner_person_id":{"user_id":{"_eq":"$CURRENT_USER"}}}},{"operation_id":{"sample_id":{"owner_person_id":{"user_id":{"_eq":"$CURRENT_USER"}}}}},{"operation_id":{"sample_id":{"co_owners":{"_some":{"user_id":{"_eq":"$CURRENT_USER"}}}}}},{"operation_id":{"sample_id":{"project_id":{"principal_investigator_person":{"user_id":{"_eq":"$CURRENT_USER"}}}}}},{"operation_id":{"sample_id":{"project_id":{"secondary_investigators":{"_some":{"user_id":{"_eq":"$CURRENT_USER"}}}}}}},{"operation_id":{"sample_id":{"campaigns":{"_some":{"campaign_id":{"owner_person_id":{"user_id":{"_eq":"$CURRENT_USER"}}}}}}}},{"operation_id":{"project_id":{"principal_investigator_person":{"user_id":{"_eq":"$CURRENT_USER"}}}}},{"operation_id":{"project_id":{"secondary_investigators":{"_some":{"user_id":{"_eq":"$CURRENT_USER"}}}}}},{"operation_id":{"campaign_id":{"owner_person_id":{"user_id":{"_eq":"$CURRENT_USER"}}}}}]}'),
    ('machining_force_analysis', 'update', '{"_or":[{"operation_id":{"owner_person_id":{"user_id":{"_eq":"$CURRENT_USER"}}}},{"operation_id":{"sample_id":{"owner_person_id":{"user_id":{"_eq":"$CURRENT_USER"}}}}},{"operation_id":{"sample_id":{"co_owners":{"_some":{"user_id":{"_eq":"$CURRENT_USER"}}}}}}]}'),
    ('fast_run_data', 'read', '{"_or":[{"operation_id":{"owner_person_id":{"user_id":{"_eq":"$CURRENT_USER"}}}},{"operation_id":{"sample_id":{"owner_person_id":{"user_id":{"_eq":"$CURRENT_USER"}}}}},{"operation_id":{"sample_id":{"co_owners":{"_some":{"user_id":{"_eq":"$CURRENT_USER"}}}}}},{"operation_id":{"sample_id":{"project_id":{"principal_investigator_person":{"user_id":{"_eq":"$CURRENT_USER"}}}}}},{"operation_id":{"sample_id":{"project_id":{"secondary_investigators":{"_some":{"user_id":{"_eq":"$CURRENT_USER"}}}}}}},{"operation_id":{"sample_id":{"campaigns":{"_some":{"campaign_id":{"owner_person_id":{"user_id":{"_eq":"$CURRENT_USER"}}}}}}}},{"operation_id":{"project_id":{"principal_investigator_person":{"user_id":{"_eq":"$CURRENT_USER"}}}}},{"operation_id":{"project_id":{"secondary_investigators":{"_some":{"user_id":{"_eq":"$CURRENT_USER"}}}}}},{"operation_id":{"campaign_id":{"owner_person_id":{"user_id":{"_eq":"$CURRENT_USER"}}}}}]}'),
    ('session_data_files', 'create', '{}'),
    ('session_data_files', 'read', '{"_or":[{"session_id":{"owner_person_id":{"user_id":{"_eq":"$CURRENT_USER"}}}},{"session_id":{"sample_id":{"owner_person_id":{"user_id":{"_eq":"$CURRENT_USER"}}}}},{"session_id":{"sample_id":{"co_owners":{"_some":{"user_id":{"_eq":"$CURRENT_USER"}}}}}},{"session_id":{"sample_id":{"project_id":{"principal_investigator_person":{"user_id":{"_eq":"$CURRENT_USER"}}}}}},{"session_id":{"sample_id":{"project_id":{"secondary_investigators":{"_some":{"user_id":{"_eq":"$CURRENT_USER"}}}}}}},{"session_id":{"sample_id":{"campaigns":{"_some":{"campaign_id":{"owner_person_id":{"user_id":{"_eq":"$CURRENT_USER"}}}}}}}},{"session_id":{"project_id":{"principal_investigator_person":{"user_id":{"_eq":"$CURRENT_USER"}}}}},{"session_id":{"project_id":{"secondary_investigators":{"_some":{"user_id":{"_eq":"$CURRENT_USER"}}}}}},{"session_id":{"campaign_id":{"owner_person_id":{"user_id":{"_eq":"$CURRENT_USER"}}}}}]}'),
    ('session_data_files', 'update', '{"_or":[{"session_id":{"owner_person_id":{"user_id":{"_eq":"$CURRENT_USER"}}}},{"session_id":{"sample_id":{"owner_person_id":{"user_id":{"_eq":"$CURRENT_USER"}}}}},{"session_id":{"sample_id":{"co_owners":{"_some":{"user_id":{"_eq":"$CURRENT_USER"}}}}}}]}'),
    ('session_data_files', 'delete', '{"_or":[{"session_id":{"owner_person_id":{"user_id":{"_eq":"$CURRENT_USER"}}}},{"session_id":{"sample_id":{"owner_person_id":{"user_id":{"_eq":"$CURRENT_USER"}}}}},{"session_id":{"sample_id":{"co_owners":{"_some":{"user_id":{"_eq":"$CURRENT_USER"}}}}}}]}'),
    ('test_sessions_subject', 'create', '{}'),
    ('test_sessions_subject', 'read', '{"_or":[{"test_sessions_id":{"owner_person_id":{"user_id":{"_eq":"$CURRENT_USER"}}}},{"test_sessions_id":{"sample_id":{"owner_person_id":{"user_id":{"_eq":"$CURRENT_USER"}}}}},{"test_sessions_id":{"sample_id":{"co_owners":{"_some":{"user_id":{"_eq":"$CURRENT_USER"}}}}}},{"test_sessions_id":{"sample_id":{"project_id":{"principal_investigator_person":{"user_id":{"_eq":"$CURRENT_USER"}}}}}},{"test_sessions_id":{"sample_id":{"project_id":{"secondary_investigators":{"_some":{"user_id":{"_eq":"$CURRENT_USER"}}}}}}},{"test_sessions_id":{"sample_id":{"campaigns":{"_some":{"campaign_id":{"owner_person_id":{"user_id":{"_eq":"$CURRENT_USER"}}}}}}}},{"test_sessions_id":{"project_id":{"principal_investigator_person":{"user_id":{"_eq":"$CURRENT_USER"}}}}},{"test_sessions_id":{"project_id":{"secondary_investigators":{"_some":{"user_id":{"_eq":"$CURRENT_USER"}}}}}},{"test_sessions_id":{"campaign_id":{"owner_person_id":{"user_id":{"_eq":"$CURRENT_USER"}}}}}]}'),
    ('test_sessions_subject', 'update', '{"_or":[{"test_sessions_id":{"owner_person_id":{"user_id":{"_eq":"$CURRENT_USER"}}}},{"test_sessions_id":{"sample_id":{"owner_person_id":{"user_id":{"_eq":"$CURRENT_USER"}}}}},{"test_sessions_id":{"sample_id":{"co_owners":{"_some":{"user_id":{"_eq":"$CURRENT_USER"}}}}}}]}'),
    ('test_sessions_subject', 'delete', '{"_or":[{"test_sessions_id":{"owner_person_id":{"user_id":{"_eq":"$CURRENT_USER"}}}},{"test_sessions_id":{"sample_id":{"owner_person_id":{"user_id":{"_eq":"$CURRENT_USER"}}}}},{"test_sessions_id":{"sample_id":{"co_owners":{"_some":{"user_id":{"_eq":"$CURRENT_USER"}}}}}}]}'),
    ('project_investigators', 'create', '{}'),
    ('project_investigators', 'read', '{"_or":[{"project_id":{"principal_investigator_person":{"user_id":{"_eq":"$CURRENT_USER"}}}},{"project_id":{"secondary_investigators":{"_some":{"user_id":{"_eq":"$CURRENT_USER"}}}}},{"project_id":{"campaigns":{"_some":{"owner_person_id":{"user_id":{"_eq":"$CURRENT_USER"}}}}}},{"project_id":{"samples":{"_some":{"owner_person_id":{"user_id":{"_eq":"$CURRENT_USER"}}}}}},{"project_id":{"samples":{"_some":{"co_owners":{"_some":{"user_id":{"_eq":"$CURRENT_USER"}}}}}}}]}'),
    ('project_investigators', 'update', '{"project_id":{"principal_investigator_person":{"user_id":{"_eq":"$CURRENT_USER"}}}}'),
    ('project_investigators', 'delete', '{"project_id":{"principal_investigator_person":{"user_id":{"_eq":"$CURRENT_USER"}}}}'),
    ('project_rollup', 'read', '{"_or":[{"project_id":{"principal_investigator_person":{"user_id":{"_eq":"$CURRENT_USER"}}}},{"project_id":{"secondary_investigators":{"_some":{"user_id":{"_eq":"$CURRENT_USER"}}}}}]}');

UPDATE directus_permissions AS p
SET permissions = r.permissions
FROM lab_member_rules AS r
WHERE p.policy = '20000002-0000-0000-0000-000000000002'
  AND p.collection = r.collection
  AND p.action = r.action;

INSERT INTO directus_permissions (policy, collection, action, permissions, validation, fields)
SELECT '20000002-0000-0000-0000-000000000002', r.collection, r.action, r.permissions, '{}', '*'
FROM lab_member_rules AS r
WHERE NOT EXISTS (
    SELECT 1 FROM directus_permissions AS p
    WHERE p.policy = '20000002-0000-0000-0000-000000000002'
      AND p.collection = r.collection AND p.action = r.action
);

DROP TABLE lab_member_rules;

-- 4. Records nobody owns.
DO $$
DECLARE
    v_samples    BIGINT;
    v_operations BIGINT;
    v_tests      BIGINT;
    v_campaigns  BIGINT;
    v_projects   BIGINT;
BEGIN
    SELECT count(*) INTO v_samples FROM physical_samples WHERE owner_person_id IS NULL;
    SELECT count(*) INTO v_operations FROM manufacturing_operations WHERE owner_person_id IS NULL;
    SELECT count(*) INTO v_tests FROM test_sessions WHERE owner_person_id IS NULL;
    SELECT count(*) INTO v_campaigns FROM campaigns WHERE owner_person_id IS NULL;
    SELECT count(*) INTO v_projects FROM projects WHERE principal_investigator_person IS NULL;
    RAISE NOTICE 'ADR-0011 ownerless records (visible to Lab Members only through a project, campaign or co-owner): physical_samples=%, manufacturing_operations=%, test_sessions=%, campaigns=%, projects without a PI=%',
        v_samples, v_operations, v_tests, v_campaigns, v_projects;
END
$$;

-- migrate:down
-- Back to the unfiltered Lab Member grants of configure_users_and_policies.sql before ADR-0011.
-- Rows of the collections that script (and later migrations) granted keep existing with an empty
-- filter; rows of the collections this migration granted for the first time are deleted. A row a
-- deployment created by hand for one of those collections goes with them.
-- The indexes are dropped; the hidden alias is removed from the relation and the field list.

DELETE FROM directus_permissions
WHERE policy = '20000002-0000-0000-0000-000000000002'
  AND collection IN (
      'campaigns', 'campaign_samples', 'project_investigators', 'project_rollup',
      'sample_data_files', 'operation_data_files', 'session_data_files'
  );

UPDATE directus_permissions
SET permissions = '{}'
WHERE policy = '20000002-0000-0000-0000-000000000002'
  AND collection IN (
      'physical_samples', 'manufacturing_operations', 'test_sessions', 'projects',
      'sample_co_owners', 'sample_genealogy', 'sample_stock_provenance',
      'test_sessions_subject', 'machining_force_analysis', 'fast_run_data'
  );

DELETE FROM directus_fields WHERE collection = 'projects' AND field = 'samples';
UPDATE directus_relations
SET one_field = NULL
WHERE many_collection = 'physical_samples' AND many_field = 'project_id'
  AND one_collection = 'projects' AND one_field = 'samples';

DROP INDEX IF EXISTS idx_sample_co_owners_user_id;
DROP INDEX IF EXISTS idx_project_investigators_user_id;
DROP INDEX IF EXISTS idx_projects_principal_investigator_person;
DROP INDEX IF EXISTS idx_campaigns_owner_person_id;
DROP INDEX IF EXISTS idx_test_sessions_project_id;
DROP INDEX IF EXISTS idx_test_sessions_owner_person_id;
DROP INDEX IF EXISTS idx_manufacturing_operations_project_id;
DROP INDEX IF EXISTS idx_manufacturing_operations_owner_person_id;
DROP INDEX IF EXISTS idx_physical_samples_project_id;
DROP INDEX IF EXISTS idx_physical_samples_owner_person_id;
