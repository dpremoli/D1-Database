-- migrate:up
-- Distinguish square bar and round bar from the generic (rectangular) bar in the sample
-- form vocabulary, and show the right dimension inputs for each:
--   square_bar -> width_mm (side) + length_mm
--   round_bar  -> diameter_mm + length_mm
-- Existing `bar` samples are unchanged (relabelled "Rectangular bar").

UPDATE directus_fields
SET options = '{"choices":[{"text":"Disc","value":"disc"},{"text":"Cylinder","value":"cylinder"},{"text":"Block","value":"block"},{"text":"Plate","value":"plate"},{"text":"Rectangular bar","value":"bar"},{"text":"Square bar","value":"square_bar"},{"text":"Round bar","value":"round_bar"},{"text":"Tensile coupon (ISO 6892)","value":"tensile_coupon"},{"text":"Bend / fatigue bar (ISO 7438)","value":"bend_bar"},{"text":"Powder / Compact","value":"powder"},{"text":"Other","value":"other"}]}'
WHERE collection = 'physical_samples' AND field = 'form';

UPDATE directus_fields SET conditions='[{"name": "sample only", "rule": {"_and": [{"item_type": {"_neq": "sample"}}]}, "hidden": true, "readonly": false, "required": false}, {"name": "form", "rule": {"_and": [{"form": {"_nin": ["disc", "cylinder", "round_bar"]}}]}, "hidden": true, "readonly": false, "required": false}]' WHERE collection='physical_samples' AND field='diameter_mm';
UPDATE directus_fields SET conditions='[{"name": "sample only", "rule": {"_and": [{"item_type": {"_neq": "sample"}}]}, "hidden": true, "readonly": false, "required": false}, {"name": "form", "rule": {"_and": [{"form": {"_nin": ["cylinder", "block", "plate", "bar", "square_bar", "round_bar", "tensile_coupon", "bend_bar"]}}]}, "hidden": true, "readonly": false, "required": false}]' WHERE collection='physical_samples' AND field='length_mm';
UPDATE directus_fields SET conditions='[{"name": "sample only", "rule": {"_and": [{"item_type": {"_neq": "sample"}}]}, "hidden": true, "readonly": false, "required": false}, {"name": "form", "rule": {"_and": [{"form": {"_nin": ["block", "plate", "bar", "square_bar", "tensile_coupon", "bend_bar"]}}]}, "hidden": true, "readonly": false, "required": false}]' WHERE collection='physical_samples' AND field='width_mm';

-- migrate:down
UPDATE directus_fields
SET options = '{"choices":[{"text":"Disc","value":"disc"},{"text":"Cylinder","value":"cylinder"},{"text":"Block","value":"block"},{"text":"Plate","value":"plate"},{"text":"Bar","value":"bar"},{"text":"Tensile coupon (ISO 6892)","value":"tensile_coupon"},{"text":"Bend / fatigue bar (ISO 7438)","value":"bend_bar"},{"text":"Powder / Compact","value":"powder"},{"text":"Other","value":"other"}]}'
WHERE collection = 'physical_samples' AND field = 'form';

UPDATE directus_fields SET conditions='[{"name": "sample only", "rule": {"_and": [{"item_type": {"_neq": "sample"}}]}, "hidden": true, "readonly": false, "required": false}, {"name": "form", "rule": {"_and": [{"form": {"_nin": ["disc", "cylinder"]}}]}, "hidden": true, "readonly": false, "required": false}]' WHERE collection='physical_samples' AND field='diameter_mm';
UPDATE directus_fields SET conditions='[{"name": "sample only", "rule": {"_and": [{"item_type": {"_neq": "sample"}}]}, "hidden": true, "readonly": false, "required": false}, {"name": "form", "rule": {"_and": [{"form": {"_nin": ["cylinder", "block", "plate", "bar", "tensile_coupon", "bend_bar"]}}]}, "hidden": true, "readonly": false, "required": false}]' WHERE collection='physical_samples' AND field='length_mm';
UPDATE directus_fields SET conditions='[{"name": "sample only", "rule": {"_and": [{"item_type": {"_neq": "sample"}}]}, "hidden": true, "readonly": false, "required": false}, {"name": "form", "rule": {"_and": [{"form": {"_nin": ["block", "plate", "bar", "tensile_coupon", "bend_bar"]}}]}, "hidden": true, "readonly": false, "required": false}]' WHERE collection='physical_samples' AND field='width_mm';
