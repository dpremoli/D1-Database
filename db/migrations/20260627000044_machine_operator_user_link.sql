-- migrate:up
-- Cross-reference Machine_Operators with app users. An operator may be a pure
-- technician (no account) or a researcher who also has a Directus user; link the
-- latter so an operator can be resolved to their app identity.

ALTER TABLE "Machine_Operators"
    ADD COLUMN IF NOT EXISTS user_id UUID REFERENCES directus_users(id) ON DELETE SET NULL;

-- Populate by full-name match.
UPDATE "Machine_Operators" mo SET user_id = u.id
FROM directus_users u
WHERE mo.user_id IS NULL
  AND lower(u.first_name || ' ' || u.last_name) = lower(mo."Name");

-- Known middle-initial case: operator "Sam Jackson" == user "Sam J Jackson".
UPDATE "Machine_Operators"
SET user_id = (SELECT id FROM directus_users WHERE email = 'sjackson13@sheffield.ac.uk')
WHERE "Name" = 'Sam Jackson' AND user_id IS NULL;

-- migrate:down
ALTER TABLE "Machine_Operators" DROP COLUMN IF EXISTS user_id;
