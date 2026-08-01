-- migrate:up
-- Split the sintering fields on the operation form by provenance so it's obvious which values
-- come from the machine and which are hand-entered QA. Both groups are created hidden=false
-- with a "hide unless sintering" condition — the inverse (hidden=true + show-conditions) makes
-- Directus error on the record page.

INSERT INTO directus_fields (collection, field, special, interface, options, conditions, sort, width, hidden)
SELECT 'manufacturing_operations', v.field, 'alias,no-data,group', 'group-detail',
       v.options::json, v.conditions::json, v.sort, 'full', false
FROM (VALUES
    ('sintering_machine_group',
     '{"start":"open"}',
     '[{"name":"Hide unless sintering","rule":{"_and":[{"process_category":{"_neq":"sintering"}}]},"hidden":true}]',
     60),
    ('sintering_qa_group',
     '{"start":"closed"}',
     '[{"name":"Hide unless sintering","rule":{"_and":[{"process_category":{"_neq":"sintering"}}]},"hidden":true}]',
     61)
) v(field, options, conditions, sort)
WHERE NOT EXISTS (
    SELECT 1 FROM directus_fields f
    WHERE f.collection = 'manufacturing_operations' AND f.field = v.field
);

-- Machine-sourced fields (MDB / export list / measured trace).
UPDATE directus_fields SET "group" = 'sintering_machine_group'
 WHERE collection = 'manufacturing_operations'
   AND field IN ('fast_recipe_id', 'sintering_recipe_number', 'sintering_batch_number',
                 'sintering_max_temp_celsius', 'sintering_max_force_kn',
                 'sintering_mould_diameter_mm', 'sintering_mass_grams',
                 'sintering_atmosphere', 'sintering_tc_pyro_control',
                 'sintering_material_type_note');

-- QA-log fields (hand-entered; the only values still sourced from the sheets).
UPDATE directus_fields SET "group" = 'sintering_qa_group'
 WHERE collection = 'manufacturing_operations'
   AND field IN ('sintering_coshh_ref', 'sintering_ptc_top_celsius', 'sintering_ptc_bot_celsius',
                 'sintering_voltage_at_max_t_v', 'sintering_power_at_max_t_kw');

-- migrate:down
UPDATE directus_fields SET "group" = NULL
 WHERE collection = 'manufacturing_operations'
   AND "group" IN ('sintering_machine_group', 'sintering_qa_group');
DELETE FROM directus_fields
 WHERE collection = 'manufacturing_operations'
   AND field IN ('sintering_machine_group', 'sintering_qa_group');
