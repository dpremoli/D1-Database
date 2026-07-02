-- migrate:up
-- 1) Test category (NDE / destructive / dynamic) on test_sessions, auto-inferred
--    in the UI from test_type by the d1-test-category interface — mirrors how
--    process_category is inferred from the manufacturing method.
-- 2) Expand test_type to cover the NDE / destructive / dynamic methods.
-- 3) equipment.capabilities: which process categories and test categories a
--    machine supports, used to filter the Machine picker on operations/tests.

ALTER TABLE test_sessions
    ADD COLUMN IF NOT EXISTS test_category TEXT
        CHECK (test_category IN ('nde','destructive','dynamic','other'));

COMMENT ON COLUMN test_sessions.test_category IS
    'Test family inferred from test_type: nde / destructive / dynamic. Drives nothing on its own — test_type drives the inline parameter fields — but groups tests and filters the Machine picker.';

-- Widen test_type: add NDE (alicona, clemx, tem, ct_scan) and dynamic (dma) methods.
ALTER TABLE test_sessions DROP CONSTRAINT IF EXISTS test_sessions_test_type_check;
ALTER TABLE test_sessions ADD  CONSTRAINT test_sessions_test_type_check
    CHECK (test_type IN (
        -- destructive
        'tensile','hardness','charpy','compression','tribology',
        -- NDE / imaging
        'optical_microscopy','sem','tem','xrd','alicona','clemx','dct','ct_scan',
        -- dynamic
        'fatigue','creep','dma',
        'other'
    ));

-- equipment capability tags (CSV: machining/sintering/heat_treatment/deformation/
-- additive + nde/destructive/dynamic). CSV so a `_contains` filter on the Machine
-- picker matches reliably (no capability value is a substring of another).
ALTER TABLE equipment
    ADD COLUMN IF NOT EXISTS capabilities TEXT;

COMMENT ON COLUMN equipment.capabilities IS
    'CSV of process/test categories this machine can perform (machining, sintering, heat_treatment, deformation, additive, nde, destructive, dynamic). Used to filter the Machine picker on operations and test sessions.';

-- migrate:down
ALTER TABLE equipment     DROP COLUMN IF EXISTS capabilities;
ALTER TABLE test_sessions DROP CONSTRAINT IF EXISTS test_sessions_test_type_check;
ALTER TABLE test_sessions DROP COLUMN IF EXISTS test_category;
