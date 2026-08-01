-- migrate:up
-- ① People unification, step 2 of 3: repoint owner / operator / investigator FKs
-- at people via NEW columns, backfilled from the step-1 mapping. The old columns
-- (owner UUID→users, operator INT→Machine_Operators, principal_investigator,
-- junction user_id) are kept untouched as a backup until this is verified, then
-- retired in a follow-up. owner maps through people.user_id; operator through
-- people.legacy_machine_operator_id.

-- ── owner → owner_person_id (9 tables) ─────────────────────────────────────────
ALTER TABLE physical_samples         ADD COLUMN IF NOT EXISTS owner_person_id UUID REFERENCES people(person_id) ON DELETE SET NULL;
ALTER TABLE manufacturing_operations ADD COLUMN IF NOT EXISTS owner_person_id UUID REFERENCES people(person_id) ON DELETE SET NULL;
ALTER TABLE test_sessions            ADD COLUMN IF NOT EXISTS owner_person_id UUID REFERENCES people(person_id) ON DELETE SET NULL;
ALTER TABLE campaigns                ADD COLUMN IF NOT EXISTS owner_person_id UUID REFERENCES people(person_id) ON DELETE SET NULL;
ALTER TABLE etchants                 ADD COLUMN IF NOT EXISTS owner_person_id UUID REFERENCES people(person_id) ON DELETE SET NULL;
ALTER TABLE prep_recipes             ADD COLUMN IF NOT EXISTS owner_person_id UUID REFERENCES people(person_id) ON DELETE SET NULL;
ALTER TABLE tool_boxes               ADD COLUMN IF NOT EXISTS owner_person_id UUID REFERENCES people(person_id) ON DELETE SET NULL;
ALTER TABLE cutting_inserts          ADD COLUMN IF NOT EXISTS owner_person_id UUID REFERENCES people(person_id) ON DELETE SET NULL;
ALTER TABLE insert_edges             ADD COLUMN IF NOT EXISTS owner_person_id UUID REFERENCES people(person_id) ON DELETE SET NULL;

UPDATE physical_samples         t SET owner_person_id = p.person_id FROM people p WHERE t.owner = p.user_id;
UPDATE manufacturing_operations t SET owner_person_id = p.person_id FROM people p WHERE t.owner = p.user_id;
UPDATE test_sessions            t SET owner_person_id = p.person_id FROM people p WHERE t.owner = p.user_id;
UPDATE campaigns                t SET owner_person_id = p.person_id FROM people p WHERE t.owner = p.user_id;
UPDATE etchants                 t SET owner_person_id = p.person_id FROM people p WHERE t.owner = p.user_id;
UPDATE prep_recipes             t SET owner_person_id = p.person_id FROM people p WHERE t.owner = p.user_id;
UPDATE tool_boxes               t SET owner_person_id = p.person_id FROM people p WHERE t.owner = p.user_id;
UPDATE cutting_inserts          t SET owner_person_id = p.person_id FROM people p WHERE t.owner = p.user_id;
UPDATE insert_edges             t SET owner_person_id = p.person_id FROM people p WHERE t.owner = p.user_id;

-- ── operator → operator_person_id (2 tables) ───────────────────────────────────
ALTER TABLE manufacturing_operations ADD COLUMN IF NOT EXISTS operator_person_id UUID REFERENCES people(person_id) ON DELETE SET NULL;
ALTER TABLE test_sessions            ADD COLUMN IF NOT EXISTS operator_person_id UUID REFERENCES people(person_id) ON DELETE SET NULL;

UPDATE manufacturing_operations t SET operator_person_id = p.person_id FROM people p WHERE t.operator = p.legacy_machine_operator_id;
UPDATE test_sessions            t SET operator_person_id = p.person_id FROM people p WHERE t.operator = p.legacy_machine_operator_id;

-- ── projects.principal_investigator → principal_investigator_person ─────────────
ALTER TABLE projects ADD COLUMN IF NOT EXISTS principal_investigator_person UUID REFERENCES people(person_id) ON DELETE SET NULL;
UPDATE projects t SET principal_investigator_person = p.person_id FROM people p WHERE t.principal_investigator = p.user_id;

-- ── researcher junctions: add person_id alongside user_id ───────────────────────
ALTER TABLE project_investigators ADD COLUMN IF NOT EXISTS person_id UUID REFERENCES people(person_id) ON DELETE CASCADE;
ALTER TABLE sample_co_owners      ADD COLUMN IF NOT EXISTS person_id UUID REFERENCES people(person_id) ON DELETE CASCADE;
UPDATE project_investigators t SET person_id = p.person_id FROM people p WHERE t.user_id = p.user_id;
UPDATE sample_co_owners      t SET person_id = p.person_id FROM people p WHERE t.user_id = p.user_id;

-- migrate:down
ALTER TABLE sample_co_owners      DROP COLUMN IF EXISTS person_id;
ALTER TABLE project_investigators DROP COLUMN IF EXISTS person_id;
ALTER TABLE projects              DROP COLUMN IF EXISTS principal_investigator_person;
ALTER TABLE test_sessions            DROP COLUMN IF EXISTS operator_person_id;
ALTER TABLE manufacturing_operations DROP COLUMN IF EXISTS operator_person_id;
ALTER TABLE insert_edges             DROP COLUMN IF EXISTS owner_person_id;
ALTER TABLE cutting_inserts          DROP COLUMN IF EXISTS owner_person_id;
ALTER TABLE tool_boxes               DROP COLUMN IF EXISTS owner_person_id;
ALTER TABLE prep_recipes             DROP COLUMN IF EXISTS owner_person_id;
ALTER TABLE etchants                 DROP COLUMN IF EXISTS owner_person_id;
ALTER TABLE campaigns                DROP COLUMN IF EXISTS owner_person_id;
ALTER TABLE test_sessions            DROP COLUMN IF EXISTS owner_person_id;
ALTER TABLE manufacturing_operations DROP COLUMN IF EXISTS owner_person_id;
ALTER TABLE physical_samples         DROP COLUMN IF EXISTS owner_person_id;
