-- migrate:up
-- Register machining_force_analysis.diag_recipe / diag_recipe_hash with Directus so the API
-- exposes them and the admin UI shows the recipe as an editable JSON block. Mirrors
-- 20260721000097_filter_chain.sql's treatment of filter_chain: an input-code interface with
-- the JSON language, raw display. Without a directus_fields row Directus only auto-discovers
-- the column after a schema-cache refresh AND the field cannot be given a useful interface.
INSERT INTO directus_fields (collection, field, interface, display, options, width, sort, readonly, hidden, note)
SELECT collection, field, interface, display, options::json, width, sort, readonly, hidden, note
FROM (VALUES
    ('machining_force_analysis', 'diag_recipe', 'input-code', 'raw', '{"language":"json"}', 'full', 70, false, false,
     'The diagnostics recipe this cut was (or will be) baked from. NULL = the built-in default. Edited from the Diagnostics Workbench; process_diag_row bakes whatever is here.'),
    ('machining_force_analysis', 'diag_recipe_hash', 'input', 'raw', NULL, 'half', 71, true, true,
     'Identity of the effective recipe the CURRENT diag artifacts were baked from (stored recipe + tool_setup injection). Set by process_diag_row; not comparable to a hash of diag_recipe alone.')
) v(collection, field, interface, display, options, width, sort, readonly, hidden, note)
WHERE NOT EXISTS (
    SELECT 1 FROM directus_fields f WHERE f.collection = v.collection AND f.field = v.field
);

-- migrate:down
DELETE FROM directus_fields
WHERE collection = 'machining_force_analysis' AND field IN ('diag_recipe', 'diag_recipe_hash');
