-- migrate:up
-- Admin-configurable sampling settings for scripts/matlab/process_force.m,
-- threaded through by scripts/force_orchestrator.py (both --daemon and one-off
-- CLI runs). Changing these only affects files processed AFTER the change —
-- existing machining_force_analysis rows keep whatever settings produced them.

ALTER TABLE force_crawler_state
    ADD COLUMN IF NOT EXISTS series_points   INTEGER NOT NULL DEFAULT 3000,
    ADD COLUMN IF NOT EXISTS fft_points      INTEGER NOT NULL DEFAULT 3000,
    ADD COLUMN IF NOT EXISTS frm_max_points  INTEGER NOT NULL DEFAULT 1200000,
    ADD COLUMN IF NOT EXISTS frm_dpi         INTEGER NOT NULL DEFAULT 300;

COMMENT ON COLUMN force_crawler_state.series_points  IS 'Points per downsampled force/RPM envelope (series.json).';
COMMENT ON COLUMN force_crawler_state.fft_points     IS 'Points per FFT spectrum, spread across the full 0..Nyquist range.';
COMMENT ON COLUMN force_crawler_state.frm_max_points IS 'Point-cloud cap for the FRM scatter (denser = slower render, larger PNG).';
COMMENT ON COLUMN force_crawler_state.frm_dpi        IS 'exportgraphics Resolution for the FRM PNGs.';

INSERT INTO directus_fields (collection, field, interface, display, options, width, sort, readonly, hidden)
SELECT collection, field, interface, display, options::json, width, sort, readonly, hidden
FROM (VALUES
    ('force_crawler_state', 'series_points',   'input', 'raw', NULL, 'half', 6, false, false),
    ('force_crawler_state', 'fft_points',      'input', 'raw', NULL, 'half', 7, false, false),
    ('force_crawler_state', 'frm_max_points',  'input', 'raw', NULL, 'half', 8, false, false),
    ('force_crawler_state', 'frm_dpi',         'input', 'raw', NULL, 'half', 9, false, false)
) v(collection, field, interface, display, options, width, sort, readonly, hidden)
WHERE NOT EXISTS (
    SELECT 1 FROM directus_fields f WHERE f.collection = v.collection AND f.field = v.field
);

-- migrate:down
DELETE FROM directus_fields WHERE collection = 'force_crawler_state'
    AND field IN ('series_points', 'fft_points', 'frm_max_points', 'frm_dpi');
ALTER TABLE force_crawler_state
    DROP COLUMN IF EXISTS series_points,
    DROP COLUMN IF EXISTS fft_points,
    DROP COLUMN IF EXISTS frm_max_points,
    DROP COLUMN IF EXISTS frm_dpi;
