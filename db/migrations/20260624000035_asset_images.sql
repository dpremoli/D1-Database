-- migrate:up
-- Image for equipment, tools, and insert types. A directus_files reference (the
-- Directus File Library is backed by MinIO), so pasting a URL into the picker
-- downloads the image into MinIO on save → stored locally → available offline.

ALTER TABLE equipment    ADD COLUMN IF NOT EXISTS image UUID REFERENCES directus_files(id) ON DELETE SET NULL;
ALTER TABLE tools        ADD COLUMN IF NOT EXISTS image UUID REFERENCES directus_files(id) ON DELETE SET NULL;
ALTER TABLE insert_types ADD COLUMN IF NOT EXISTS image UUID REFERENCES directus_files(id) ON DELETE SET NULL;

COMMENT ON COLUMN equipment.image    IS 'Photo of the machine (Directus File Library / MinIO). URL imports are downloaded for offline viewing.';
COMMENT ON COLUMN tools.image        IS 'Photo of the tool (Directus File Library / MinIO).';
COMMENT ON COLUMN insert_types.image IS 'Photo of the insert type (Directus File Library / MinIO).';

-- migrate:down
ALTER TABLE insert_types DROP COLUMN IF EXISTS image;
ALTER TABLE tools        DROP COLUMN IF EXISTS image;
ALTER TABLE equipment    DROP COLUMN IF EXISTS image;
