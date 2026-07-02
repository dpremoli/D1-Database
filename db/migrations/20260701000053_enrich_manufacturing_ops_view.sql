-- migrate:up
-- Enrich v_manufacturing_operations_full with the process discriminator and the
-- inline process parameters (all already on manufacturing_operations). This makes
-- the view a single relation carrying method_name AND process_category AND the
-- machining/AM/sintering/deformation/heat-treatment parameters, so the text-to-SQL
-- model no longer has to choose between the view (had method_name) and the base
-- table (had the params) and mix columns across them. Appended at the end of the
-- column list so CREATE OR REPLACE VIEW is valid and the grant is preserved.
CREATE OR REPLACE VIEW v_manufacturing_operations_full AS
 SELECT mo.operation_id,
    mo.pass_code,
    mo.operation_date,
    mo.operation_sequence,
    mo.operator_name,
    mo.recorded_metadata,
    mo.capture_software,
    mo.capture_frequency_khz,
    mo.file_storage_pointer,
    mo.force_file_id,
    mo.outcome_notes,
    mo.created_at,
    ps.sample_id,
    ps.sample_code,
    mm.method_id,
    mm.method_name,
    mm.method_code,
    p.project_code,
    p.project_name,
    e.equipment_code,
    e.equipment_name,
    t.tool_code,
    ie.edge_code AS insert_edge_code,
    ci.insert_code,
    tb.tool_box_code,
    -- process discriminator + inline parameters (appended)
    mo.process_category,
    mo.machining_operation_subtype,
    mo.machining_feed_mm_per_rev,
    mo.machining_cutting_speed_m_per_min,
    mo.machining_spindle_speed_rpm,
    mo.machining_axial_depth_of_cut_mm,
    mo.machining_radial_depth_of_cut_mm,
    mo.machining_coolant_pressure_bar,
    mo.machining_workpiece_diameter_mm,
    mo.machining_cutting_length_mm,
    mo.am_process_variant,
    mo.am_laser_power_w,
    mo.am_scan_speed_mm_per_s,
    mo.am_energy_density_j_per_mm3,
    mo.am_hatch_spacing_mm,
    mo.am_layer_thickness_mm,
    mo.sintering_max_force_kn,
    mo.sintering_max_temp_celsius,
    mo.sintering_power_at_max_t_kw,
    mo.sintering_mould_diameter_mm,
    mo.deform_deformation_type,
    mo.deform_deformation_temp_celsius,
    mo.deform_strain_rate_per_sec,
    mo.deform_roll_speed_m_per_min,
    mo.deform_total_reduction_pct,
    mo.ht_treatment_type,
    mo.ht_peak_temp_celsius,
    mo.ht_heating_rate_c_per_min,
    mo.ht_cooling_rate_c_per_min,
    mo.ht_hold_time_min
   FROM manufacturing_operations mo
     JOIN physical_samples ps ON mo.sample_id = ps.sample_id
     JOIN manufacturing_methods mm ON mo.method_id = mm.method_id
     LEFT JOIN projects p ON mo.project_id = p.project_id
     LEFT JOIN equipment e ON mo.equipment_id = e.equipment_id
     LEFT JOIN tools t ON mo.tool_id = t.tool_id
     LEFT JOIN insert_edges ie ON mo.insert_edge_id = ie.edge_id
     LEFT JOIN cutting_inserts ci ON ie.insert_id = ci.insert_id
     LEFT JOIN tool_boxes tb ON ci.tool_box_id = tb.tool_box_id;

COMMENT ON COLUMN v_manufacturing_operations_full.process_category IS
    'Process type discriminator: which family of parameters applies (machining, sintering, additive, deformation, heat_treatment).';
COMMENT ON COLUMN v_manufacturing_operations_full.machining_operation_subtype IS
    'Machining sub-type (e.g. turning, milling) when process_category = machining.';

-- migrate:down
-- CREATE OR REPLACE cannot drop columns, so recreate the original view. The
-- broad-read grant is re-applied because the new object doesn't inherit it.
DROP VIEW IF EXISTS v_manufacturing_operations_full;
CREATE VIEW v_manufacturing_operations_full AS
 SELECT mo.operation_id,
    mo.pass_code,
    mo.operation_date,
    mo.operation_sequence,
    mo.operator_name,
    mo.recorded_metadata,
    mo.capture_software,
    mo.capture_frequency_khz,
    mo.file_storage_pointer,
    mo.force_file_id,
    mo.outcome_notes,
    mo.created_at,
    ps.sample_id,
    ps.sample_code,
    mm.method_id,
    mm.method_name,
    mm.method_code,
    p.project_code,
    p.project_name,
    e.equipment_code,
    e.equipment_name,
    t.tool_code,
    ie.edge_code AS insert_edge_code,
    ci.insert_code,
    tb.tool_box_code
   FROM manufacturing_operations mo
     JOIN physical_samples ps ON mo.sample_id = ps.sample_id
     JOIN manufacturing_methods mm ON mo.method_id = mm.method_id
     LEFT JOIN projects p ON mo.project_id = p.project_id
     LEFT JOIN equipment e ON mo.equipment_id = e.equipment_id
     LEFT JOIN tools t ON mo.tool_id = t.tool_id
     LEFT JOIN insert_edges ie ON mo.insert_edge_id = ie.edge_id
     LEFT JOIN cutting_inserts ci ON ie.insert_id = ci.insert_id
     LEFT JOIN tool_boxes tb ON ci.tool_box_id = tb.tool_box_id;
GRANT SELECT ON v_manufacturing_operations_full TO d1_llm_readonly;
