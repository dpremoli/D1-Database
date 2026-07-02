-- migrate:up
-- Replace the free-text operator fields with a reference to Machine_Operators,
-- AND correct the legacy data: the imported operator_name values are mostly the
-- OWNER (researcher), not the operator (technician) — e.g. owner emails landed in
-- operator_name. So we move those to `owner` and only set `operator` for genuine
-- technician names (Nigel …).

ALTER TABLE test_sessions
    ADD COLUMN IF NOT EXISTS operator INTEGER
        REFERENCES "Machine_Operators"(id) ON DELETE SET NULL;

-- 1) operator_name that is a user's email → that user is the OWNER.
UPDATE manufacturing_operations mo
SET owner = u.id
FROM directus_users u
WHERE mo.owner IS NULL AND mo.operator_name = u.email;

UPDATE test_sessions ts
SET owner = u.id
FROM directus_users u
WHERE ts.owner IS NULL AND ts.operator_name = u.email;

-- 2) operator_name that is a researcher's first name (e.g. "Dennis") → OWNER.
UPDATE manufacturing_operations mo
SET owner = u.id
FROM directus_users u
WHERE mo.owner IS NULL
  AND lower(mo.operator_name) = lower(u.first_name)
  AND mo.operator_name NOT ILIKE '%nigel%';

-- 3) Genuine operator (technician): names containing "Nigel" → Nigel Martin.
UPDATE manufacturing_operations mo
SET operator = (SELECT id FROM "Machine_Operators" WHERE "Name" = 'Nigel Martin' LIMIT 1)
WHERE mo.operator_name ILIKE '%nigel%';

-- 4) Any operation still without an owner → fall back to the input sample's owner.
UPDATE manufacturing_operations mo
SET owner = ps.owner
FROM physical_samples ps
WHERE mo.owner IS NULL AND mo.sample_id = ps.sample_id AND ps.owner IS NOT NULL;

-- 5) The legacy operator_name is now superseded (kept as a hidden legacy column).
--    It no longer feeds the operator field, which references Machine_Operators.

-- migrate:down
ALTER TABLE test_sessions DROP COLUMN IF EXISTS operator;
