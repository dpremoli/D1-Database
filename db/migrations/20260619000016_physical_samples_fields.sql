-- migrate:up
-- Add per-field columns that the Phase 8 migration erroneously concatenated
-- into the notes blob (nickname, location, surface_finish, legacy_notes).

ALTER TABLE physical_samples
    ADD COLUMN IF NOT EXISTS nickname       TEXT,
    ADD COLUMN IF NOT EXISTS location       TEXT,
    ADD COLUMN IF NOT EXISTS surface_finish TEXT,
    ADD COLUMN IF NOT EXISTS legacy_notes   TEXT;

COMMENT ON COLUMN physical_samples.nickname
    IS 'Informal human label for the sample (e.g. "FAST Control", "UD Rolled Control").';
COMMENT ON COLUMN physical_samples.location
    IS 'Physical storage location of the sample.';
COMMENT ON COLUMN physical_samples.surface_finish
    IS 'Surface finish state, e.g. Mirror, Machined, As-sintered.';
COMMENT ON COLUMN physical_samples.legacy_notes
    IS 'Free-text notes carried over verbatim from the legacy AppSheet Inventory sheet.';

-- Backfill: extract the structured sub-fields from the pipe-delimited notes blob
-- that the Phase 8 migration script wrote.
UPDATE physical_samples
SET
    nickname       = btrim((regexp_match(notes, 'Nickname: ([^|]+)'))[1]),
    legacy_notes   = btrim((regexp_match(notes, 'Notes: ([^|]+)'))[1]),
    location       = btrim((regexp_match(notes, 'Location: ([^|]+)'))[1]),
    surface_finish = btrim((regexp_match(notes, 'Surface finish: ([^|]+)'))[1]),
    notes          = 'Imported from legacy AppSheet/Sheets export (Phase 8 migration).'
WHERE notes LIKE 'Imported from legacy AppSheet%';

-- migrate:down
ALTER TABLE physical_samples
    DROP COLUMN IF EXISTS nickname,
    DROP COLUMN IF EXISTS location,
    DROP COLUMN IF EXISTS surface_finish,
    DROP COLUMN IF EXISTS legacy_notes;
