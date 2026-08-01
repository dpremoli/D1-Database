-- migrate:up
-- The operation form now links recipes via fast_recipe_id (a real relation), so the free-text
-- sintering_recipe_number is redundant there. Hide the text field on the form; the column is
-- kept in the table as raw provenance (the machine's original recipe string).
UPDATE directus_fields SET hidden = true
 WHERE collection = 'manufacturing_operations' AND field = 'sintering_recipe_number';

-- migrate:down
UPDATE directus_fields SET hidden = false
 WHERE collection = 'manufacturing_operations' AND field = 'sintering_recipe_number';
