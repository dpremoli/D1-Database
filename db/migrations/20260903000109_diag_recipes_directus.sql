-- migrate:up
-- Register the diag_recipes library table with Directus so /items/diag_recipes is exposed --
-- the table was created in 20260901000106 but never registered. The workbench does recipe
-- CRUD through this endpoint. Mirrors how filter_profiles and diag_layer are surfaced.
INSERT INTO directus_collections (collection, icon, note, hidden, singleton)
SELECT 'diag_recipes', 'menu_book',
       'Named, reusable diagnostics recipes; applying one copies its document onto a cut.',
       false, false
WHERE NOT EXISTS (SELECT 1 FROM directus_collections WHERE collection = 'diag_recipes');

INSERT INTO directus_fields (collection, field, special, interface, options, readonly, hidden, sort, note)
SELECT collection, field, special, interface, options::json, readonly, hidden, sort, note
FROM (VALUES
    ('diag_recipes', 'recipe_id',  'uuid',         'input',           NULL,                  true,  true,  1, 'Primary key.'),
    ('diag_recipes', 'name',       NULL,           'input',           NULL,                  false, false, 2, 'Unique library name.'),
    ('diag_recipes', 'recipe',     NULL,           'input-code',      '{"language":"json"}', false, false, 3, 'The recipe document copied onto machining_force_analysis.diag_recipe when applied.'),
    ('diag_recipes', 'notes',      NULL,           'input-multiline', NULL,                  false, false, 4, NULL),
    ('diag_recipes', 'created_at', 'date-created', 'datetime',        NULL,                  true,  false, 5, NULL),
    ('diag_recipes', 'updated_at', 'date-updated', 'datetime',        NULL,                  true,  false, 6, NULL)
) v(collection, field, special, interface, options, readonly, hidden, sort, note)
WHERE NOT EXISTS (SELECT 1 FROM directus_fields f WHERE f.collection = 'diag_recipes' AND f.field = v.field);

-- migrate:down
DELETE FROM directus_fields WHERE collection = 'diag_recipes';
DELETE FROM directus_collections WHERE collection = 'diag_recipes';
