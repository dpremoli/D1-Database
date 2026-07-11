-- migrate:up
-- The FRM fingerprint is now rendered per force axis (Fx, Fy, Fz) so the dashboard
-- can toggle between them. Replace the single frm_file with three file refs; the
-- previously-ingested single map (which was coloured by Fz) becomes frm_fz.

ALTER TABLE machining_force_analysis
    ADD COLUMN IF NOT EXISTS frm_fx UUID REFERENCES directus_files(id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS frm_fy UUID REFERENCES directus_files(id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS frm_fz UUID REFERENCES directus_files(id) ON DELETE SET NULL;

UPDATE machining_force_analysis SET frm_fz = frm_file WHERE frm_file IS NOT NULL AND frm_fz IS NULL;

-- Retire the single-map Directus metadata + relation + column.
DELETE FROM directus_relations WHERE many_collection = 'machining_force_analysis' AND many_field = 'frm_file';
DELETE FROM directus_fields    WHERE collection = 'machining_force_analysis' AND field = 'frm_file';
ALTER TABLE machining_force_analysis DROP COLUMN IF EXISTS frm_file;

-- Register the three per-axis file refs (image interface) + relations.
INSERT INTO directus_fields (collection, field, interface, display, width, sort, special)
SELECT * FROM (VALUES
    ('machining_force_analysis', 'frm_fx', 'file-image', 'image', 'half', 10, 'file'),
    ('machining_force_analysis', 'frm_fy', 'file-image', 'image', 'half', 11, 'file'),
    ('machining_force_analysis', 'frm_fz', 'file-image', 'image', 'half', 12, 'file')
) v(collection, field, interface, display, width, sort, special)
WHERE NOT EXISTS (
    SELECT 1 FROM directus_fields f WHERE f.collection = v.collection AND f.field = v.field
);

INSERT INTO directus_relations (many_collection, many_field, one_collection, one_deselect_action)
SELECT 'machining_force_analysis', fld, 'directus_files', 'nullify'
FROM (VALUES ('frm_fx'), ('frm_fy'), ('frm_fz')) x(fld)
WHERE NOT EXISTS (
    SELECT 1 FROM directus_relations r
    WHERE r.many_collection = 'machining_force_analysis' AND r.many_field = x.fld
);

-- migrate:down
DELETE FROM directus_relations WHERE many_collection = 'machining_force_analysis' AND many_field IN ('frm_fx','frm_fy','frm_fz');
DELETE FROM directus_fields    WHERE collection = 'machining_force_analysis' AND field IN ('frm_fx','frm_fy','frm_fz');
ALTER TABLE machining_force_analysis ADD COLUMN IF NOT EXISTS frm_file UUID REFERENCES directus_files(id) ON DELETE SET NULL;
UPDATE machining_force_analysis SET frm_file = frm_fz WHERE frm_fz IS NOT NULL;
ALTER TABLE machining_force_analysis
    DROP COLUMN IF EXISTS frm_fx,
    DROP COLUMN IF EXISTS frm_fy,
    DROP COLUMN IF EXISTS frm_fz;
INSERT INTO directus_relations (many_collection, many_field, one_collection, one_deselect_action)
SELECT 'machining_force_analysis', 'frm_file', 'directus_files', 'nullify'
WHERE NOT EXISTS (SELECT 1 FROM directus_relations r WHERE r.many_collection='machining_force_analysis' AND r.many_field='frm_file');
