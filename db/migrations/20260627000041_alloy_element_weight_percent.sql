-- migrate:up
-- Record HOW MUCH of each element is in an alloy, not just which elements are
-- present. weight_percent is the nominal content (wt%) of the element in the
-- material; the matrix/base element is the balance to 100%. Drives the alloy
-- composition bar (d1-composition-bar) on the material detail page.

ALTER TABLE material_alloying_elements
    ADD COLUMN IF NOT EXISTS weight_percent NUMERIC(6,3)
        CHECK (weight_percent IS NULL OR (weight_percent >= 0 AND weight_percent <= 100));

COMMENT ON COLUMN material_alloying_elements.weight_percent
    IS 'Nominal content of this element in the alloy, weight percent (0–100). Null = unspecified.';

-- migrate:down
ALTER TABLE material_alloying_elements DROP COLUMN IF EXISTS weight_percent;
