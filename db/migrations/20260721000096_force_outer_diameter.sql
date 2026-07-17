-- migrate:up
-- Outer-diameter override, completing the donut/diaphragm geometry pair (see
-- 20260717000095_force_inner_diameter): the .mat metadata's CutDiameter is sometimes wrong
-- for an op, and until now editing "Diameter" only changed the client-side Lite plot —
-- host rebuilds (PNG / octree / grid / live cache) kept using the metadata value. NULL/0 =
-- use the .mat metadata; > 0 overrides it everywhere the spiral is computed.
ALTER TABLE machining_force_analysis
    ADD COLUMN IF NOT EXISTS outer_diameter real;

COMMENT ON COLUMN machining_force_analysis.outer_diameter IS
    'Outer (cut) diameter override in mm; NULL/0 = use the .mat metadata CutDiameter.';

-- migrate:down
ALTER TABLE machining_force_analysis DROP COLUMN IF EXISTS outer_diameter;
