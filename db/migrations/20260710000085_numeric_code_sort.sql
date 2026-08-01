-- migrate:up
-- Directus sorts codes as plain strings, so "10" lands before "2". Add a generated
-- `code_sort` column that zero-pads the leading number (8 digits) so string ordering
-- matches numeric order, register it (hidden), and point the default list sort at it.

ALTER TABLE manufacturing_operations
    ADD COLUMN IF NOT EXISTS code_sort TEXT GENERATED ALWAYS AS (
        lpad(coalesce((regexp_match(pass_code, '^\d+'))[1], ''), 8, '0') || regexp_replace(coalesce(pass_code, ''), '^\d+', '')
    ) STORED;

ALTER TABLE physical_samples
    ADD COLUMN IF NOT EXISTS code_sort TEXT GENERATED ALWAYS AS (
        lpad(coalesce((regexp_match(sample_code, '^\d+'))[1], ''), 8, '0') || regexp_replace(coalesce(sample_code, ''), '^\d+', '')
    ) STORED;

CREATE INDEX IF NOT EXISTS manufacturing_operations_code_sort_idx ON manufacturing_operations (code_sort);
CREATE INDEX IF NOT EXISTS physical_samples_code_sort_idx        ON physical_samples (code_sort);

-- Register the helper field (hidden; used for sorting, not display).
INSERT INTO directus_fields (collection, field, interface, display, width, sort, readonly, hidden, special)
SELECT * FROM (VALUES
    ('manufacturing_operations', 'code_sort', 'input', 'raw', 'half', 900, true, true, NULL),
    ('physical_samples',         'code_sort', 'input', 'raw', 'half', 900, true, true, NULL)
) v(collection, field, interface, display, width, sort, readonly, hidden, special)
WHERE NOT EXISTS (
    SELECT 1 FROM directus_fields f WHERE f.collection = v.collection AND f.field = v.field
);

-- Global default preset (user & role NULL) so lists sort numerically out of the box.
INSERT INTO directus_presets (bookmark, "user", role, collection, layout, layout_query)
SELECT NULL, NULL, NULL, v.collection, 'tabular', ('{"tabular":{"sort":["code_sort"]}}')::json
FROM (VALUES ('manufacturing_operations'), ('physical_samples')) v(collection)
WHERE NOT EXISTS (
    SELECT 1 FROM directus_presets p
    WHERE p.collection = v.collection AND p.bookmark IS NULL AND p."user" IS NULL AND p.role IS NULL
);

-- Point the home-linked "Samples" bookmark (71) at the numeric sort too.
UPDATE directus_presets
   SET layout_query = jsonb_set(coalesce(layout_query::jsonb, '{}'::jsonb), '{tabular,sort}', '["code_sort"]'::jsonb)::json
 WHERE id = 71;

-- migrate:down
DELETE FROM directus_presets WHERE bookmark IS NULL AND "user" IS NULL AND role IS NULL
    AND collection IN ('manufacturing_operations', 'physical_samples')
    AND layout_query::text LIKE '%code_sort%';
DELETE FROM directus_fields WHERE field = 'code_sort' AND collection IN ('manufacturing_operations', 'physical_samples');
DROP INDEX IF EXISTS manufacturing_operations_code_sort_idx;
DROP INDEX IF EXISTS physical_samples_code_sort_idx;
ALTER TABLE manufacturing_operations DROP COLUMN IF EXISTS code_sort;
ALTER TABLE physical_samples DROP COLUMN IF EXISTS code_sort;
