-- migrate:up
-- Diagnostics Workbench: a third Potree octree variant per operation, carrying derived
-- analysis attributes (TSA residual, radial-detrended z-score, and later the spatial
-- statistics) as float32 LAS extra dims alongside the force axes. Built by the diag handler
-- in scripts/force_orchestrator.py and published under ./infra/octrees/diag/<diag_path>/.
-- Request/poll mirrors the octree and grid-octree patterns exactly.
ALTER TABLE machining_force_analysis
    ADD COLUMN IF NOT EXISTS diag_status        text,        -- null | pending | processing | done | error
    ADD COLUMN IF NOT EXISTS diag_path          text,        -- served subdir under /octrees/diag/ (usually the operation_id)
    ADD COLUMN IF NOT EXISTS diag_points        bigint,      -- points in the diag octree (informational)
    ADD COLUMN IF NOT EXISTS diag_error         text,
    ADD COLUMN IF NOT EXISTS diag_requested_at  timestamptz,
    ADD COLUMN IF NOT EXISTS diag_version       integer,     -- analysis version; bump to invalidate and requeue
    ADD COLUMN IF NOT EXISTS diag_metrics       jsonb;       -- order spectrum, TSA signature, validity limits, provenance

-- migrate:down
ALTER TABLE machining_force_analysis
    DROP COLUMN IF EXISTS diag_status,
    DROP COLUMN IF EXISTS diag_path,
    DROP COLUMN IF EXISTS diag_points,
    DROP COLUMN IF EXISTS diag_error,
    DROP COLUMN IF EXISTS diag_requested_at,
    DROP COLUMN IF EXISTS diag_version,
    DROP COLUMN IF EXISTS diag_metrics;
