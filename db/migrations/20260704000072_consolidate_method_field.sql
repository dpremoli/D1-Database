-- migrate:up
-- Resolve the clashing "Manufacturing Route" (free text, where the real data lived)
-- and "Primary Method" (M2O, empty but drives the code) fields into ONE clear
-- "Manufacturing method" M2O. Backfill the method from the route text, relabel the
-- M2O, and hide the free-text route. A sample can carry just a method with no
-- operations (e.g. "we were told it was forged").

UPDATE physical_samples ps
SET primary_method_id = m.method_id
FROM manufacturing_methods m
WHERE ps.primary_method_id IS NULL
  AND ps.manufacturing_route IS NOT NULL AND btrim(ps.manufacturing_route) <> ''
  AND m.method_code = CASE lower(btrim(ps.manufacturing_route))
        WHEN 'fast'     THEN 'MF'
        WHEN 'rolled'   THEN 'MR'
        WHEN 'forged'   THEN 'MO'
        WHEN 'machined' THEN 'MC2'
        WHEN 'hip'      THEN 'MHIP'
        WHEN 'edm'      THEN 'MEDM'
        WHEN 'cast'     THEN 'MCA'
        WHEN 'other'    THEN 'MOTH'
        ELSE 'MUK'
      END;

-- Relabel the M2O and hide the now-redundant free-text route.
UPDATE directus_fields
SET translations = '[{"language":"en-US","translation":"Manufacturing method"}]',
    note = 'How the sample was made — drives the sample code. Leave operations empty if you only know the method (e.g. "forged").'
WHERE collection = 'physical_samples' AND field = 'primary_method_id';

UPDATE directus_fields SET hidden = true
WHERE collection = 'physical_samples' AND field = 'manufacturing_route';

-- migrate:down
UPDATE directus_fields SET hidden = false
WHERE collection = 'physical_samples' AND field = 'manufacturing_route';
UPDATE directus_fields
SET translations = '[{"language":"en-US","translation":"Primary Method (for code)"}]', note = NULL
WHERE collection = 'physical_samples' AND field = 'primary_method_id';
