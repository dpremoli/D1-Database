-- migrate:up
-- Facilities reference table + equipment.facility_id FK, so equipment can be
-- grouped/filtered by lab (drives the tiered facility -> machine picker) and an
-- image_url for externally-sourced instrument photos (the existing `image` file
-- field stays for uploaded photos).

CREATE TABLE IF NOT EXISTS facilities (
    facility_id UUID        NOT NULL DEFAULT uuid_generate_v4(),
    name        TEXT        NOT NULL,
    code        VARCHAR(16) NOT NULL,
    notes       TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT facilities_pkey PRIMARY KEY (facility_id),
    CONSTRAINT facilities_code_unique UNIQUE (code),
    CONSTRAINT facilities_name_unique UNIQUE (name)
);

COMMENT ON TABLE facilities IS
    'Physical labs / centres that house equipment. Used to group and filter the machine picker.';
COMMENT ON COLUMN facilities.code IS 'Short unique facility code, e.g. SORBY, RDC, RTC, METLAB, MECHLAB.';

-- Seed the five facilities from the master equipment list.
INSERT INTO facilities (name, code, notes) VALUES
    ('Sorby Centre',               'SORBY',   'Electron microscopy, FIB, EPMA and specimen preparation.'),
    ('Royce Discovery Centre',     'RDC',     'Additive manufacturing and powder handling.'),
    ('Royce Translational Centre', 'RTC',     'Powder production (atomiser), HIP, VIM and thermomechanical processing.'),
    ('Metallography Lab',          'METLAB',  'Sectioning, mounting, grinding/polishing and optical microscopy.'),
    ('Mechanical Testing Lab',     'MECHLAB', 'Tensile / compression, dilatometry and thermomechanical testing.')
ON CONFLICT (code) DO NOTHING;

ALTER TABLE equipment
    ADD COLUMN IF NOT EXISTS facility_id UUID,
    ADD COLUMN IF NOT EXISTS image_url   TEXT;

COMMENT ON COLUMN equipment.facility_id IS 'Lab / centre that houses this machine. Drives the tiered facility -> machine picker.';
COMMENT ON COLUMN equipment.image_url IS 'URL of an externally-sourced photo of the machine (manufacturer/facility page). The `image` file field is for uploaded photos.';

ALTER TABLE equipment
    DROP CONSTRAINT IF EXISTS equipment_facility_id_fkey;
ALTER TABLE equipment
    ADD CONSTRAINT equipment_facility_id_fkey
        FOREIGN KEY (facility_id) REFERENCES facilities (facility_id) ON DELETE SET NULL;

-- migrate:down
ALTER TABLE equipment DROP CONSTRAINT IF EXISTS equipment_facility_id_fkey;
ALTER TABLE equipment DROP COLUMN IF EXISTS image_url;
ALTER TABLE equipment DROP COLUMN IF EXISTS facility_id;
DROP TABLE IF EXISTS facilities CASCADE;
