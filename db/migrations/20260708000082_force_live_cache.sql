-- migrate:up
-- Live mode: a medium-resolution decimated point-cloud cache (live_cache.bin) is
-- produced once during crawler processing (scripts/matlab/process_force.m) and
-- uploaded to Directus (scripts/force_orchestrator.py). The d1-force-dashboard
-- "Live" mode downloads it and recomputes the FRM client-side for any crop /
-- Feed / Diameter / RPM without re-reading the archive. One generic-file FK per
-- analysis row, following the frm_fx/fy/fz blueprint (migration ...076) but with
-- the plain 'file' interface (it's binary, not an image).

ALTER TABLE machining_force_analysis
    ADD COLUMN IF NOT EXISTS live_cache_file UUID REFERENCES directus_files(id) ON DELETE SET NULL;

INSERT INTO directus_fields (collection, field, interface, display, width, sort, special)
SELECT * FROM (VALUES
    ('machining_force_analysis', 'live_cache_file', 'file', 'file', 'half', 13, 'file')
) v(collection, field, interface, display, width, sort, special)
WHERE NOT EXISTS (
    SELECT 1 FROM directus_fields f WHERE f.collection = v.collection AND f.field = v.field
);

INSERT INTO directus_relations (many_collection, many_field, one_collection, one_deselect_action)
SELECT 'machining_force_analysis', 'live_cache_file', 'directus_files', 'nullify'
WHERE NOT EXISTS (
    SELECT 1 FROM directus_relations r
    WHERE r.many_collection = 'machining_force_analysis' AND r.many_field = 'live_cache_file'
);

-- Admin-configurable target point count for the live cache (per axis), following
-- the sampling-settings pattern (migration ...079).
ALTER TABLE force_crawler_state
    ADD COLUMN IF NOT EXISTS live_cache_points INTEGER NOT NULL DEFAULT 250000;

COMMENT ON COLUMN force_crawler_state.live_cache_points IS
    'Target points per axis in live_cache.bin (the browser Live-mode point cloud). Larger = finer signal/FRM but bigger download.';

INSERT INTO directus_fields (collection, field, interface, display, options, width, sort, readonly, hidden)
SELECT collection, field, interface, display, options::json, width, sort, readonly, hidden
FROM (VALUES
    ('force_crawler_state', 'live_cache_points', 'input', 'raw', NULL, 'half', 10, false, false)
) v(collection, field, interface, display, options, width, sort, readonly, hidden)
WHERE NOT EXISTS (
    SELECT 1 FROM directus_fields f WHERE f.collection = v.collection AND f.field = v.field
);

-- migrate:down
DELETE FROM directus_fields WHERE collection = 'force_crawler_state' AND field = 'live_cache_points';
ALTER TABLE force_crawler_state DROP COLUMN IF EXISTS live_cache_points;
DELETE FROM directus_relations WHERE many_collection = 'machining_force_analysis' AND many_field = 'live_cache_file';
DELETE FROM directus_fields    WHERE collection = 'machining_force_analysis' AND field = 'live_cache_file';
ALTER TABLE machining_force_analysis DROP COLUMN IF EXISTS live_cache_file;
