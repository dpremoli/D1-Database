-- migrate:up
-- M2M junction: which elemental symbols compose each alloy.
-- Mirrors AppSheet "Alloy Codes.Alloying Elements" EnumList.
CREATE TABLE material_alloying_elements (
    material_id  UUID       NOT NULL REFERENCES materials(material_id) ON DELETE CASCADE,
    symbol       VARCHAR(4) NOT NULL REFERENCES alloying_elements(symbol) ON DELETE RESTRICT,
    PRIMARY KEY (material_id, symbol)
);

COMMENT ON TABLE material_alloying_elements IS 'M2M: elemental composition of each alloy (mirrors AppSheet Alloy Codes.Alloying Elements EnumList).';

-- Add item_type to physical_samples (separate concept from geometry/form).
-- AppSheet "Inventory.Item Type": Sample | Equipment | Miscellaneous.
ALTER TABLE physical_samples
    ADD COLUMN IF NOT EXISTS item_type TEXT
        CHECK (item_type IN ('sample', 'equipment', 'miscellaneous'));

COMMENT ON COLUMN physical_samples.item_type IS 'AppSheet Item Type: sample | equipment | miscellaneous. Distinct from form/geometry.';

-- migrate:down
DROP TABLE IF EXISTS material_alloying_elements;
ALTER TABLE physical_samples DROP COLUMN IF EXISTS item_type;
