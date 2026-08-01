-- migrate:up
-- Seed ISO 513 material classification codes referenced by insert_types.material_class
-- and materials.iso_code.
INSERT INTO material_iso_classifications (iso_code, description, colour_hex) VALUES
    ('P', 'Steel and cast steel',             '#4169E1'),
    ('M', 'Stainless steel',                  '#FFD700'),
    ('K', 'Cast iron',                        '#DC143C'),
    ('N', 'Non-ferrous metals (Al, Cu, etc.)','#32CD32'),
    ('S', 'Super alloys and titanium',        '#FF8C00'),
    ('H', 'Hardened materials',               '#808080')
ON CONFLICT (iso_code) DO NOTHING;

-- migrate:down
DELETE FROM material_iso_classifications WHERE iso_code IN ('P','M','K','N','S','H');
