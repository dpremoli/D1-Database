-- migrate:up
-- Scalar discriminator that drives which typed parameter panel is shown when
-- creating a manufacturing operation. Directus field conditions work reliably
-- on a scalar enum in the same collection (like test_sessions.test_type) but
-- NOT on a M2O relation (method_id) — the form only holds the FK, so relational
-- conditions never evaluate. This column gives the form a scalar to condition on.

ALTER TABLE manufacturing_operations
    ADD COLUMN IF NOT EXISTS process_category TEXT
        CHECK (process_category IN
            ('machining','sintering','heat_treatment','deformation','additive'));

COMMENT ON COLUMN manufacturing_operations.process_category IS
    'Process family that selects the typed parameter panel in the UI '
    '(machining / sintering / heat_treatment / deformation / additive).';

-- Best-effort back-fill from the linked manufacturing method so existing rows
-- get the right panel without manual editing.
UPDATE manufacturing_operations mo
SET process_category = CASE
        WHEN mm.method_code IN ('MC','MM','MC2','MEDM','MCO','MX','MS') THEN 'machining'
        WHEN mm.method_code IN ('MF','MHIP')                            THEN 'sintering'
        WHEN mm.method_code IN ('HT')                                   THEN 'heat_treatment'
        WHEN mm.method_code IN ('MO','MR')                              THEN 'deformation'
        WHEN mm.method_code IN ('MAM','MW','MAE')                       THEN 'additive'
        ELSE NULL
    END
FROM manufacturing_methods mm
WHERE mo.method_id = mm.method_id
  AND mo.process_category IS NULL;

-- migrate:down
ALTER TABLE manufacturing_operations DROP COLUMN IF EXISTS process_category;
