-- migrate:up
-- Optimistic Concurrency Control (OCC) helpers.
-- A BEFORE UPDATE trigger on every mutable table:
--   1. Increments `version` by 1.
--   2. Sets `updated_at` to NOW().
-- The API layer enforces OCC by including WHERE version = <client_version> in
-- UPDATE statements and treating 0 rows affected as a conflict.

CREATE OR REPLACE FUNCTION occ_update_trigger_function()
    RETURNS TRIGGER
    LANGUAGE plpgsql
AS $$
BEGIN
    NEW.version    := OLD.version + 1;
    NEW.updated_at := NOW();
    RETURN NEW;
END;
$$;

-- Attach to all tables that carry version + updated_at.
CREATE TRIGGER occ_manufacturing_methods
    BEFORE UPDATE ON manufacturing_methods
    FOR EACH ROW EXECUTE FUNCTION occ_update_trigger_function();

CREATE TRIGGER occ_equipment
    BEFORE UPDATE ON equipment
    FOR EACH ROW EXECUTE FUNCTION occ_update_trigger_function();

CREATE TRIGGER occ_tools
    BEFORE UPDATE ON tools
    FOR EACH ROW EXECUTE FUNCTION occ_update_trigger_function();

CREATE TRIGGER occ_insert_types
    BEFORE UPDATE ON insert_types
    FOR EACH ROW EXECUTE FUNCTION occ_update_trigger_function();

CREATE TRIGGER occ_projects
    BEFORE UPDATE ON projects
    FOR EACH ROW EXECUTE FUNCTION occ_update_trigger_function();

CREATE TRIGGER occ_raw_stock_lots
    BEFORE UPDATE ON raw_stock_lots
    FOR EACH ROW EXECUTE FUNCTION occ_update_trigger_function();

CREATE TRIGGER occ_tool_boxes
    BEFORE UPDATE ON tool_boxes
    FOR EACH ROW EXECUTE FUNCTION occ_update_trigger_function();

CREATE TRIGGER occ_cutting_inserts
    BEFORE UPDATE ON cutting_inserts
    FOR EACH ROW EXECUTE FUNCTION occ_update_trigger_function();

CREATE TRIGGER occ_insert_edges
    BEFORE UPDATE ON insert_edges
    FOR EACH ROW EXECUTE FUNCTION occ_update_trigger_function();

CREATE TRIGGER occ_physical_samples
    BEFORE UPDATE ON physical_samples
    FOR EACH ROW EXECUTE FUNCTION occ_update_trigger_function();

CREATE TRIGGER occ_manufacturing_operations
    BEFORE UPDATE ON manufacturing_operations
    FOR EACH ROW EXECUTE FUNCTION occ_update_trigger_function();

CREATE TRIGGER occ_test_sessions
    BEFORE UPDATE ON test_sessions
    FOR EACH ROW EXECUTE FUNCTION occ_update_trigger_function();

-- migrate:down

DROP TRIGGER IF EXISTS occ_test_sessions ON test_sessions;
DROP TRIGGER IF EXISTS occ_manufacturing_operations ON manufacturing_operations;
DROP TRIGGER IF EXISTS occ_physical_samples ON physical_samples;
DROP TRIGGER IF EXISTS occ_insert_edges ON insert_edges;
DROP TRIGGER IF EXISTS occ_cutting_inserts ON cutting_inserts;
DROP TRIGGER IF EXISTS occ_tool_boxes ON tool_boxes;
DROP TRIGGER IF EXISTS occ_raw_stock_lots ON raw_stock_lots;
DROP TRIGGER IF EXISTS occ_projects ON projects;
DROP TRIGGER IF EXISTS occ_insert_types ON insert_types;
DROP TRIGGER IF EXISTS occ_tools ON tools;
DROP TRIGGER IF EXISTS occ_equipment ON equipment;
DROP TRIGGER IF EXISTS occ_manufacturing_methods ON manufacturing_methods;
DROP FUNCTION IF EXISTS occ_update_trigger_function();
