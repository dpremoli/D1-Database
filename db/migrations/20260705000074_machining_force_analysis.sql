-- migrate:up
-- Per-.mat force-analysis results for machining operations. One row per source
-- force file (directus_files_id UNIQUE); the host orchestrator (scripts/
-- force_orchestrator.py) runs scripts/matlab/process_force.m read-only over the
-- archive .mat, then ingests the JSON metrics + downsampled series/fft here and
-- uploads the FRM fingerprint PNG to Directus local storage (frm_file). The
-- `status` column doubles as the work queue; `fingerprint` mirrors the source
-- file's light fingerprint so a moved/rewritten file is reprocessed.
--
-- Read-only w.r.t. the archive: nothing here ever writes back to the .mat.

CREATE TABLE machining_force_analysis (
    id                UUID        NOT NULL DEFAULT uuid_generate_v4(),
    operation_id      UUID        NOT NULL REFERENCES manufacturing_operations(operation_id) ON DELETE CASCADE,
    directus_files_id UUID        NOT NULL REFERENCES directus_files(id) ON DELETE CASCADE,  -- source .mat
    status            VARCHAR(16) NOT NULL DEFAULT 'pending',
    fingerprint       TEXT,          -- source file fingerprint at process time (staleness check)
    error_message     TEXT,

    -- cut parameters read from the .mat `metadata` variable
    file_version      NUMERIC,
    sample_rate       INTEGER,
    feed              NUMERIC,
    cut_diameter      NUMERIC,
    surface_speed     NUMERIC,
    depth_of_cut      NUMERIC,
    max_rpm           NUMERIC,
    dyno_gain         NUMERIC,        -- surfaced so a gain of 1 (uncalibrated) is visible

    -- derived scalar metrics
    n_raw             BIGINT,
    cut_start_idx     BIGINT,
    cut_end_idx       BIGINT,
    peak_fx           NUMERIC,
    peak_fy           NUMERIC,
    peak_fz           NUMERIC,
    mean_rpm          NUMERIC,

    -- payloads for the viewer (TOASTed out-of-line by Postgres; not fetched in lists)
    series            JSONB,          -- downsampled min/max envelope of Fx/Fy/Fz
    fft               JSONB,          -- per-axis amplitude spectrum (<=2 kHz)
    frm_file          UUID REFERENCES directus_files(id) ON DELETE SET NULL,  -- uploaded FRM PNG

    -- provenance
    matlab_version    TEXT,
    processed_at      TIMESTAMPTZ,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT machining_force_analysis_pkey        PRIMARY KEY (id),
    CONSTRAINT machining_force_analysis_file_unique UNIQUE (directus_files_id),
    CONSTRAINT machining_force_analysis_status_chk
        CHECK (status IN ('pending', 'processing', 'done', 'error', 'skipped'))
);

COMMENT ON TABLE machining_force_analysis IS
    'ABFPA-faithful force-analysis results per machining .mat file (FRM fingerprint, force envelopes, spectra, cut metrics). Populated read-only by scripts/force_orchestrator.py.';
COMMENT ON COLUMN machining_force_analysis.status IS
    'Work-queue state: pending -> processing -> done | error | skipped.';
COMMENT ON COLUMN machining_force_analysis.dyno_gain IS
    'Dynamometer gain (N/V) stored in the file metadata. A value of 1 means the capture was effectively uncalibrated.';

CREATE INDEX machining_force_analysis_operation_id_idx ON machining_force_analysis (operation_id);
CREATE INDEX machining_force_analysis_status_idx       ON machining_force_analysis (status);

-- migrate:down
DROP TABLE IF EXISTS machining_force_analysis;
