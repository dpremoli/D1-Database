-- migrate:up
-- Operations gain a researcher owner (≠ operator/technician) and an explicit
-- input → output sample model: some steps consume a workpiece (machining), some
-- produce a new sample (additive/FAST), and FAST can do both.

-- ── Ownership (researcher), separate from operator_name (technician) ──────────
ALTER TABLE manufacturing_operations ADD COLUMN IF NOT EXISTS owner UUID;  -- directus_users, no hard FK (ADR-0002)
ALTER TABLE test_sessions            ADD COLUMN IF NOT EXISTS owner UUID;
COMMENT ON COLUMN manufacturing_operations.owner IS
    'Researcher who owns this operation (defaults to the creating user; editable). Distinct from operator_name (the technician who ran it).';
COMMENT ON COLUMN test_sessions.owner IS
    'Researcher who owns this test session (defaults to the creating user; editable).';

-- ── Input / output samples ───────────────────────────────────────────────────
-- sample_id becomes the INPUT (workpiece consumed/acted on) and is now optional.
ALTER TABLE manufacturing_operations ALTER COLUMN sample_id DROP NOT NULL;

ALTER TABLE manufacturing_operations
    ADD COLUMN IF NOT EXISTS output_sample_id UUID
        REFERENCES physical_samples(sample_id) ON DELETE SET NULL;
COMMENT ON COLUMN manufacturing_operations.sample_id IS
    'Input sample / workpiece consumed or acted on (machining, FAST-embed). NULL for purely generative steps (additive from powder).';
COMMENT ON COLUMN manufacturing_operations.output_sample_id IS
    'New sample produced by this operation (additive, FAST). NULL when the step only modifies the input in place (machining).';

-- Every operation must reference at least one sample (input or output).
ALTER TABLE manufacturing_operations DROP CONSTRAINT IF EXISTS manufacturing_operations_has_sample;
ALTER TABLE manufacturing_operations ADD  CONSTRAINT manufacturing_operations_has_sample
    CHECK (sample_id IS NOT NULL OR output_sample_id IS NOT NULL);

CREATE INDEX IF NOT EXISTS manufacturing_operations_output_sample_idx
    ON manufacturing_operations (output_sample_id);

-- ── Auto-record input → output lineage in sample_genealogy ────────────────────
CREATE OR REPLACE FUNCTION mfg_op_link_genealogy() RETURNS trigger AS $$
DECLARE
    rel  TEXT := 'derived_from';
    code TEXT;
BEGIN
    IF NEW.sample_id IS NOT NULL AND NEW.output_sample_id IS NOT NULL
       AND NEW.sample_id <> NEW.output_sample_id THEN
        SELECT method_code INTO code FROM manufacturing_methods WHERE method_id = NEW.method_id;
        rel := CASE
            WHEN code IN ('MF','MHIP')                       THEN 'sintered_from'
            WHEN code IN ('MC','MM','MC2','MEDM','MCO','MX','MS') THEN 'cut_from'
            ELSE 'derived_from'
        END;
        INSERT INTO sample_genealogy (child_sample_id, parent_sample_id, relationship_type, notes)
        VALUES (NEW.output_sample_id, NEW.sample_id, rel,
                'Auto-linked from manufacturing operation ' || COALESCE(NEW.pass_code, NEW.operation_id::text))
        ON CONFLICT (child_sample_id, parent_sample_id) DO NOTHING;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS mfg_op_genealogy ON manufacturing_operations;
CREATE TRIGGER mfg_op_genealogy
    AFTER INSERT OR UPDATE OF sample_id, output_sample_id, method_id ON manufacturing_operations
    FOR EACH ROW EXECUTE FUNCTION mfg_op_link_genealogy();

-- migrate:down
DROP TRIGGER IF EXISTS mfg_op_genealogy ON manufacturing_operations;
DROP FUNCTION IF EXISTS mfg_op_link_genealogy();
DROP INDEX IF EXISTS manufacturing_operations_output_sample_idx;
ALTER TABLE manufacturing_operations DROP CONSTRAINT IF EXISTS manufacturing_operations_has_sample;
ALTER TABLE manufacturing_operations DROP COLUMN IF EXISTS output_sample_id;
ALTER TABLE manufacturing_operations ALTER COLUMN sample_id SET NOT NULL;
ALTER TABLE test_sessions            DROP COLUMN IF EXISTS owner;
ALTER TABLE manufacturing_operations DROP COLUMN IF EXISTS owner;
