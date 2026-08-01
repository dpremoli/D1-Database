-- migrate:up
-- Fields supporting the FAST/SPS log import + future scheduled sync.
-- source_run_uid: deterministic key (machine|date|time|batch) for idempotent
--   re-imports — a press cycle is unique by machine + timestamp.
-- sintering_mass_grams: the log's "Mass (g)" (no inline sintering field existed).
-- source_system: provenance tag (e.g. 'fast_log').

ALTER TABLE manufacturing_operations
    ADD COLUMN IF NOT EXISTS source_run_uid    TEXT,
    ADD COLUMN IF NOT EXISTS source_system     TEXT,
    ADD COLUMN IF NOT EXISTS sintering_mass_grams NUMERIC(10,3),
    -- Feedstock alloy of the run. Operations had no material link (material lived
    -- only on samples); FAST runs record the powder/charge material directly.
    ADD COLUMN IF NOT EXISTS material_id       UUID REFERENCES materials(material_id) ON DELETE SET NULL;

CREATE UNIQUE INDEX IF NOT EXISTS manufacturing_operations_source_run_uid_key
    ON manufacturing_operations (source_run_uid)
    WHERE source_run_uid IS NOT NULL;

-- Imported log runs (e.g. FAST) have no sample record in the source data, so
-- allow a sample-less operation when it is an imported row (source_system set).
ALTER TABLE manufacturing_operations DROP CONSTRAINT IF EXISTS manufacturing_operations_has_sample;
ALTER TABLE manufacturing_operations ADD CONSTRAINT manufacturing_operations_has_sample
    CHECK (sample_id IS NOT NULL OR output_sample_id IS NOT NULL OR source_system IS NOT NULL);

COMMENT ON COLUMN manufacturing_operations.source_run_uid
    IS 'Deterministic dedup key for imported runs (e.g. sha1 of machine|date|time|batch). Unique.';
COMMENT ON COLUMN manufacturing_operations.sintering_mass_grams
    IS 'Charge mass for the sinter run, grams (FAST log "Mass (g)").';
COMMENT ON COLUMN manufacturing_operations.source_system
    IS 'Provenance of an imported row, e.g. fast_log.';

-- migrate:down
ALTER TABLE manufacturing_operations DROP CONSTRAINT IF EXISTS manufacturing_operations_has_sample;
ALTER TABLE manufacturing_operations ADD CONSTRAINT manufacturing_operations_has_sample
    CHECK (sample_id IS NOT NULL OR output_sample_id IS NOT NULL);
DROP INDEX IF EXISTS manufacturing_operations_source_run_uid_key;
ALTER TABLE manufacturing_operations
    DROP COLUMN IF EXISTS source_run_uid,
    DROP COLUMN IF EXISTS source_system,
    DROP COLUMN IF EXISTS sintering_mass_grams,
    DROP COLUMN IF EXISTS material_id;
