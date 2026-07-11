-- migrate:up
-- Tier-2 "Process at full resolution" for the dashboard Live mode: the browser
-- requests a denser (down to 1:1) live_cache.bin for one operation by setting
-- live_render_points + status='pending'. The host orchestrator honours that
-- per-row override for live_cache_points, then clears it. This never touches the
-- canonical FRM PNGs / metrics — it only regenerates the (non-canonical) point-cloud
-- cache the browser plots from.

ALTER TABLE machining_force_analysis
    ADD COLUMN IF NOT EXISTS live_render_points INTEGER;

COMMENT ON COLUMN machining_force_analysis.live_render_points IS
    'Client render request: desired live_cache.bin point count (1 = full 1:1). Consumed and cleared by the host orchestrator.';

INSERT INTO directus_fields (collection, field, interface, display, options, width, sort, readonly, hidden)
SELECT collection, field, interface, display, options::json, width, sort, readonly, hidden
FROM (VALUES
    ('machining_force_analysis', 'live_render_points', 'input', 'raw', NULL, 'half', 14, true, false)
) v(collection, field, interface, display, options, width, sort, readonly, hidden)
WHERE NOT EXISTS (
    SELECT 1 FROM directus_fields f WHERE f.collection = v.collection AND f.field = v.field
);

-- migrate:down
DELETE FROM directus_fields WHERE collection = 'machining_force_analysis' AND field = 'live_render_points';
ALTER TABLE machining_force_analysis DROP COLUMN IF EXISTS live_render_points;
