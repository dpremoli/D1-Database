-- migrate:up
-- Principal investigator becomes a real user reference (was free text). The text
-- column is kept (hidden) as legacy.

ALTER TABLE projects
    ADD COLUMN IF NOT EXISTS principal_investigator UUID REFERENCES directus_users(id) ON DELETE SET NULL;

UPDATE projects p SET principal_investigator = u.id
FROM directus_users u
WHERE p.principal_investigator IS NULL
  AND lower(u.first_name || ' ' || u.last_name) = lower(p.principal_investigator_name);

-- migrate:down
ALTER TABLE projects DROP COLUMN IF EXISTS principal_investigator;
