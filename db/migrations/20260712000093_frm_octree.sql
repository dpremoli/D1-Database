-- migrate:up
-- Phase 2: full-resolution FRM point clouds as Potree octrees. For ops too large to
-- render client-side (>~3M points), the host builds a Potree octree from the raw .mat
-- at full resolution (MATLAB emits the cloud -> LAS -> PotreeConverter), stores it under
-- the Caddy-served ./infra/octrees/<octree_path>/, and the browser LOD-streams it with a
-- custom viridis-by-attribute material. Request/poll mirrors the Tier-2 render pattern.
ALTER TABLE machining_force_analysis
    ADD COLUMN IF NOT EXISTS octree_status        text,        -- null | pending | processing | done | error
    ADD COLUMN IF NOT EXISTS octree_path          text,        -- served subdir under /octrees/ (usually the operation_id)
    ADD COLUMN IF NOT EXISTS octree_points        bigint,      -- points in the octree (informational)
    ADD COLUMN IF NOT EXISTS octree_error         text,
    ADD COLUMN IF NOT EXISTS octree_requested_at  timestamptz;

-- migrate:down
ALTER TABLE machining_force_analysis
    DROP COLUMN IF EXISTS octree_status,
    DROP COLUMN IF EXISTS octree_path,
    DROP COLUMN IF EXISTS octree_points,
    DROP COLUMN IF EXISTS octree_error,
    DROP COLUMN IF EXISTS octree_requested_at;
