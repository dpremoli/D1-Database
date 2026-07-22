-- migrate:up
-- FAST sintering recipes, imported from each machine's own recipe store:
--   FAST 25  -> ECS_Prog.mdb::Rezept (keyed by ProgrammNr)
--   FAST 250 -> PROGS/*.rcp          (keyed by name; no program number)
-- Operations link via manufacturing_operations.fast_recipe_id.

CREATE TABLE fast_recipes (
    id              UUID        NOT NULL DEFAULT uuid_generate_v4(),
    machine         VARCHAR(8)  NOT NULL,
    program_nr      INTEGER,
    name            TEXT        NOT NULL,
    group_name      TEXT,
    source_file     TEXT,
    target_temp_c   NUMERIC,
    target_force_kn NUMERIC,
    hold_time_min   NUMERIC,
    params          JSONB,
    date_created    TIMESTAMPTZ,
    date_changed    TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT fast_recipes_pkey PRIMARY KEY (id),
    CONSTRAINT fast_recipes_machine_chk CHECK (machine IN ('25', '250'))
);

COMMENT ON TABLE fast_recipes IS
    'FAST sintering recipe definitions (ECS_Prog.mdb::Rezept for 25, PROGS/*.rcp for 250).';

-- Identity differs per machine: FAST 25 is keyed by ProgrammNr (two recipes may legitimately
-- share a ProgrammText), FAST 250 has no program number and is keyed by name. Two partial
-- indexes, NOT one composite — a plain (machine, lower(name)) unique index would wrongly
-- reject duplicate-titled FAST 25 recipes.
CREATE UNIQUE INDEX fast_recipes_prog_uniq ON fast_recipes (machine, program_nr)
    WHERE program_nr IS NOT NULL;
CREATE UNIQUE INDEX fast_recipes_name_uniq ON fast_recipes (machine, lower(name))
    WHERE program_nr IS NULL;

ALTER TABLE manufacturing_operations
    ADD COLUMN IF NOT EXISTS fast_recipe_id UUID REFERENCES fast_recipes(id) ON DELETE SET NULL;
CREATE INDEX manufacturing_operations_fast_recipe_idx
    ON manufacturing_operations (fast_recipe_id);

-- ── Directus registration ──────────────────────────────────────────────────────
INSERT INTO directus_collections (collection, icon, note, display_template, hidden, "group", sort)
VALUES ('fast_recipes', 'science',
        'FAST sintering recipe definitions imported from the machine recipe stores',
        '{{name}}', false, 'manufacturing_methods', 11)
ON CONFLICT (collection) DO NOTHING;

INSERT INTO directus_fields (collection, field, interface, display, options, width, sort, special, readonly, hidden)
SELECT collection, field, interface, display, options::json, width, sort, special, readonly, hidden
FROM (VALUES
    ('fast_recipes', 'name',            'input', 'raw', NULL, 'full', 1, NULL, true, false),
    ('fast_recipes', 'machine',         'input', 'raw', NULL, 'half', 2, NULL, true, false),
    ('fast_recipes', 'program_nr',      'input', 'raw', NULL, 'half', 3, NULL, true, false),
    ('fast_recipes', 'group_name',      'input', 'raw', NULL, 'half', 4, NULL, true, false),
    ('fast_recipes', 'target_temp_c',   'input', 'raw', NULL, 'half', 5, NULL, true, false),
    ('fast_recipes', 'target_force_kn', 'input', 'raw', NULL, 'half', 6, NULL, true, false),
    ('fast_recipes', 'hold_time_min',   'input', 'raw', NULL, 'half', 7, NULL, true, false),
    ('fast_recipes', 'source_file',     'input', 'raw', NULL, 'full', 8, NULL, true, false),
    ('fast_recipes', 'params',          'input-code', 'raw', NULL, 'full', 20, 'cast-json', true, true)
) v(collection, field, interface, display, options, width, sort, special, readonly, hidden)
WHERE NOT EXISTS (
    SELECT 1 FROM directus_fields f WHERE f.collection = v.collection AND f.field = v.field
);

-- M2O on the operation form.
INSERT INTO directus_fields (collection, field, interface, display, options, display_options, width, sort, special, hidden)
SELECT 'manufacturing_operations', 'fast_recipe_id', 'select-dropdown-m2o', 'related-values',
       '{"template":"{{name}}","enableCreate":false}'::json, '{"template":"{{name}}"}'::json, 'half', 50, 'm2o', false
WHERE NOT EXISTS (
    SELECT 1 FROM directus_fields f
    WHERE f.collection = 'manufacturing_operations' AND f.field = 'fast_recipe_id'
);

-- O2M back-reference so a recipe page lists its runs.
INSERT INTO directus_fields (collection, field, interface, special, options, display, width, sort, hidden)
SELECT 'fast_recipes', 'runs', 'list-o2m', 'o2m',
       '{"template":"{{pass_code}}","enableCreate":false,"enableSelect":false}'::json,
       'related-values', 'full', 30, false
WHERE NOT EXISTS (
    SELECT 1 FROM directus_fields f WHERE f.collection = 'fast_recipes' AND f.field = 'runs'
);

INSERT INTO directus_relations (many_collection, many_field, one_collection, one_field, one_deselect_action)
SELECT 'manufacturing_operations', 'fast_recipe_id', 'fast_recipes', 'runs', 'nullify'
WHERE NOT EXISTS (
    SELECT 1 FROM directus_relations r
    WHERE r.many_collection = 'manufacturing_operations' AND r.many_field = 'fast_recipe_id'
);

-- Lab Member: read-only.
INSERT INTO directus_permissions (policy, collection, action, permissions, validation, fields)
SELECT '20000002-0000-0000-0000-000000000002', 'fast_recipes', 'read', '{}', '{}', '*'
WHERE NOT EXISTS (
    SELECT 1 FROM directus_permissions p
    WHERE p.policy = '20000002-0000-0000-0000-000000000002'
      AND p.collection = 'fast_recipes' AND p.action = 'read'
);

-- migrate:down
DELETE FROM directus_permissions WHERE collection = 'fast_recipes';
DELETE FROM directus_relations   WHERE many_collection = 'manufacturing_operations' AND many_field = 'fast_recipe_id';
DELETE FROM directus_fields      WHERE collection = 'fast_recipes';
DELETE FROM directus_fields      WHERE collection = 'manufacturing_operations' AND field = 'fast_recipe_id';
DELETE FROM directus_collections WHERE collection = 'fast_recipes';
ALTER TABLE manufacturing_operations DROP COLUMN IF EXISTS fast_recipe_id;
DROP TABLE IF EXISTS fast_recipes;
