-- migrate:up
-- FRM interpolated-grid octree: a second octree variant per op, built from the spiral
-- interpolated onto a fine N×N grid (MATLAB grid_out -> D1GR binary -> LAS -> PotreeConverter),
-- served under /octrees/grid/<op_id>/. Mirrors the raw octree_* columns and adds the fidelity
-- estimate + cell size. force_crawler_state gains the gridding + octree LOD tuning knobs.

ALTER TABLE machining_force_analysis
    ADD COLUMN IF NOT EXISTS grid_octree_status       text,        -- null | pending | processing | done | error
    ADD COLUMN IF NOT EXISTS grid_octree_path         text,        -- served subdir under /octrees/grid/
    ADD COLUMN IF NOT EXISTS grid_octree_points       bigint,      -- kept grid cells (points in the octree)
    ADD COLUMN IF NOT EXISTS grid_octree_error        text,
    ADD COLUMN IF NOT EXISTS grid_octree_requested_at timestamptz,
    ADD COLUMN IF NOT EXISTS grid_fidelity            real,        -- 0..1 hold-out-arms cross-validation
    ADD COLUMN IF NOT EXISTS grid_arm_ratio           real,        -- median arm spacing / cell size
    ADD COLUMN IF NOT EXISTS grid_cell_mm             real;        -- grid cell size (mm), for fill sizing

-- octree_threshold decouples the dashboard's auto-route from live_cache_points; seed it from
-- the current value so behaviour is unchanged until an admin edits it.
ALTER TABLE force_crawler_state
    ADD COLUMN IF NOT EXISTS grid_density        integer NOT NULL DEFAULT 2048,
    ADD COLUMN IF NOT EXISTS grid_method         text    NOT NULL DEFAULT 'splat',
    ADD COLUMN IF NOT EXISTS octree_threshold    integer,
    ADD COLUMN IF NOT EXISTS octree_min_node_px  real    NOT NULL DEFAULT 1,
    ADD COLUMN IF NOT EXISTS octree_budget_cap   integer NOT NULL DEFAULT 25000000;

UPDATE force_crawler_state
   SET octree_threshold = live_cache_points
 WHERE octree_threshold IS NULL;

COMMENT ON COLUMN force_crawler_state.grid_density       IS 'Interpolated-grid resolution N (N×N cells); capped at 8192.';
COMMENT ON COLUMN force_crawler_state.grid_method        IS 'Grid interpolation: splat (Gaussian, GPU) or natural (Delaunay).';
COMMENT ON COLUMN force_crawler_state.octree_threshold   IS 'Auto-route to the octree view above this many points.';
COMMENT ON COLUMN force_crawler_state.octree_min_node_px IS 'Potree LOD: min projected node size (px) before culling.';
COMMENT ON COLUMN force_crawler_state.octree_budget_cap  IS 'Potree point-budget hard cap (GPU safety).';

INSERT INTO directus_fields (collection, field, interface, display, options, width, sort, readonly, hidden)
SELECT collection, field, interface, display, options::json, width, sort, readonly, hidden
FROM (VALUES
    ('force_crawler_state', 'grid_density',       'input',         'raw', NULL, 'half', 10, false, false),
    ('force_crawler_state', 'grid_method',        'select-dropdown','raw',
        '{"choices":[{"text":"splat","value":"splat"},{"text":"natural","value":"natural"}]}', 'half', 11, false, false),
    ('force_crawler_state', 'octree_threshold',   'input',         'raw', NULL, 'half', 12, false, false),
    ('force_crawler_state', 'octree_min_node_px', 'input',         'raw', NULL, 'half', 13, false, false),
    ('force_crawler_state', 'octree_budget_cap',  'input',         'raw', NULL, 'half', 14, false, false)
) v(collection, field, interface, display, options, width, sort, readonly, hidden)
WHERE NOT EXISTS (
    SELECT 1 FROM directus_fields f WHERE f.collection = v.collection AND f.field = v.field
);

-- migrate:down
DELETE FROM directus_fields WHERE collection = 'force_crawler_state'
    AND field IN ('grid_density', 'grid_method', 'octree_threshold', 'octree_min_node_px', 'octree_budget_cap');
ALTER TABLE force_crawler_state
    DROP COLUMN IF EXISTS grid_density,
    DROP COLUMN IF EXISTS grid_method,
    DROP COLUMN IF EXISTS octree_threshold,
    DROP COLUMN IF EXISTS octree_min_node_px,
    DROP COLUMN IF EXISTS octree_budget_cap;
ALTER TABLE machining_force_analysis
    DROP COLUMN IF EXISTS grid_octree_status,
    DROP COLUMN IF EXISTS grid_octree_path,
    DROP COLUMN IF EXISTS grid_octree_points,
    DROP COLUMN IF EXISTS grid_octree_error,
    DROP COLUMN IF EXISTS grid_octree_requested_at,
    DROP COLUMN IF EXISTS grid_fidelity,
    DROP COLUMN IF EXISTS grid_arm_ratio,
    DROP COLUMN IF EXISTS grid_cell_mm;
