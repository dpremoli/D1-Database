-- migrate:up
-- Donut / diaphragm disc support: some components (e.g. 122-*) are annular — the cut
-- stops at an inner radius (the central hole) instead of reaching radius 0. inner_diameter
-- (mm, default 0 = solid disc) is an editable FRM parameter, threaded to process_force.m so
-- the spiral runs rho: Diam/2 -> inner_diameter/2 for the PNG / octree / grid / live cache,
-- and applied client-side by the Live recompute.
ALTER TABLE machining_force_analysis
    ADD COLUMN IF NOT EXISTS inner_diameter real NOT NULL DEFAULT 0;

COMMENT ON COLUMN machining_force_analysis.inner_diameter IS
    'Inner diameter (mm) for donut/diaphragm discs; 0 = solid disc (spiral runs to radius 0).';

-- migrate:down
ALTER TABLE machining_force_analysis DROP COLUMN IF EXISTS inner_diameter;
