-- migrate:up
-- Diagnostics Workbench Phase 6: mount geometry + H-matrix FRF correction, owned by a setup
-- record rather than duplicated per cut. Component 4 (frame transform) needs a real mount_deg
-- to turn Fc/Ff from "XY under another name" into an actual tool-frame decomposition; the FRF
-- is setup-dependent (workpiece mass, fixturing), so binding it to the cut instead would
-- produce many near-identical files with no way to tell which one was valid for a given cut.
CREATE TABLE tool_setup (
    setup_id    UUID        NOT NULL DEFAULT uuid_generate_v4(),
    setup_code  VARCHAR(64) NOT NULL,
    mount_deg   NUMERIC     NOT NULL DEFAULT 0,  -- static dyno->tool mounting angle (turning)
    h_matrix    JSONB,                            -- optional 3x3 FRF correction, applied not estimated
    notes       TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    version     INTEGER     NOT NULL DEFAULT 1,
    CONSTRAINT tool_setup_pkey PRIMARY KEY (setup_id),
    CONSTRAINT tool_setup_code_unique UNIQUE (setup_code)
);

COMMENT ON TABLE tool_setup IS
    'Mount geometry + H-matrix FRF correction for a dynamometer setup. Cuts reference a setup by FK (machining_force_analysis.tool_setup_id) rather than each carrying a near-duplicate FRF file.';
COMMENT ON COLUMN tool_setup.h_matrix IS
    'Optional 3x3 correction matrix (row-major JSON array of arrays), applied to (Fx,Fy,Fz) before frame_transform. NULL = no correction (identity). Measuring an FRF is a bench procedure, out of scope for this app -- the worker only applies a supplied matrix.';

ALTER TABLE machining_force_analysis
    ADD COLUMN IF NOT EXISTS tool_setup_id UUID REFERENCES tool_setup(setup_id) ON DELETE SET NULL;

COMMENT ON COLUMN machining_force_analysis.tool_setup_id IS
    'Optional link to the tool_setup that supplies this cut''s mount_deg and h_matrix for the diagnostics pipeline. NULL means the pipeline uses the mount_deg=0.0/no-correction defaults, unchanged from Phases 1-5.';

-- migrate:down
ALTER TABLE machining_force_analysis DROP COLUMN IF EXISTS tool_setup_id;
DROP TABLE IF EXISTS tool_setup;
