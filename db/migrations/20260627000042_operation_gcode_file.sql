-- migrate:up
-- A dedicated G-code / NC program file for machining & CNC operations, picked
-- from the Directus File Library (existing uploads) or uploaded inline. This is
-- distinct from the free-text nc_program_text and the legacy nc_program_file_uri;
-- it is a real file reference so the program travels with the operation.

ALTER TABLE manufacturing_operations
    ADD COLUMN IF NOT EXISTS gcode_file UUID REFERENCES directus_files(id) ON DELETE SET NULL;

COMMENT ON COLUMN manufacturing_operations.gcode_file
    IS 'G-code / NC program file (Directus File Library). Shown for machining & CNC operations; pick an existing uploaded file or upload a new one.';

-- migrate:down
ALTER TABLE manufacturing_operations DROP COLUMN IF EXISTS gcode_file;
