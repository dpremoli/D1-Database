-- migrate:up
-- Surfaces the .mat file's own recorded trigger time (metadata.TriggerTime in the
-- archive file, when present) rather than relying on operation_date / created_at,
-- which are frequently just the sample-record creation time for legacy imports.

ALTER TABLE machining_force_analysis
    ADD COLUMN IF NOT EXISTS trigger_time TIMESTAMPTZ;

COMMENT ON COLUMN machining_force_analysis.trigger_time IS
    'metadata.TriggerTime read from the source .mat file, when present (the actual recording time, not the DB row creation time).';

INSERT INTO directus_fields (collection, field, interface, display, options, width, sort, readonly, hidden)
SELECT collection, field, interface, display, options::json, width, sort, readonly, hidden
FROM (VALUES
    ('machining_force_analysis', 'trigger_time', 'datetime', 'datetime', NULL, 'half', 10, true, false)
) v(collection, field, interface, display, options, width, sort, readonly, hidden)
WHERE NOT EXISTS (
    SELECT 1 FROM directus_fields f WHERE f.collection = v.collection AND f.field = v.field
);

-- migrate:down
DELETE FROM directus_fields WHERE collection = 'machining_force_analysis' AND field = 'trigger_time';
ALTER TABLE machining_force_analysis DROP COLUMN IF EXISTS trigger_time;
