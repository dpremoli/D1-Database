-- migrate:up
-- External data-file links for a manufacturing operation (force .mat/.csv etc. that
-- live on the lab network share, not uploaded into Directus). Lets one operation carry
-- many file links without copying the data.
CREATE TABLE operation_files (
    file_id      UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    operation_id UUID NOT NULL REFERENCES manufacturing_operations(operation_id) ON DELETE CASCADE,
    file_path    TEXT NOT NULL,
    file_name    TEXT,
    file_kind    TEXT,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT operation_files_unique UNIQUE (operation_id, file_path)
);
CREATE INDEX idx_operation_files_operation_id ON operation_files (operation_id);

COMMENT ON TABLE operation_files
    IS 'External file links (network-share paths) attached to a manufacturing operation.';

-- migrate:down
DROP TABLE IF EXISTS operation_files;
