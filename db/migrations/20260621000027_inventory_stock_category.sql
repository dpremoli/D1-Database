-- migrate:up
-- Add stock_category to physical_samples to distinguish bulk metal stock,
-- powder forms, and specialty geometries. Drives conditional field visibility
-- in Directus (different dimension fields per category).

ALTER TABLE physical_samples
    ADD COLUMN IF NOT EXISTS stock_category TEXT
        CHECK (stock_category IN ('bulk', 'powder', 'specialty'));

-- migrate:down
ALTER TABLE physical_samples DROP COLUMN IF EXISTS stock_category;
