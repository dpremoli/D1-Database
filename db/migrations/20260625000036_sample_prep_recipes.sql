-- migrate:up
-- Sample preparation as a manufacturing step, with reusable recipes.
-- Model: a "Sample Preparation" operation owns an ordered list of prep_steps
-- (mount / grind / polish / etch …). A prep_recipe is a saved template of such
-- steps; setting source_recipe_id on a new prep operation copies the template's
-- steps into editable prep_steps (done by the d1-apply-prep-recipe hook).

-- ── Etchants: extensible lookup (users can add their own) ─────────────────────
CREATE TABLE etchants (
    etchant_id    UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name          TEXT NOT NULL UNIQUE,
    composition   TEXT,
    suited_metals TEXT,
    notes         TEXT,
    owner         UUID,            -- directus_users, no hard FK (ADR-0002)
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    version    INTEGER     NOT NULL DEFAULT 1
);

COMMENT ON TABLE etchants IS 'Extensible list of metallographic etchants used in sample preparation.';

-- ── Reusable prep recipe (template) ───────────────────────────────────────────
CREATE TABLE prep_recipes (
    recipe_id   UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name        TEXT NOT NULL UNIQUE,
    description TEXT,
    suited_materials TEXT,
    owner       UUID,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    version    INTEGER     NOT NULL DEFAULT 1
);

COMMENT ON TABLE prep_recipes IS 'Reusable sample-preparation recipe (an ordered set of prep steps).';

-- Shared column set for a prep step, used by both the recipe template and the
-- actual applied steps on an operation.
-- ── Recipe template steps ─────────────────────────────────────────────────────
CREATE TABLE prep_recipe_steps (
    step_id       UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    recipe_id     UUID NOT NULL REFERENCES prep_recipes(recipe_id) ON DELETE CASCADE,
    step_order    INTEGER NOT NULL DEFAULT 1,
    step_type     TEXT CHECK (step_type IN ('sectioning','mounting','grinding','polishing','etching','cleaning','other')),
    grit          TEXT,                -- P50 … P4000 (grinding)
    suspension_um NUMERIC(8,3),        -- polishing suspension size (µm)
    cloth         TEXT,                -- polishing cloth
    etchant_id    UUID REFERENCES etchants(etchant_id) ON DELETE SET NULL,
    duration_s    NUMERIC(8,2),
    force_n       NUMERIC(8,2),
    rpm           NUMERIC(8,2),
    temperature_c NUMERIC(8,2),
    lubricant     TEXT,
    resin_type    TEXT,                -- mounting
    notes         TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    version    INTEGER     NOT NULL DEFAULT 1
);
CREATE INDEX prep_recipe_steps_recipe_idx ON prep_recipe_steps (recipe_id, step_order);

-- ── Actual prep steps applied in an operation (copied from a recipe, editable) ─
CREATE TABLE prep_steps (
    step_id       UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    operation_id  UUID NOT NULL REFERENCES manufacturing_operations(operation_id) ON DELETE CASCADE,
    step_order    INTEGER NOT NULL DEFAULT 1,
    step_type     TEXT CHECK (step_type IN ('sectioning','mounting','grinding','polishing','etching','cleaning','other')),
    grit          TEXT,
    suspension_um NUMERIC(8,3),
    cloth         TEXT,
    etchant_id    UUID REFERENCES etchants(etchant_id) ON DELETE SET NULL,
    duration_s    NUMERIC(8,2),
    force_n       NUMERIC(8,2),
    rpm           NUMERIC(8,2),
    temperature_c NUMERIC(8,2),
    lubricant     TEXT,
    resin_type    TEXT,
    notes         TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    version    INTEGER     NOT NULL DEFAULT 1
);
CREATE INDEX prep_steps_operation_idx ON prep_steps (operation_id, step_order);

-- ── Operation gains: prep process category + which recipe it came from ────────
ALTER TABLE manufacturing_operations DROP CONSTRAINT IF EXISTS manufacturing_operations_process_category_check;
ALTER TABLE manufacturing_operations ADD  CONSTRAINT manufacturing_operations_process_category_check
    CHECK (process_category IN ('machining','sintering','heat_treatment','deformation','additive','sample_prep'));

ALTER TABLE manufacturing_operations
    ADD COLUMN IF NOT EXISTS source_recipe_id UUID REFERENCES prep_recipes(recipe_id) ON DELETE SET NULL;
COMMENT ON COLUMN manufacturing_operations.source_recipe_id IS
    'Prep recipe this operation was pre-filled from (steps are copied into prep_steps, then editable).';

-- ── New method: Sample Preparation ────────────────────────────────────────────
INSERT INTO manufacturing_methods (method_code, method_name, description)
VALUES ('MP', 'Sample Preparation', 'Metallographic preparation: sectioning, mounting, grinding, polishing, etching')
ON CONFLICT (method_code) DO NOTHING;

-- ── OCC triggers ──────────────────────────────────────────────────────────────
CREATE TRIGGER etchants_occ          BEFORE UPDATE ON etchants          FOR EACH ROW EXECUTE FUNCTION occ_update_trigger_function();
CREATE TRIGGER prep_recipes_occ      BEFORE UPDATE ON prep_recipes      FOR EACH ROW EXECUTE FUNCTION occ_update_trigger_function();
CREATE TRIGGER prep_recipe_steps_occ BEFORE UPDATE ON prep_recipe_steps FOR EACH ROW EXECUTE FUNCTION occ_update_trigger_function();
CREATE TRIGGER prep_steps_occ        BEFORE UPDATE ON prep_steps        FOR EACH ROW EXECUTE FUNCTION occ_update_trigger_function();

-- ── Seed common metallographic etchants ───────────────────────────────────────
INSERT INTO etchants (name, composition, suited_metals) VALUES
('Nital (2%)',        '2 mL HNO3 + 98 mL ethanol',                         'Carbon & low-alloy steels, cast iron'),
('Nital (5%)',        '5 mL HNO3 + 95 mL ethanol',                         'Carbon & low-alloy steels'),
('Picral',            '4 g picric acid + 100 mL ethanol',                  'Steels (pearlite/carbides)'),
('Kalling''s No.2',   '5 g CuCl2 + 100 mL HCl + 100 mL ethanol',           'Ni superalloys, stainless, duplex'),
('Kroll''s',          '2 mL HF + 6 mL HNO3 + 92 mL water',                 'Titanium & Ti alloys'),
('Marble''s',         '10 g CuSO4 + 50 mL HCl + 50 mL water',              'Ni & Co superalloys, stainless'),
('Glyceregia',        '10 mL HNO3 + 20–30 mL HCl + 30 mL glycerol',        'Ni superalloys, stainless'),
('Keller''s',         '2 mL HF + 3 mL HCl + 5 mL HNO3 + 190 mL water',     'Aluminium alloys'),
('Vilella''s',        '1 g picric acid + 5 mL HCl + 100 mL ethanol',       'Martensitic/tool steels'),
('Murakami''s',       '10 g K3Fe(CN)6 + 10 g KOH + 100 mL water',          'Carbides, WC-Co, Ti'),
('Adler''s',          '3 g CuNH4Cl2 + 50 mL HCl + 15 g FeCl3 + 25 mL water','Stainless & Ni alloys'),
('Beraha''s',         'HCl + K2S2O5 in water (tint etch)',                 'Steels, stainless (colour)'),
('Aqua regia',        '1 part HNO3 + 3 parts HCl',                         'Au, Pt, high-alloy stainless'),
('HF (dilute)',       '0.5–2 mL HF + 100 mL water',                        'Ti, Zr, reactive metals'),
('Electrolytic oxalic','10 g oxalic acid + 100 mL water (electrolytic)',   'Austenitic stainless')
ON CONFLICT (name) DO NOTHING;

-- migrate:down
DROP TRIGGER IF EXISTS prep_steps_occ ON prep_steps;
DROP TRIGGER IF EXISTS prep_recipe_steps_occ ON prep_recipe_steps;
DROP TRIGGER IF EXISTS prep_recipes_occ ON prep_recipes;
DROP TRIGGER IF EXISTS etchants_occ ON etchants;
ALTER TABLE manufacturing_operations DROP COLUMN IF EXISTS source_recipe_id;
ALTER TABLE manufacturing_operations DROP CONSTRAINT IF EXISTS manufacturing_operations_process_category_check;
ALTER TABLE manufacturing_operations ADD  CONSTRAINT manufacturing_operations_process_category_check
    CHECK (process_category IN ('machining','sintering','heat_treatment','deformation','additive'));
DROP TABLE IF EXISTS prep_steps;
DROP TABLE IF EXISTS prep_recipe_steps;
DROP TABLE IF EXISTS prep_recipes;
DROP TABLE IF EXISTS etchants;
DELETE FROM manufacturing_methods WHERE method_code = 'MP';
