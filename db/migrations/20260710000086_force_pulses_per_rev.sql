-- migrate:up
-- Pulses-per-rev for tachorpm (scripts/matlab/process_force.m): the number of
-- tacho pulses per spindle revolution is not always 1. A global admin default
-- (force_crawler_state, following the series_points/live_cache_points
-- blueprint) plus a per-operation resolved value (machining_force_analysis,
-- following the live_cache_file/live_render_points blueprint in migration
-- ...082) — the orchestrator writes the value actually used for each row's
-- current PNGs/metrics back via summary.json, the same way sample_rate/feed
-- already round-trip.

ALTER TABLE force_crawler_state
    ADD COLUMN IF NOT EXISTS pulses_per_rev INTEGER NOT NULL DEFAULT 1;

COMMENT ON COLUMN force_crawler_state.pulses_per_rev IS
    'Global default tacho pulses-per-revolution for tachorpm (PulsesPerRev). Overridable per-row via machining_force_analysis.pulses_per_rev.';

INSERT INTO directus_fields (collection, field, interface, display, options, width, sort, readonly, hidden)
SELECT collection, field, interface, display, options::json, width, sort, readonly, hidden
FROM (VALUES
    ('force_crawler_state', 'pulses_per_rev', 'input', 'raw', NULL, 'half', 11, false, false)
) v(collection, field, interface, display, options, width, sort, readonly, hidden)
WHERE NOT EXISTS (
    SELECT 1 FROM directus_fields f WHERE f.collection = v.collection AND f.field = v.field
);

ALTER TABLE machining_force_analysis
    ADD COLUMN IF NOT EXISTS pulses_per_rev INTEGER;

COMMENT ON COLUMN machining_force_analysis.pulses_per_rev IS
    'Tacho pulses-per-revolution actually used to produce this row''s current PNGs/metrics. NULL = never processed under this feature yet.';

INSERT INTO directus_fields (collection, field, interface, display, options, width, sort, readonly, hidden)
SELECT collection, field, interface, display, options::json, width, sort, readonly, hidden
FROM (VALUES
    ('machining_force_analysis', 'pulses_per_rev', 'input', 'raw', NULL, 'half', 22, false, false)
) v(collection, field, interface, display, options, width, sort, readonly, hidden)
WHERE NOT EXISTS (
    SELECT 1 FROM directus_fields f WHERE f.collection = v.collection AND f.field = v.field
);

-- migrate:down
DELETE FROM directus_fields WHERE collection = 'machining_force_analysis' AND field = 'pulses_per_rev';
ALTER TABLE machining_force_analysis DROP COLUMN IF EXISTS pulses_per_rev;
DELETE FROM directus_fields WHERE collection = 'force_crawler_state' AND field = 'pulses_per_rev';
ALTER TABLE force_crawler_state DROP COLUMN IF EXISTS pulses_per_rev;
