-- migrate:up
-- Hand-painted regions for the Diagnostics Workbench (Recipe Workbench spec, Component 3).
-- A layer is POLYGONS IN (x, y) MILLIMETRES on the angular-resampled analysis grid -- the
-- coordinate space frame_transform produces and DiagScatter renders -- NOT a per-point array.
-- Geometry survives re-baking at any samples_per_rev; a dense mask would be welded to the
-- current point count and ordering. Rasterisation to per-point booleans happens server-side
-- in scripts/diag/layers.py, consumed by run_recipe's per-step `inputs` bindings.
CREATE TABLE IF NOT EXISTS diag_layer (
    layer_id     UUID        NOT NULL DEFAULT uuid_generate_v4(),
    analysis_id  UUID        NOT NULL REFERENCES machining_force_analysis(id) ON DELETE CASCADE,
    name         TEXT        NOT NULL,
    role         TEXT        NOT NULL,
    geometry     JSONB       NOT NULL,
    value        JSONB,
    version      INTEGER     NOT NULL DEFAULT 1,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT diag_layer_pkey PRIMARY KEY (layer_id),
    CONSTRAINT diag_layer_role_ck CHECK (role IN ('mask', 'label', 'seed')),
    CONSTRAINT diag_layer_name_uq UNIQUE (analysis_id, name)
);
CREATE INDEX IF NOT EXISTS diag_layer_analysis_idx ON diag_layer (analysis_id);

-- Register the collection with Directus so the items API exposes it -- the workbench does
-- layer CRUD through /items/diag_layer. Mirrors 20260901000106_diag_recipe.sql's treatment
-- of diag_recipes. `special` is a comma-separated varchar in this Directus schema, not an
-- array; jsonb columns get an input-code interface and NO special (matching how diag_recipe
-- itself was registered in 20260903000107).
INSERT INTO directus_collections (collection, icon, note, hidden, singleton)
SELECT 'diag_layer', 'gesture', 'Hand-painted mask/label/seed regions for a diagnostics cut.', false, false
WHERE NOT EXISTS (SELECT 1 FROM directus_collections WHERE collection = 'diag_layer');

INSERT INTO directus_fields (collection, field, special, interface, options, readonly, hidden, sort, note)
SELECT collection, field, special, interface, options::json, readonly, hidden, sort, note
FROM (VALUES
    ('diag_layer', 'layer_id',    'uuid',         'input',               NULL,                  true,  true,  1,
     'Primary key.'),
    ('diag_layer', 'analysis_id', 'm2o',          'select-dropdown-m2o', NULL,                  false, false, 2,
     'The machining_force_analysis row this region belongs to.'),
    ('diag_layer', 'name',        NULL,           'input',               NULL,                  false, false, 3,
     'The name a recipe step''s `inputs` binding refers to. Unique per analysis.'),
    ('diag_layer', 'role',        NULL,           'select-dropdown',     '{"choices":[{"text":"mask","value":"mask"},{"text":"label","value":"label"},{"text":"seed","value":"seed"}]}', false, false, 4,
     'mask = excluded from compute; label = annotation only; seed = in/out examples for a future segmentation step.'),
    ('diag_layer', 'geometry',    NULL,           'input-code',          '{"language":"json"}', false, false, 5,
     'Polygons in (x, y) mm on the angular-resampled analysis grid: {"polygons": [[[x,y],...], ...]}.'),
    ('diag_layer', 'value',       NULL,           'input-code',          '{"language":"json"}', false, false, 6,
     'Role payload: mask {"mode":"exclude"}; label {"name":..,"colour":..}; seed {"class":..}.'),
    ('diag_layer', 'version',     NULL,           'input',               NULL,                  false, false, 7,
     'Bumped on every geometry edit; stands in for content in the bake hash fingerprint.'),
    ('diag_layer', 'created_at',  'date-created', 'datetime',            NULL,                  true,  false, 8, NULL),
    ('diag_layer', 'updated_at',  'date-updated', 'datetime',            NULL,                  true,  false, 9, NULL)
) v(collection, field, special, interface, options, readonly, hidden, sort, note)
WHERE NOT EXISTS (
    SELECT 1 FROM directus_fields f WHERE f.collection = v.collection AND f.field = v.field
);

-- migrate:down
DELETE FROM directus_fields WHERE collection = 'diag_layer';
DELETE FROM directus_collections WHERE collection = 'diag_layer';
DROP TABLE IF EXISTS diag_layer;
