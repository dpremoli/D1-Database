-- migrate:up
-- Per-process-type parameter tables for manufacturing_operations.
-- Each table has a 1:1 relationship with manufacturing_operations via operation_id.
-- The recorded_metadata JSONB is kept for legacy data; these tables carry new typed records.

-- ─── Machining (Turning / Milling / Drilling / EDM / Facing) ─────────────────
CREATE TABLE machining_params (
    param_id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    operation_id              UUID NOT NULL UNIQUE
                                  REFERENCES manufacturing_operations(operation_id) ON DELETE CASCADE,
    -- Sub-type
    operation_subtype         TEXT CHECK (operation_subtype IN
                                  ('turning','facing','boring','threading',
                                   'grooving','parting','milling','drilling','other')),
    -- Cutting conditions  (MATLAB-app field names in comments)
    spindle_speed_rpm         NUMERIC(8,2),       -- max_rpm / rpm
    cutting_speed_m_per_min   NUMERIC(8,3),       -- vc_m_per_min
    feed_mm_per_rev           NUMERIC(8,4),       -- feed_mm_per_rev
    axial_depth_of_cut_mm     NUMERIC(8,4),       -- axial_mm / ap_mm
    radial_depth_of_cut_mm    NUMERIC(8,4),       -- ae (milling)
    cutting_length_mm         NUMERIC(8,2),       -- cut_length_mm
    -- Workpiece
    workpiece_diameter_mm     NUMERIC(8,3),       -- diameter_mm
    -- Setup flags
    new_edge                  BOOLEAN,
    coolant_used              BOOLEAN,
    coolant_pressure_bar      NUMERIC(6,2),
    tacho_used                BOOLEAN,
    -- Capture / output
    force_captured            BOOLEAN,
    chips_collected           BOOLEAN,
    chips_ref_code            TEXT,
    -- Documentation
    experiment_sheet_url      TEXT,
    -- Legacy traceability (imported from recorded_metadata)
    legacy_insert_edge_id     TEXT,
    legacy_machining_uid      TEXT,
    -- OCC
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    version     INTEGER     NOT NULL DEFAULT 1
);

-- ─── Sintering (FAST / HIP / SPS) ────────────────────────────────────────────
CREATE TABLE sintering_params (
    param_id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    operation_id          UUID NOT NULL UNIQUE
                              REFERENCES manufacturing_operations(operation_id) ON DELETE CASCADE,
    recipe_number         TEXT,
    batch_number          TEXT,
    mould_diameter_mm     NUMERIC(8,3),
    atmosphere            TEXT,
    tc_pyro_control       TEXT,
    max_temp_celsius      NUMERIC(8,2),
    max_force_kn          NUMERIC(8,3),
    voltage_at_max_t_v    NUMERIC(8,3),
    power_at_max_t_kw     NUMERIC(8,3),
    ptc_top_celsius       NUMERIC(8,2),
    ptc_bot_celsius       NUMERIC(8,2),
    coshh_ref             TEXT,
    material_type_note    TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    version     INTEGER     NOT NULL DEFAULT 1
);

-- ─── Heat Treatment ───────────────────────────────────────────────────────────
CREATE TABLE heat_treatment_params (
    param_id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    operation_id              UUID NOT NULL UNIQUE
                                  REFERENCES manufacturing_operations(operation_id) ON DELETE CASCADE,
    treatment_type            TEXT CHECK (treatment_type IN
                                  ('anneal','solution_treat','age','quench','temper',
                                   'stress_relieve','normalise','other')),
    atmosphere                TEXT,
    peak_temp_celsius         NUMERIC(8,2),
    hold_time_min             NUMERIC(8,2),
    heating_rate_c_per_min    NUMERIC(8,3),
    cooling_method            TEXT CHECK (cooling_method IN
                                  ('furnace','air','water_quench','oil_quench','forced_air','other')),
    cooling_rate_c_per_min    NUMERIC(8,3),
    quench_medium             TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    version     INTEGER     NOT NULL DEFAULT 1
);

-- ─── Deformation (Rolling / Forging / Extrusion) ─────────────────────────────
CREATE TABLE deformation_params (
    param_id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    operation_id              UUID NOT NULL UNIQUE
                                  REFERENCES manufacturing_operations(operation_id) ON DELETE CASCADE,
    deformation_type          TEXT CHECK (deformation_type IN
                                  ('rolling','forging','extrusion','drawing','other')),
    deformation_temp_celsius  NUMERIC(8,2),
    pass_count                INTEGER,
    total_reduction_pct       NUMERIC(6,2),
    reduction_per_pass_pct    NUMERIC(6,2),
    strain_rate_per_sec       NUMERIC(10,4),
    roll_speed_m_per_min      NUMERIC(8,3),
    lubricant                 TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    version     INTEGER     NOT NULL DEFAULT 1
);

-- ─── Additive Manufacturing ───────────────────────────────────────────────────
CREATE TABLE am_params (
    param_id                      UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    operation_id                  UUID NOT NULL UNIQUE
                                      REFERENCES manufacturing_operations(operation_id) ON DELETE CASCADE,
    process_variant               TEXT CHECK (process_variant IN
                                      ('SLM','EBM','DED','WAAM','binder_jet','other')),
    layer_thickness_mm            NUMERIC(8,4),
    laser_power_w                 NUMERIC(8,2),
    scan_speed_mm_per_s           NUMERIC(8,2),
    hatch_spacing_mm              NUMERIC(8,4),
    energy_density_j_per_mm3      NUMERIC(10,4),
    build_atmosphere              TEXT,
    preheat_temp_celsius          NUMERIC(8,2),
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    version     INTEGER     NOT NULL DEFAULT 1
);

-- ─── Seed new manufacturing method: Heat Treatment ───────────────────────────
INSERT INTO manufacturing_methods (method_code, method_name, description)
VALUES ('HT', 'Heat Treatment', 'Thermal processing: annealing, solution treat, ageing, quench, temper')
ON CONFLICT (method_code) DO NOTHING;

-- ─── OCC triggers ────────────────────────────────────────────────────────────
CREATE TRIGGER machining_params_occ
    BEFORE UPDATE ON machining_params
    FOR EACH ROW EXECUTE FUNCTION occ_update_trigger_function();

CREATE TRIGGER sintering_params_occ
    BEFORE UPDATE ON sintering_params
    FOR EACH ROW EXECUTE FUNCTION occ_update_trigger_function();

CREATE TRIGGER heat_treatment_params_occ
    BEFORE UPDATE ON heat_treatment_params
    FOR EACH ROW EXECUTE FUNCTION occ_update_trigger_function();

CREATE TRIGGER deformation_params_occ
    BEFORE UPDATE ON deformation_params
    FOR EACH ROW EXECUTE FUNCTION occ_update_trigger_function();

CREATE TRIGGER am_params_occ
    BEFORE UPDATE ON am_params
    FOR EACH ROW EXECUTE FUNCTION occ_update_trigger_function();

-- migrate:down
DROP TRIGGER IF EXISTS am_params_occ              ON am_params;
DROP TRIGGER IF EXISTS deformation_params_occ     ON deformation_params;
DROP TRIGGER IF EXISTS heat_treatment_params_occ  ON heat_treatment_params;
DROP TRIGGER IF EXISTS sintering_params_occ       ON sintering_params;
DROP TRIGGER IF EXISTS machining_params_occ       ON machining_params;

DROP TABLE IF EXISTS am_params;
DROP TABLE IF EXISTS deformation_params;
DROP TABLE IF EXISTS heat_treatment_params;
DROP TABLE IF EXISTS sintering_params;
DROP TABLE IF EXISTS machining_params;

DELETE FROM manufacturing_methods WHERE method_code = 'HT';
