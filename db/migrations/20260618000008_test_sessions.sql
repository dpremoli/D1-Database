-- migrate:up
-- Test sessions ledger: documents experimental trials (e.g. force measurement runs).
-- Linked to the heavy-data pipeline (Phase 4): after a multi-GB file is uploaded
-- to MinIO, a session record is created here with the file_storage_pointer URI.
-- The async worker then populates summary_stats and plot_uris.

CREATE TABLE test_sessions (
    session_id              UUID        NOT NULL DEFAULT uuid_generate_v4(),
    sample_id               UUID        NOT NULL,
    equipment_id            UUID,
    insert_edge_id          UUID,
    project_id              UUID,
    operator_name           TEXT,
    session_date            TIMESTAMPTZ,
    test_type               TEXT,
    capture_software        TEXT,
    capture_frequency_khz   NUMERIC(10, 4),
    file_storage_pointer    TEXT,
    file_size_gb            NUMERIC(10, 4),
    summary_stats           JSONB,
    plot_uris               JSONB,
    status                  TEXT        NOT NULL DEFAULT 'registered',
    notes                   TEXT,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    version                 INTEGER     NOT NULL DEFAULT 1,
    CONSTRAINT test_sessions_pkey PRIMARY KEY (session_id),
    CONSTRAINT test_sessions_sample_fkey
        FOREIGN KEY (sample_id)
        REFERENCES physical_samples (sample_id),
    CONSTRAINT test_sessions_equipment_fkey
        FOREIGN KEY (equipment_id)
        REFERENCES equipment (equipment_id),
    CONSTRAINT test_sessions_insert_edge_fkey
        FOREIGN KEY (insert_edge_id)
        REFERENCES insert_edges (edge_id),
    CONSTRAINT test_sessions_project_fkey
        FOREIGN KEY (project_id)
        REFERENCES projects (project_id),
    CONSTRAINT test_sessions_status_check
        CHECK (status IN ('registered', 'processing', 'complete', 'failed'))
);

COMMENT ON TABLE test_sessions
    IS 'Experimental test-session ledger. One row per test run / data-capture event.'
       ' file_storage_pointer links to the raw file in MinIO (10–100 GB).';
COMMENT ON COLUMN test_sessions.sample_id
    IS 'The sample under test. FK to physical_samples.';
COMMENT ON COLUMN test_sessions.insert_edge_id
    IS 'The specific cutting-edge used in this test. FK to insert_edges.';
COMMENT ON COLUMN test_sessions.test_type
    IS 'Category of test, e.g. force_measurement, microstructure, hardness, SEM.';
COMMENT ON COLUMN test_sessions.capture_software
    IS 'Data-capture app and version, e.g. MATLAB ABFP 0.18.';
COMMENT ON COLUMN test_sessions.capture_frequency_khz
    IS 'Sampling frequency in kilohertz (e.g. 25.6). Required to interpret raw files.';
COMMENT ON COLUMN test_sessions.file_storage_pointer
    IS 'MinIO S3 URI for the raw data file, e.g. s3://d1-data/AI4340/9-AA-MR-...';
COMMENT ON COLUMN test_sessions.file_size_gb
    IS 'Raw file size in gigabytes as reported by the capture client.';
COMMENT ON COLUMN test_sessions.summary_stats
    IS 'JSON statistics written back by the async heavy-data worker after parsing.';
COMMENT ON COLUMN test_sessions.plot_uris
    IS 'JSON array of MinIO URIs for SVG/PNG plots rendered by the worker.';
COMMENT ON COLUMN test_sessions.status
    IS 'Pipeline status: registered | processing | complete | failed.';

-- migrate:down

DROP TABLE IF EXISTS test_sessions CASCADE;
