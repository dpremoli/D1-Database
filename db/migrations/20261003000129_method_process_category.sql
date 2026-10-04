-- migrate:up
-- Review finding 4.11: the process category came from a method-code map hard-coded in the
-- d1-process-category interface, a second copy of the CASE in 20260623000031_process_category.sql.
-- The copies had already diverged: the interface knew MT and MP, the SQL did not (MP, "Sample
-- Preparation", was added to the data in 20260625000036 after the SQL map was written). Worse, the
-- interface's `immediate` watcher emitted null for any code it did not know, blanking a stored
-- category when an existing operation was opened.
--
-- The map now lives in one place, the database:
--   * manufacturing_methods.process_category holds each method's category, back-filled here from the
--     union of the two old maps (MT is in the old interface map but in no seed or migration; it is
--     kept so a method with that code on a deployment keeps its category);
--   * a BEFORE trigger on manufacturing_operations fills process_category from the method when an
--     operation is inserted without one, or when its method_id changes and the same statement does
--     not set a category. A method with no category (a new method nobody mapped yet) leaves the
--     operation's own value alone -- the trigger never writes NULL over a stored value;
--   * the interface reads manufacturing_methods.process_category and only displays it (and still
--     sets the form value on a new record, because Directus field conditions that show the typed
--     parameter panels need it in the form before the first save).
--
-- No back-fill of existing manufacturing_operations rows: the down section could not tell the rows it
-- changed from the rest, and rows with a NULL category on a mapped method get one the next time their
-- method is set.

ALTER TABLE manufacturing_methods
    ADD COLUMN process_category TEXT;

ALTER TABLE manufacturing_methods
    ADD CONSTRAINT manufacturing_methods_process_category_check
    CHECK (process_category IN ('machining', 'sintering', 'heat_treatment', 'deformation', 'additive', 'sample_prep'));

COMMENT ON COLUMN manufacturing_methods.process_category IS
    'Process family of operations done with this method (machining / sintering / heat_treatment / '
    'deformation / additive / sample_prep). Copied onto manufacturing_operations.process_category when '
    'an operation is created or its method changes; NULL means "not mapped", and then an operation '
    'keeps whatever category it already has.';

UPDATE manufacturing_methods
SET process_category = CASE
        WHEN method_code IN ('MC','MM','MC2','MEDM','MCO','MX','MS','MT') THEN 'machining'
        WHEN method_code IN ('MF','MHIP')                                 THEN 'sintering'
        WHEN method_code IN ('HT')                                        THEN 'heat_treatment'
        WHEN method_code IN ('MO','MR')                                   THEN 'deformation'
        WHEN method_code IN ('MAM','MW','MAE')                            THEN 'additive'
        WHEN method_code IN ('MP')                                        THEN 'sample_prep'
    END
WHERE process_category IS NULL;

CREATE FUNCTION trg_manufacturing_operations_derive_category() RETURNS trigger
    LANGUAGE plpgsql
    SET search_path = pg_catalog, public
AS $$
DECLARE
    v_category TEXT;
BEGIN
    IF TG_OP = 'INSERT' THEN
        IF NEW.process_category IS NOT NULL THEN
            RETURN NEW;                      -- an explicit category (an import, an API client) wins
        END IF;
    ELSIF NEW.method_id IS NOT DISTINCT FROM OLD.method_id
          OR NEW.process_category IS DISTINCT FROM OLD.process_category THEN
        RETURN NEW;                          -- method unchanged, or the category was set deliberately
    END IF;

    SELECT mm.process_category INTO v_category
    FROM   public.manufacturing_methods mm
    WHERE  mm.method_id = NEW.method_id;

    IF v_category IS NOT NULL THEN
        NEW.process_category := v_category;  -- never assigns NULL over a stored value
    END IF;
    RETURN NEW;
END;
$$;

COMMENT ON FUNCTION trg_manufacturing_operations_derive_category() IS
    'BEFORE INSERT / UPDATE on manufacturing_operations: sets process_category from '
    'manufacturing_methods.process_category when the operation has none, or when its method changes '
    'without a category being set in the same statement. Never writes NULL (review 4.11).';

CREATE TRIGGER mfg_op_derive_category
    BEFORE INSERT OR UPDATE ON manufacturing_operations
    FOR EACH ROW EXECUTE FUNCTION trg_manufacturing_operations_derive_category();

COMMENT ON TRIGGER mfg_op_derive_category ON manufacturing_operations IS
    'Derives process_category from the operation''s manufacturing method (review 4.11).';

-- migrate:down
DROP TRIGGER IF EXISTS mfg_op_derive_category ON manufacturing_operations;
DROP FUNCTION IF EXISTS trg_manufacturing_operations_derive_category();
ALTER TABLE manufacturing_methods DROP CONSTRAINT IF EXISTS manufacturing_methods_process_category_check;
ALTER TABLE manufacturing_methods DROP COLUMN IF EXISTS process_category;
