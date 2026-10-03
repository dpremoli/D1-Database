-- migrate:up
-- Put the "Generate PDF" button (d1-report-button interface) on the sample, operation and
-- test forms. The extension and the /d1-report endpoint were shipped, but no directus_fields
-- row ever placed the button, so it never appeared on a record. The field is a presentation
-- alias (no column), sorted first so it sits at the top of the form. Idempotent: a button an
-- admin already added by hand under the same field name is left alone.
INSERT INTO directus_fields (collection, field, special, interface, options, display, readonly, hidden, sort, width, required, translations)
SELECT collection, field, special, interface, options::json, display, readonly, hidden, sort, width, required, translations::json
FROM (VALUES
    ('physical_samples', 'report_button', 'alias,no-data', 'd1-report-button', '{"label":"Generate sample PDF","report":"sample"}', NULL, false, false, 0, 'full', false,
     '[{"language":"en-US","translation":"Report"}]'),
    ('manufacturing_operations', 'report_button', 'alias,no-data', 'd1-report-button', '{"label":"Generate operation PDF","report":"operation"}', NULL, false, false, 0, 'full', false,
     '[{"language":"en-US","translation":"Report"}]'),
    ('test_sessions', 'report_button', 'alias,no-data', 'd1-report-button', '{"label":"Generate test PDF","report":"test"}', NULL, false, false, 0, 'full', false,
     '[{"language":"en-US","translation":"Report"}]')
) v(collection, field, special, interface, options, display, readonly, hidden, sort, width, required, translations)
WHERE NOT EXISTS (
    SELECT 1 FROM directus_fields f WHERE f.collection = v.collection AND f.field = v.field
);

-- migrate:down
DELETE FROM directus_fields
WHERE field = 'report_button'
  AND interface = 'd1-report-button'
  AND collection IN ('physical_samples', 'manufacturing_operations', 'test_sessions');
