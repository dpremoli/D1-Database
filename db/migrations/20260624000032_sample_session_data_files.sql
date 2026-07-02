-- migrate:up
-- M2M junctions linking physical_samples and test_sessions to files in the
-- Directus File Library (directus_files), mirroring operation_data_files. Archive
-- files are registered as pointer rows by scripts/index_archive.py; these tables
-- record which file belongs to which sample / test session.

CREATE TABLE sample_data_files (
    id                UUID NOT NULL DEFAULT uuid_generate_v4(),
    sample_id         UUID NOT NULL REFERENCES physical_samples(sample_id) ON DELETE CASCADE,
    directus_files_id UUID NOT NULL REFERENCES directus_files(id) ON DELETE CASCADE,
    CONSTRAINT sample_data_files_pkey PRIMARY KEY (id),
    CONSTRAINT sample_data_files_unique UNIQUE (sample_id, directus_files_id)
);

COMMENT ON TABLE sample_data_files IS
    'M2M junction: data files (Directus File Library, incl. SMB-archive pointers) linked to a physical sample.';

CREATE INDEX sample_data_files_sample_id_idx ON sample_data_files (sample_id);
CREATE INDEX sample_data_files_file_id_idx   ON sample_data_files (directus_files_id);

CREATE TABLE session_data_files (
    id                UUID NOT NULL DEFAULT uuid_generate_v4(),
    session_id        UUID NOT NULL REFERENCES test_sessions(session_id) ON DELETE CASCADE,
    directus_files_id UUID NOT NULL REFERENCES directus_files(id) ON DELETE CASCADE,
    CONSTRAINT session_data_files_pkey PRIMARY KEY (id),
    CONSTRAINT session_data_files_unique UNIQUE (session_id, directus_files_id)
);

COMMENT ON TABLE session_data_files IS
    'M2M junction: data files (Directus File Library, incl. SMB-archive pointers) linked to a test session.';

CREATE INDEX session_data_files_session_id_idx ON session_data_files (session_id);
CREATE INDEX session_data_files_file_id_idx     ON session_data_files (directus_files_id);

-- migrate:down
DROP TABLE IF EXISTS session_data_files;
DROP TABLE IF EXISTS sample_data_files;
