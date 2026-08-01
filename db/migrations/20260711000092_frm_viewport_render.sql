-- migrate:up
-- Pixel-identical "download this viewport" for the Live FRM. The client sends the
-- current viewport bounds + colour settings; the host (MATLAB, via force_orchestrator)
-- re-renders the FRM restricted to those bounds at full resolution with the exact same
-- styling as the prerendered frm_<axis>.png, and returns a PNG. This mirrors the Tier-2
-- live_render_points request pattern (poll on status), but for a one-off raster export.
ALTER TABLE machining_force_analysis
    ADD COLUMN IF NOT EXISTS render_status       text,        -- null | pending | processing | done | error
    ADD COLUMN IF NOT EXISTS render_bounds        jsonb,       -- { xmin, xmax, ymin, ymax } in mm
    ADD COLUMN IF NOT EXISTS render_axis          text,        -- Fx | Fy | Fz
    ADD COLUMN IF NOT EXISTS render_colormap      text,        -- viridis | inferno | grayscale
    ADD COLUMN IF NOT EXISTS render_cmin          numeric,     -- null => auto prctile 1
    ADD COLUMN IF NOT EXISTS render_cmax          numeric,     -- null => auto prctile 99
    ADD COLUMN IF NOT EXISTS render_file          uuid REFERENCES directus_files(id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS render_error         text,
    ADD COLUMN IF NOT EXISTS render_requested_at  timestamptz;

-- migrate:down
ALTER TABLE machining_force_analysis
    DROP COLUMN IF EXISTS render_status,
    DROP COLUMN IF EXISTS render_bounds,
    DROP COLUMN IF EXISTS render_axis,
    DROP COLUMN IF EXISTS render_colormap,
    DROP COLUMN IF EXISTS render_cmin,
    DROP COLUMN IF EXISTS render_cmax,
    DROP COLUMN IF EXISTS render_file,
    DROP COLUMN IF EXISTS render_error,
    DROP COLUMN IF EXISTS render_requested_at;
