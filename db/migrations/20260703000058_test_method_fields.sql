-- migrate:up
-- ④b Per-method inline parameter columns for the test methods that lacked them:
-- tribology, optical_microscopy, tem, alicona, clemx, dct, ct_scan, fatigue, creep, dma.
-- Setup + result fields, chosen from the standard settings each method records.
-- test_type already permits all of these (migration 20260624000033); no CHECK change.

-- tribology
ALTER TABLE test_sessions ADD COLUMN IF NOT EXISTS tribology_test_standard TEXT;
ALTER TABLE test_sessions ADD COLUMN IF NOT EXISTS tribology_configuration TEXT;
ALTER TABLE test_sessions ADD COLUMN IF NOT EXISTS tribology_counterface_material TEXT;
ALTER TABLE test_sessions ADD COLUMN IF NOT EXISTS tribology_normal_load_n NUMERIC(10,3);
ALTER TABLE test_sessions ADD COLUMN IF NOT EXISTS tribology_sliding_speed_m_per_s NUMERIC(10,4);
ALTER TABLE test_sessions ADD COLUMN IF NOT EXISTS tribology_sliding_distance_m NUMERIC(12,3);
ALTER TABLE test_sessions ADD COLUMN IF NOT EXISTS tribology_lubrication TEXT;
ALTER TABLE test_sessions ADD COLUMN IF NOT EXISTS tribology_test_temp_celsius NUMERIC(8,2);
ALTER TABLE test_sessions ADD COLUMN IF NOT EXISTS tribology_coefficient_of_friction NUMERIC(8,4);
ALTER TABLE test_sessions ADD COLUMN IF NOT EXISTS tribology_wear_rate_mm3_per_nm NUMERIC(14,8);
ALTER TABLE test_sessions ADD COLUMN IF NOT EXISTS tribology_wear_volume_mm3 NUMERIC(12,6);

-- optical_microscopy
ALTER TABLE test_sessions ADD COLUMN IF NOT EXISTS optical_microscopy_mode TEXT;
ALTER TABLE test_sessions ADD COLUMN IF NOT EXISTS optical_microscopy_objective_magnification TEXT;
ALTER TABLE test_sessions ADD COLUMN IF NOT EXISTS optical_microscopy_etchant TEXT;
ALTER TABLE test_sessions ADD COLUMN IF NOT EXISTS optical_microscopy_etch_time_s NUMERIC(8,2);
ALTER TABLE test_sessions ADD COLUMN IF NOT EXISTS optical_microscopy_image_scale_um_per_px NUMERIC(10,5);
ALTER TABLE test_sessions ADD COLUMN IF NOT EXISTS optical_microscopy_notable_features TEXT;

-- tem
ALTER TABLE test_sessions ADD COLUMN IF NOT EXISTS tem_operating_voltage_kv NUMERIC(6,1);
ALTER TABLE test_sessions ADD COLUMN IF NOT EXISTS tem_imaging_mode TEXT;
ALTER TABLE test_sessions ADD COLUMN IF NOT EXISTS tem_camera_length_mm NUMERIC(8,2);
ALTER TABLE test_sessions ADD COLUMN IF NOT EXISTS tem_specimen_prep TEXT;
ALTER TABLE test_sessions ADD COLUMN IF NOT EXISTS tem_magnification_range TEXT;
ALTER TABLE test_sessions ADD COLUMN IF NOT EXISTS tem_notable_features TEXT;

-- alicona
ALTER TABLE test_sessions ADD COLUMN IF NOT EXISTS alicona_objective_magnification TEXT;
ALTER TABLE test_sessions ADD COLUMN IF NOT EXISTS alicona_vertical_resolution_nm NUMERIC(10,2);
ALTER TABLE test_sessions ADD COLUMN IF NOT EXISTS alicona_lateral_resolution_um NUMERIC(10,4);
ALTER TABLE test_sessions ADD COLUMN IF NOT EXISTS alicona_measured_area TEXT;
ALTER TABLE test_sessions ADD COLUMN IF NOT EXISTS alicona_sa_um NUMERIC(10,4);
ALTER TABLE test_sessions ADD COLUMN IF NOT EXISTS alicona_sz_um NUMERIC(10,4);

-- clemx
ALTER TABLE test_sessions ADD COLUMN IF NOT EXISTS clemx_analysis_type TEXT;
ALTER TABLE test_sessions ADD COLUMN IF NOT EXISTS clemx_objective_magnification TEXT;
ALTER TABLE test_sessions ADD COLUMN IF NOT EXISTS clemx_n_fields_analysed INTEGER;
ALTER TABLE test_sessions ADD COLUMN IF NOT EXISTS clemx_etchant TEXT;
ALTER TABLE test_sessions ADD COLUMN IF NOT EXISTS clemx_mean_grain_size_um NUMERIC(10,3);
ALTER TABLE test_sessions ADD COLUMN IF NOT EXISTS clemx_astm_grain_size_number NUMERIC(6,2);
ALTER TABLE test_sessions ADD COLUMN IF NOT EXISTS clemx_phase_fraction_pct NUMERIC(6,2);

-- dct
ALTER TABLE test_sessions ADD COLUMN IF NOT EXISTS dct_beam_energy_kev NUMERIC(8,2);
ALTER TABLE test_sessions ADD COLUMN IF NOT EXISTS dct_voxel_size_um NUMERIC(10,4);
ALTER TABLE test_sessions ADD COLUMN IF NOT EXISTS dct_n_projections INTEGER;
ALTER TABLE test_sessions ADD COLUMN IF NOT EXISTS dct_scan_time_min NUMERIC(8,2);
ALTER TABLE test_sessions ADD COLUMN IF NOT EXISTS dct_n_grains_indexed INTEGER;
ALTER TABLE test_sessions ADD COLUMN IF NOT EXISTS dct_notable_features TEXT;

-- ct_scan
ALTER TABLE test_sessions ADD COLUMN IF NOT EXISTS ct_scan_tube_voltage_kv NUMERIC(8,2);
ALTER TABLE test_sessions ADD COLUMN IF NOT EXISTS ct_scan_tube_current_ua NUMERIC(10,2);
ALTER TABLE test_sessions ADD COLUMN IF NOT EXISTS ct_scan_voxel_size_um NUMERIC(10,4);
ALTER TABLE test_sessions ADD COLUMN IF NOT EXISTS ct_scan_n_projections INTEGER;
ALTER TABLE test_sessions ADD COLUMN IF NOT EXISTS ct_scan_exposure_time_ms NUMERIC(10,2);
ALTER TABLE test_sessions ADD COLUMN IF NOT EXISTS ct_scan_filter_material TEXT;
ALTER TABLE test_sessions ADD COLUMN IF NOT EXISTS ct_scan_porosity_pct NUMERIC(8,4);
ALTER TABLE test_sessions ADD COLUMN IF NOT EXISTS ct_scan_notable_features TEXT;

-- fatigue
ALTER TABLE test_sessions ADD COLUMN IF NOT EXISTS fatigue_loading_mode TEXT;
ALTER TABLE test_sessions ADD COLUMN IF NOT EXISTS fatigue_stress_ratio_r NUMERIC(6,3);
ALTER TABLE test_sessions ADD COLUMN IF NOT EXISTS fatigue_max_stress_mpa NUMERIC(10,3);
ALTER TABLE test_sessions ADD COLUMN IF NOT EXISTS fatigue_stress_amplitude_mpa NUMERIC(10,3);
ALTER TABLE test_sessions ADD COLUMN IF NOT EXISTS fatigue_frequency_hz NUMERIC(10,3);
ALTER TABLE test_sessions ADD COLUMN IF NOT EXISTS fatigue_waveform TEXT;
ALTER TABLE test_sessions ADD COLUMN IF NOT EXISTS fatigue_test_temp_celsius NUMERIC(8,2);
ALTER TABLE test_sessions ADD COLUMN IF NOT EXISTS fatigue_cycles_to_failure BIGINT;
ALTER TABLE test_sessions ADD COLUMN IF NOT EXISTS fatigue_runout BOOLEAN;

-- creep
ALTER TABLE test_sessions ADD COLUMN IF NOT EXISTS creep_applied_stress_mpa NUMERIC(10,3);
ALTER TABLE test_sessions ADD COLUMN IF NOT EXISTS creep_test_temp_celsius NUMERIC(8,2);
ALTER TABLE test_sessions ADD COLUMN IF NOT EXISTS creep_atmosphere TEXT;
ALTER TABLE test_sessions ADD COLUMN IF NOT EXISTS creep_time_to_rupture_h NUMERIC(12,3);
ALTER TABLE test_sessions ADD COLUMN IF NOT EXISTS creep_steady_state_creep_rate_per_s NUMERIC(16,12);
ALTER TABLE test_sessions ADD COLUMN IF NOT EXISTS creep_rupture_elongation_pct NUMERIC(8,3);
ALTER TABLE test_sessions ADD COLUMN IF NOT EXISTS creep_reduction_of_area_pct NUMERIC(8,3);

-- dma
ALTER TABLE test_sessions ADD COLUMN IF NOT EXISTS dma_deformation_mode TEXT;
ALTER TABLE test_sessions ADD COLUMN IF NOT EXISTS dma_frequency_hz NUMERIC(10,3);
ALTER TABLE test_sessions ADD COLUMN IF NOT EXISTS dma_temperature_range TEXT;
ALTER TABLE test_sessions ADD COLUMN IF NOT EXISTS dma_heating_rate_c_per_min NUMERIC(8,3);
ALTER TABLE test_sessions ADD COLUMN IF NOT EXISTS dma_amplitude_um NUMERIC(10,3);
ALTER TABLE test_sessions ADD COLUMN IF NOT EXISTS dma_storage_modulus_mpa NUMERIC(12,3);
ALTER TABLE test_sessions ADD COLUMN IF NOT EXISTS dma_loss_modulus_mpa NUMERIC(12,3);
ALTER TABLE test_sessions ADD COLUMN IF NOT EXISTS dma_tan_delta NUMERIC(10,5);
ALTER TABLE test_sessions ADD COLUMN IF NOT EXISTS dma_glass_transition_celsius NUMERIC(8,2);

-- migrate:down
ALTER TABLE test_sessions DROP COLUMN IF EXISTS dma_glass_transition_celsius;
ALTER TABLE test_sessions DROP COLUMN IF EXISTS dma_tan_delta;
ALTER TABLE test_sessions DROP COLUMN IF EXISTS dma_loss_modulus_mpa;
ALTER TABLE test_sessions DROP COLUMN IF EXISTS dma_storage_modulus_mpa;
ALTER TABLE test_sessions DROP COLUMN IF EXISTS dma_amplitude_um;
ALTER TABLE test_sessions DROP COLUMN IF EXISTS dma_heating_rate_c_per_min;
ALTER TABLE test_sessions DROP COLUMN IF EXISTS dma_temperature_range;
ALTER TABLE test_sessions DROP COLUMN IF EXISTS dma_frequency_hz;
ALTER TABLE test_sessions DROP COLUMN IF EXISTS dma_deformation_mode;
ALTER TABLE test_sessions DROP COLUMN IF EXISTS creep_reduction_of_area_pct;
ALTER TABLE test_sessions DROP COLUMN IF EXISTS creep_rupture_elongation_pct;
ALTER TABLE test_sessions DROP COLUMN IF EXISTS creep_steady_state_creep_rate_per_s;
ALTER TABLE test_sessions DROP COLUMN IF EXISTS creep_time_to_rupture_h;
ALTER TABLE test_sessions DROP COLUMN IF EXISTS creep_atmosphere;
ALTER TABLE test_sessions DROP COLUMN IF EXISTS creep_test_temp_celsius;
ALTER TABLE test_sessions DROP COLUMN IF EXISTS creep_applied_stress_mpa;
ALTER TABLE test_sessions DROP COLUMN IF EXISTS fatigue_runout;
ALTER TABLE test_sessions DROP COLUMN IF EXISTS fatigue_cycles_to_failure;
ALTER TABLE test_sessions DROP COLUMN IF EXISTS fatigue_test_temp_celsius;
ALTER TABLE test_sessions DROP COLUMN IF EXISTS fatigue_waveform;
ALTER TABLE test_sessions DROP COLUMN IF EXISTS fatigue_frequency_hz;
ALTER TABLE test_sessions DROP COLUMN IF EXISTS fatigue_stress_amplitude_mpa;
ALTER TABLE test_sessions DROP COLUMN IF EXISTS fatigue_max_stress_mpa;
ALTER TABLE test_sessions DROP COLUMN IF EXISTS fatigue_stress_ratio_r;
ALTER TABLE test_sessions DROP COLUMN IF EXISTS fatigue_loading_mode;
ALTER TABLE test_sessions DROP COLUMN IF EXISTS ct_scan_notable_features;
ALTER TABLE test_sessions DROP COLUMN IF EXISTS ct_scan_porosity_pct;
ALTER TABLE test_sessions DROP COLUMN IF EXISTS ct_scan_filter_material;
ALTER TABLE test_sessions DROP COLUMN IF EXISTS ct_scan_exposure_time_ms;
ALTER TABLE test_sessions DROP COLUMN IF EXISTS ct_scan_n_projections;
ALTER TABLE test_sessions DROP COLUMN IF EXISTS ct_scan_voxel_size_um;
ALTER TABLE test_sessions DROP COLUMN IF EXISTS ct_scan_tube_current_ua;
ALTER TABLE test_sessions DROP COLUMN IF EXISTS ct_scan_tube_voltage_kv;
ALTER TABLE test_sessions DROP COLUMN IF EXISTS dct_notable_features;
ALTER TABLE test_sessions DROP COLUMN IF EXISTS dct_n_grains_indexed;
ALTER TABLE test_sessions DROP COLUMN IF EXISTS dct_scan_time_min;
ALTER TABLE test_sessions DROP COLUMN IF EXISTS dct_n_projections;
ALTER TABLE test_sessions DROP COLUMN IF EXISTS dct_voxel_size_um;
ALTER TABLE test_sessions DROP COLUMN IF EXISTS dct_beam_energy_kev;
ALTER TABLE test_sessions DROP COLUMN IF EXISTS clemx_phase_fraction_pct;
ALTER TABLE test_sessions DROP COLUMN IF EXISTS clemx_astm_grain_size_number;
ALTER TABLE test_sessions DROP COLUMN IF EXISTS clemx_mean_grain_size_um;
ALTER TABLE test_sessions DROP COLUMN IF EXISTS clemx_etchant;
ALTER TABLE test_sessions DROP COLUMN IF EXISTS clemx_n_fields_analysed;
ALTER TABLE test_sessions DROP COLUMN IF EXISTS clemx_objective_magnification;
ALTER TABLE test_sessions DROP COLUMN IF EXISTS clemx_analysis_type;
ALTER TABLE test_sessions DROP COLUMN IF EXISTS alicona_sz_um;
ALTER TABLE test_sessions DROP COLUMN IF EXISTS alicona_sa_um;
ALTER TABLE test_sessions DROP COLUMN IF EXISTS alicona_measured_area;
ALTER TABLE test_sessions DROP COLUMN IF EXISTS alicona_lateral_resolution_um;
ALTER TABLE test_sessions DROP COLUMN IF EXISTS alicona_vertical_resolution_nm;
ALTER TABLE test_sessions DROP COLUMN IF EXISTS alicona_objective_magnification;
ALTER TABLE test_sessions DROP COLUMN IF EXISTS tem_notable_features;
ALTER TABLE test_sessions DROP COLUMN IF EXISTS tem_magnification_range;
ALTER TABLE test_sessions DROP COLUMN IF EXISTS tem_specimen_prep;
ALTER TABLE test_sessions DROP COLUMN IF EXISTS tem_camera_length_mm;
ALTER TABLE test_sessions DROP COLUMN IF EXISTS tem_imaging_mode;
ALTER TABLE test_sessions DROP COLUMN IF EXISTS tem_operating_voltage_kv;
ALTER TABLE test_sessions DROP COLUMN IF EXISTS optical_microscopy_notable_features;
ALTER TABLE test_sessions DROP COLUMN IF EXISTS optical_microscopy_image_scale_um_per_px;
ALTER TABLE test_sessions DROP COLUMN IF EXISTS optical_microscopy_etch_time_s;
ALTER TABLE test_sessions DROP COLUMN IF EXISTS optical_microscopy_etchant;
ALTER TABLE test_sessions DROP COLUMN IF EXISTS optical_microscopy_objective_magnification;
ALTER TABLE test_sessions DROP COLUMN IF EXISTS optical_microscopy_mode;
ALTER TABLE test_sessions DROP COLUMN IF EXISTS tribology_wear_volume_mm3;
ALTER TABLE test_sessions DROP COLUMN IF EXISTS tribology_wear_rate_mm3_per_nm;
ALTER TABLE test_sessions DROP COLUMN IF EXISTS tribology_coefficient_of_friction;
ALTER TABLE test_sessions DROP COLUMN IF EXISTS tribology_test_temp_celsius;
ALTER TABLE test_sessions DROP COLUMN IF EXISTS tribology_lubrication;
ALTER TABLE test_sessions DROP COLUMN IF EXISTS tribology_sliding_distance_m;
ALTER TABLE test_sessions DROP COLUMN IF EXISTS tribology_sliding_speed_m_per_s;
ALTER TABLE test_sessions DROP COLUMN IF EXISTS tribology_normal_load_n;
ALTER TABLE test_sessions DROP COLUMN IF EXISTS tribology_counterface_material;
ALTER TABLE test_sessions DROP COLUMN IF EXISTS tribology_configuration;
ALTER TABLE test_sessions DROP COLUMN IF EXISTS tribology_test_standard;
