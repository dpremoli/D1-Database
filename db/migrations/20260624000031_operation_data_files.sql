-- migrate:up
-- M2M junction linking manufacturing_operations to files in the Directus File
-- Library (directus_files). Files on the read-only SMB archive are registered as
-- pointer rows by scripts/index_archive.py; this table records which archive file
-- belongs to which operation. Background plugins resolve the link to bytes via
-- the directus_files row (storage='star', metadata.archive_path).

CREATE TABLE operation_data_files (
    id                UUID NOT NULL DEFAULT uuid_generate_v4(),
    operation_id      UUID NOT NULL REFERENCES manufacturing_operations(operation_id) ON DELETE CASCADE,
    directus_files_id UUID NOT NULL REFERENCES directus_files(id) ON DELETE CASCADE,
    CONSTRAINT operation_data_files_pkey PRIMARY KEY (id),
    CONSTRAINT operation_data_files_unique UNIQUE (operation_id, directus_files_id)
);

COMMENT ON TABLE operation_data_files IS
    'M2M junction: data files (Directus File Library, incl. SMB-archive pointers) linked to a manufacturing operation.';

CREATE INDEX operation_data_files_operation_id_idx ON operation_data_files (operation_id);
CREATE INDEX operation_data_files_file_id_idx      ON operation_data_files (directus_files_id);

-- migrate:down
DROP TABLE IF EXISTS operation_data_files;
