-- migrate:up
-- Audit trail for corrections made to metadata INSIDE archive files (e.g. a stale
-- metadata.SampleName in a .mat capture). Distinct from audit_logs (which is
-- trigger-driven for core DB tables) since these edits happen to files living on
-- the read-only-mounted SMB archive, outside any DB table's row lifecycle.

CREATE TABLE archive_metadata_edits (
    id                UUID NOT NULL DEFAULT uuid_generate_v4(),
    directus_files_id UUID REFERENCES directus_files(id) ON DELETE SET NULL,
    archive_path      text NOT NULL,
    field_path        text NOT NULL,      -- e.g. 'metadata.SampleName'
    old_value         text,
    new_value         text NOT NULL,
    reason            text,
    edited_by         text,
    edited_at         timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT archive_metadata_edits_pkey PRIMARY KEY (id)
);

COMMENT ON TABLE archive_metadata_edits IS
    'Audit trail of in-place corrections made to metadata fields inside archive files (e.g. stale SampleName in a .mat capture). The archive itself has no version history, so this table is the only record of what changed.';

CREATE INDEX archive_metadata_edits_file_idx ON archive_metadata_edits (directus_files_id);

-- migrate:down
DROP TABLE IF EXISTS archive_metadata_edits;
