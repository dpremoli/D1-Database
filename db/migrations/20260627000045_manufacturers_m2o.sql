-- migrate:up
-- Promote the free-text "manufacturer" on equipment/tools/insert_types to a real
-- reference table so it's a consistent dropdown everywhere. Free-text columns are
-- kept (hidden) as legacy provenance.

CREATE TABLE IF NOT EXISTS manufacturers (
    manufacturer_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name            TEXT NOT NULL UNIQUE,
    notes           TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

INSERT INTO manufacturers (name) VALUES
    ('Sandvik Coromant'), ('Seco Tools'), ('DMG Mori'), ('Hermle'), ('FCT Systeme')
ON CONFLICT (name) DO NOTHING;

ALTER TABLE equipment    ADD COLUMN IF NOT EXISTS manufacturer_id UUID REFERENCES manufacturers(manufacturer_id) ON DELETE SET NULL;
ALTER TABLE tools        ADD COLUMN IF NOT EXISTS manufacturer_id UUID REFERENCES manufacturers(manufacturer_id) ON DELETE SET NULL;
ALTER TABLE insert_types ADD COLUMN IF NOT EXISTS manufacturer_id UUID REFERENCES manufacturers(manufacturer_id) ON DELETE SET NULL;

-- Map the messy free-text values to canonical manufacturers (per table).
CREATE OR REPLACE FUNCTION _fast_mfr_map(txt TEXT) RETURNS UUID LANGUAGE sql AS $$
    SELECT manufacturer_id FROM manufacturers WHERE name =
      CASE
        WHEN txt ILIKE '%sandvik%' THEN 'Sandvik Coromant'
        WHEN txt ILIKE '%seco%'    THEN 'Seco Tools'
        WHEN txt ILIKE '%dmg%' OR txt ILIKE '%deckel%' OR txt ILIKE '%nlx%' THEN 'DMG Mori'
        WHEN txt ILIKE '%hermle%'  THEN 'Hermle'
        WHEN txt ILIKE '%fct%'     THEN 'FCT Systeme'
      END;
$$;
UPDATE equipment    SET manufacturer_id = _fast_mfr_map(manufacturer) WHERE manufacturer IS NOT NULL;
UPDATE tools        SET manufacturer_id = _fast_mfr_map(manufacturer) WHERE manufacturer IS NOT NULL;
UPDATE insert_types SET manufacturer_id = _fast_mfr_map(manufacturer) WHERE manufacturer IS NOT NULL;
DROP FUNCTION _fast_mfr_map(TEXT);

-- migrate:down
ALTER TABLE equipment    DROP COLUMN IF EXISTS manufacturer_id;
ALTER TABLE tools        DROP COLUMN IF EXISTS manufacturer_id;
ALTER TABLE insert_types DROP COLUMN IF EXISTS manufacturer_id;
DROP TABLE IF EXISTS manufacturers;
