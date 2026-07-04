-- migrate:up
-- Move the real AppSheet legacy note (legacy_notes) into the notes field. Existing
-- notes on imported rows is just a "Imported from legacy…" banner, so put the
-- meaningful legacy text first, keep any real note below, then clear legacy_notes
-- and hide the field.
UPDATE physical_samples
SET notes = legacy_notes || CASE WHEN notes IS NOT NULL AND btrim(notes) <> '' THEN E'\n\n' || notes ELSE '' END
WHERE legacy_notes IS NOT NULL AND btrim(legacy_notes) <> '';
UPDATE physical_samples SET legacy_notes = NULL WHERE legacy_notes IS NOT NULL;
UPDATE directus_fields SET hidden = true WHERE collection = 'physical_samples' AND field = 'legacy_notes';

-- migrate:down
UPDATE directus_fields SET hidden = false WHERE collection = 'physical_samples' AND field = 'legacy_notes';
