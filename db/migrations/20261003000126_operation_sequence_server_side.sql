-- migrate:up
-- Review finding 4.5: operation numbers and operation codes were built in the browser.
--
-- Before this migration:
--   * the d1-operation-sequence Directus hook filled operation_sequence with max+1 for the sample
--     AFTER the form had already composed pass_code, so a new heat-treatment / deformation /
--     additive operation was stored with a code that lacked its number (e.g. "5-AA-MF-...-HTA-800C"
--     instead of "...-HTA1-800C"), and nothing rewrote the code;
--   * the read-then-write was not locked, so two operations created at once on one sample got the
--     same number;
--   * the sintering counter in the interface was COUNT(sintering ops)+1, which hands out a number
--     that already exists once any earlier operation has been deleted.
-- ADR-0002 says nothing the system depends on lives in Directus, so both numbers are now assigned
-- by a BEFORE trigger on manufacturing_operations:
--
--   operation_sequence  NULL on insert and sample_id set  ->  max(operation_sequence)+1 for that
--                       sample, under pg_advisory_xact_lock keyed by the sample. A value the caller
--                       supplies (e.g. a machining pass number) is never overwritten.
--   pass_code           the interface still composes the readable part of the code (alloy, method,
--                       parameters; see d1-operation-code), but leaves the two database-owned
--                       numbers as placeholders that the trigger fills in:
--                         {seq}  ->  the row's operation_sequence (empty when there is none, which
--                                    is what the interface produced for a sample-less operation);
--                         {mf}   ->  the next sintering "MF" number: 1 + the highest MF number found
--                                    in the pass_code of any sintering operation, under a global
--                                    advisory lock. It is a max+1 over live codes, so a deleted
--                                    middle number is never handed out again while a higher one
--                                    exists.
--                       A pass_code without a placeholder (a typed override, an import) is stored
--                       exactly as given. The code format is unchanged.
--
-- The trigger also runs on UPDATE (and returns at once unless pass_code changed) so that
-- "regenerate" on an existing operation cannot store a raw placeholder. It is deliberately not
-- declared UPDATE OF pass_code: a column-list trigger would block ALTER COLUMN pass_code TYPE, which
-- the natural-sort collation migration's down section needs.
--
-- Not done here: UNIQUE(pass_code) and UNIQUE(sample_id, operation_sequence). Production may already
-- hold duplicates; that needs a data check first (see the review-fix plan, section 2).
--
-- Deadlocks: a single statement that inserts operations for several samples takes the sample locks
-- in row order; two such statements with the samples in opposite order could deadlock. Postgres
-- aborts one of them with a clear error. The interface and the API insert one row at a time.

CREATE FUNCTION trg_manufacturing_operations_assign_numbers() RETURNS trigger
    LANGUAGE plpgsql
    SET search_path = pg_catalog, public
AS $$
DECLARE
    v_mf BIGINT;
BEGIN
    IF TG_OP = 'UPDATE' AND NEW.pass_code IS NOT DISTINCT FROM OLD.pass_code THEN
        RETURN NEW;
    END IF;

    -- Per-sample operation number.
    IF NEW.operation_sequence IS NULL
       AND NEW.sample_id IS NOT NULL
       AND (TG_OP = 'INSERT' OR NEW.pass_code LIKE '%{seq}%')
    THEN
        PERFORM pg_catalog.pg_advisory_xact_lock(
            pg_catalog.hashtextextended('manufacturing_operations.sample:' || NEW.sample_id::text, 0));
        SELECT COALESCE(max(mo.operation_sequence), 0) + 1
        INTO   NEW.operation_sequence
        FROM   public.manufacturing_operations mo
        WHERE  mo.sample_id = NEW.sample_id;
    END IF;

    -- Placeholders in the client-composed code.
    IF NEW.pass_code LIKE '%{seq}%' THEN
        NEW.pass_code := replace(NEW.pass_code, '{seq}', COALESCE(NEW.operation_sequence::text, ''));
    END IF;

    IF NEW.pass_code LIKE '%{mf}%' THEN
        PERFORM pg_catalog.pg_advisory_xact_lock(
            pg_catalog.hashtextextended('manufacturing_operations.sintering_mf_counter', 0));
        SELECT COALESCE(max((substring(mo.pass_code FROM '(?:^|-)MF(\d{1,9})(?:-|$)'))::bigint), 0) + 1
        INTO   v_mf
        FROM   public.manufacturing_operations mo
        WHERE  mo.process_category = 'sintering'
          AND  mo.operation_id IS DISTINCT FROM NEW.operation_id;
        NEW.pass_code := replace(NEW.pass_code, '{mf}', v_mf::text);
    END IF;

    RETURN NEW;
END;
$$;

COMMENT ON FUNCTION trg_manufacturing_operations_assign_numbers() IS
    'BEFORE INSERT / UPDATE on manufacturing_operations (UPDATE only when pass_code changes): assigns operation_sequence '
    '(max+1 per sample, advisory-locked) when NULL, and replaces the {seq} and {mf} placeholders '
    'in a client-composed pass_code with the operation number and the next sintering MF number '
    '(review 4.5). Replaces the d1-operation-sequence Directus hook.';

CREATE TRIGGER mfg_op_assign_numbers
    BEFORE INSERT OR UPDATE ON manufacturing_operations
    FOR EACH ROW EXECUTE FUNCTION trg_manufacturing_operations_assign_numbers();

COMMENT ON TRIGGER mfg_op_assign_numbers ON manufacturing_operations IS
    'Assigns operation_sequence and fills the {seq} / {mf} placeholders of pass_code server-side (review 4.5).';

COMMENT ON COLUMN manufacturing_operations.operation_sequence IS
    'Ordering of this operation within the sample lifecycle (1 = first). Left NULL on insert, it is '
    'assigned by the database as max+1 for the sample; a supplied value (e.g. a machining pass '
    'number) is kept.';

COMMENT ON COLUMN manufacturing_operations.pass_code IS
    'Human-readable operation code, e.g. 9-AA-MR-2023-03-23-F9 or 22-04-21-MF1-950C_11kN_20dia. '
    'The placeholders {seq} (operation_sequence) and {mf} (next sintering MF number) are replaced '
    'by the database on insert; any other value is stored as given. Not the PK.';

-- migrate:down
DROP TRIGGER IF EXISTS mfg_op_assign_numbers ON manufacturing_operations;
DROP FUNCTION IF EXISTS trg_manufacturing_operations_assign_numbers();

-- Restore the column comments exactly as 20260618000007_manufacturing_operations.sql left them.
COMMENT ON COLUMN manufacturing_operations.operation_sequence IS
    'Ordering of this operation within the sample lifecycle (1 = first).';
COMMENT ON COLUMN manufacturing_operations.pass_code IS
    'Human-readable pass identifier, e.g. 9-AA-MR-2023-03-23-F9.'
    ' Generated by generate_pass_code(). Not the PK.';
