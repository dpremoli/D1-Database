-- migrate:up
-- Editing a cut's diag_recipe or tool_setup_id outside the workbench (in the Directus admin,
-- or by applying a library recipe) must requeue it -- otherwise the daemon never re-bakes and
-- the artifacts silently disagree with the stored recipe. process_diag_row's completion
-- UPDATE touches diag_status/path/points/version/metrics/hash/error but NOT diag_recipe or
-- tool_setup_id, so IS DISTINCT FROM is false on daemon writes and this does not fight it.
-- Painting a seed/mask layer does not change diag_recipe, so a layer edit alone does not
-- requeue -- an explicit Build does (unchanged Phase E behaviour).
CREATE OR REPLACE FUNCTION diag_requeue_on_recipe_change() RETURNS trigger AS $$
BEGIN
    IF NEW.diag_recipe IS DISTINCT FROM OLD.diag_recipe
       OR NEW.tool_setup_id IS DISTINCT FROM OLD.tool_setup_id THEN
        NEW.diag_status := 'pending';
        NEW.diag_requested_at := now();
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS diag_requeue_on_recipe_change ON machining_force_analysis;
CREATE TRIGGER diag_requeue_on_recipe_change
    BEFORE UPDATE ON machining_force_analysis
    FOR EACH ROW EXECUTE FUNCTION diag_requeue_on_recipe_change();

-- migrate:down
DROP TRIGGER IF EXISTS diag_requeue_on_recipe_change ON machining_force_analysis;
DROP FUNCTION IF EXISTS diag_requeue_on_recipe_change();
