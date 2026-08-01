-- migrate:up
-- ① People unification, step 1 of 3: the people table + backfill.
--
-- Problem: operators (Machine_Operators) and researchers/owners (directus_users)
-- are separate identity spaces, but the same human is often both — an operator who
-- also owns samples and has an app login. That forces messy, duplicated attribution.
--
-- people is the single identity for anyone attributed on a record. It optionally
-- links to a Directus login (user_id) — operators aren't always app users — and
-- carries role flags (is_operator / is_researcher) so one person can be both.
--
-- This step only CREATES and BACKFILLS people. Repointing the owner/operator/PI FKs
-- happens in step 2 (…_people_repoint), and the Directus config in step 3, so each
-- stage is reversible on its own.

CREATE TABLE IF NOT EXISTS people (
    person_id                   UUID        NOT NULL DEFAULT uuid_generate_v4(),
    full_name                   TEXT        NOT NULL,
    email                       TEXT,
    user_id                     UUID,               -- app login, NULL for pure technicians
    is_operator                 BOOLEAN     NOT NULL DEFAULT FALSE,
    is_researcher               BOOLEAN     NOT NULL DEFAULT FALSE,
    active                      BOOLEAN     NOT NULL DEFAULT TRUE,
    notes                       TEXT,
    legacy_machine_operator_id  INTEGER,            -- provenance, drives the operator remap
    created_at                  TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT people_pkey PRIMARY KEY (person_id),
    CONSTRAINT people_user_id_unique UNIQUE (user_id),
    CONSTRAINT people_legacy_mo_id_unique UNIQUE (legacy_machine_operator_id),
    CONSTRAINT people_user_id_fkey FOREIGN KEY (user_id)
        REFERENCES directus_users(id) ON DELETE SET NULL
);

COMMENT ON TABLE people IS
    'Unified identity for anyone attributed on a record (operator, researcher, owner). Optionally linked to a Directus login via user_id; pure technicians have none.';
COMMENT ON COLUMN people.user_id IS 'Directus login, if this person is an app user. NULL for operators without an account.';
COMMENT ON COLUMN people.legacy_machine_operator_id IS 'Source Machine_Operators.id, kept so operator FKs can be remapped and for provenance.';

-- 1) Every Directus user becomes a person (researcher by default).
INSERT INTO people (full_name, email, user_id, is_researcher)
SELECT COALESCE(NULLIF(btrim(COALESCE(first_name,'') || ' ' || COALESCE(last_name,'')), ''), email, 'User ' || id::text),
       email, id, TRUE
FROM directus_users
WHERE NOT EXISTS (SELECT 1 FROM people p WHERE p.user_id = directus_users.id);

-- 2a) A Machine_Operator linked to a user IS that person → also flag operator + provenance.
UPDATE people p
SET is_operator = TRUE, legacy_machine_operator_id = mo.id
FROM "Machine_Operators" mo
WHERE mo.user_id = p.user_id
  AND p.legacy_machine_operator_id IS NULL;

-- 2b) A Machine_Operator with no user is a standalone person (pure technician).
INSERT INTO people (full_name, is_operator, legacy_machine_operator_id)
SELECT mo."Name", TRUE, mo.id
FROM "Machine_Operators" mo
WHERE mo.user_id IS NULL
  AND NOT EXISTS (SELECT 1 FROM people p WHERE p.legacy_machine_operator_id = mo.id);

-- migrate:down
DROP TABLE IF EXISTS people CASCADE;
