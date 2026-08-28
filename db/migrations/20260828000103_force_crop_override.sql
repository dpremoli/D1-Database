-- migrate:up
-- Human-corrected crop window. cut_start_idx / cut_end_idx are DERIVED at processing time
-- (process_force.m writes them; force_orchestrator.py rewrites them on every reprocess), so a
-- manual correction can't live there — a reprocess would clobber it. Mirror the outer_diameter /
-- inner_diameter override pattern instead: nullable *_override columns that, when set, win over the
-- derived value everywhere (plotting-window crop lines, and replay's start-of-cut). NULL = follow
-- the derived cut_start_idx / cut_end_idx (so "reset to auto" and reprocessing both keep working).
ALTER TABLE machining_force_analysis
    ADD COLUMN IF NOT EXISTS crop_start_idx_override BIGINT,
    ADD COLUMN IF NOT EXISTS crop_end_idx_override   BIGINT;

COMMENT ON COLUMN machining_force_analysis.crop_start_idx_override IS
    'Human-corrected cut-start sample index; NULL = follow the derived cut_start_idx. Wins over the derived value in the viewer and on replay.';
COMMENT ON COLUMN machining_force_analysis.crop_end_idx_override IS
    'Human-corrected cut-end sample index; NULL = follow the derived cut_end_idx.';

-- migrate:down
ALTER TABLE machining_force_analysis
    DROP COLUMN IF EXISTS crop_start_idx_override,
    DROP COLUMN IF EXISTS crop_end_idx_override;
