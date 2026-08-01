-- migrate:up
-- Support standards-based specimen geometry: gauge dimensions for a tensile coupon,
-- and a wider `form` vocabulary (block / plate / bar / tensile_coupon / bend_bar)
-- so the guided creator's parametric isometric preview can scale to real dimensions
-- and draw ISO test specimens. width_mm already exists.

ALTER TABLE physical_samples
    ADD COLUMN IF NOT EXISTS gauge_length_mm NUMERIC(8,3),
    ADD COLUMN IF NOT EXISTS gauge_width_mm  NUMERIC(8,3);

COMMENT ON COLUMN physical_samples.gauge_length_mm IS 'Gauge length of a test coupon (e.g. ISO 6892 tensile). NULL for non-specimen forms.';
COMMENT ON COLUMN physical_samples.gauge_width_mm  IS 'Gauge (reduced-section) width of a test coupon. NULL for non-specimen forms.';

-- Expand the form dropdown choices to the creator's vocabulary.
UPDATE directus_fields
SET options = '{"choices":[{"text":"Disc","value":"disc"},{"text":"Cylinder","value":"cylinder"},{"text":"Block","value":"block"},{"text":"Plate","value":"plate"},{"text":"Bar","value":"bar"},{"text":"Tensile coupon (ISO 6892)","value":"tensile_coupon"},{"text":"Bend / fatigue bar (ISO 7438)","value":"bend_bar"},{"text":"Powder / Compact","value":"powder"},{"text":"Other","value":"other"}]}'
WHERE collection = 'physical_samples' AND field = 'form';

-- migrate:down
UPDATE directus_fields
SET options = '{"choices":[{"text":"Disc","value":"disc"},{"text":"Cylindrical","value":"cylindrical"},{"text":"Rectangular","value":"rectangular"},{"text":"Powder / Compact","value":"powder"},{"text":"Other","value":"other"}]}'
WHERE collection = 'physical_samples' AND field = 'form';
ALTER TABLE physical_samples DROP COLUMN IF EXISTS gauge_width_mm;
ALTER TABLE physical_samples DROP COLUMN IF EXISTS gauge_length_mm;
