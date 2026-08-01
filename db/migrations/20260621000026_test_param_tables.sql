-- migrate:up
-- Per-test-type parameter tables for test_sessions.
-- Each has a 1:1 relationship via session_id.
-- Also adds data_file columns to test_sessions and tightens the test_type CHECK.

ALTER TABLE test_sessions
    ADD COLUMN IF NOT EXISTS data_file_uri      TEXT,
    ADD COLUMN IF NOT EXISTS data_file_size_gb  NUMERIC(10,4);

-- Widen test_type to cover all named types (drop old CHECK, add new one)
ALTER TABLE test_sessions DROP CONSTRAINT IF EXISTS test_sessions_test_type_check;
ALTER TABLE test_sessions ADD  CONSTRAINT test_sessions_test_type_check
    CHECK (test_type IN (
        'tensile', 'hardness', 'charpy', 'compression',
        'sem', 'xrd', 'optical_microscopy',
        'tribology', 'fatigue', 'creep', 'dct',
        'other'
    ));

-- ─── Tensile Test ─────────────────────────────────────────────────────────────
CREATE TABLE tensile_test_params (
    param_id                    UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    session_id                  UUID NOT NULL UNIQUE
                                    REFERENCES test_sessions(session_id) ON DELETE CASCADE,
    -- Specimen
    specimen_geometry           TEXT CHECK (specimen_geometry IN
                                    ('dog_bone','waisted','flat','round','other')),
    gauge_length_mm             NUMERIC(8,3),
    gauge_diameter_mm           NUMERIC(8,3),
    gauge_width_mm              NUMERIC(8,3),
    gauge_thickness_mm          NUMERIC(8,3),
    -- Conditions
    crosshead_speed_mm_per_min  NUMERIC(8,3),
    strain_rate_per_s           NUMERIC(10,6),
    test_temp_celsius           NUMERIC(8,2),
    extensometer_used           BOOLEAN,
    -- Results (filled after test / by data pipeline)
    yield_strength_mpa          NUMERIC(10,3),
    uts_mpa                     NUMERIC(10,3),
    elongation_pct              NUMERIC(8,3),
    reduction_of_area_pct       NUMERIC(8,3),
    youngs_modulus_gpa          NUMERIC(8,3),
    fracture_mode               TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    version     INTEGER     NOT NULL DEFAULT 1
);

-- ─── Hardness Test ────────────────────────────────────────────────────────────
CREATE TABLE hardness_test_params (
    param_id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    session_id        UUID NOT NULL UNIQUE
                          REFERENCES test_sessions(session_id) ON DELETE CASCADE,
    hardness_scale    TEXT CHECK (hardness_scale IN
                          ('HV','HRC','HRB','HB','HK','Shore_A','Shore_D')),
    load_gf           NUMERIC(10,3),
    dwell_time_s      NUMERIC(6,2),
    indenter_type     TEXT,
    n_indentations    INTEGER,
    surface_finish    TEXT,
    -- Results
    mean_hardness     NUMERIC(10,3),
    std_dev_hardness  NUMERIC(10,3),
    min_hardness      NUMERIC(10,3),
    max_hardness      NUMERIC(10,3),
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    version     INTEGER     NOT NULL DEFAULT 1
);

-- ─── Charpy Impact Test ───────────────────────────────────────────────────────
CREATE TABLE charpy_test_params (
    param_id               UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    session_id             UUID NOT NULL UNIQUE
                               REFERENCES test_sessions(session_id) ON DELETE CASCADE,
    specimen_standard      TEXT CHECK (specimen_standard IN ('ISO_148','ASTM_E23','other')),
    notch_type             TEXT CHECK (notch_type IN ('V','U','keyhole','none')),
    notch_depth_mm         NUMERIC(6,3),
    specimen_width_mm      NUMERIC(6,3),
    specimen_height_mm     NUMERIC(6,3),
    test_temp_celsius      NUMERIC(8,2),
    orientation            TEXT,
    -- Results
    absorbed_energy_j      NUMERIC(8,3),
    lateral_expansion_mm   NUMERIC(6,3),
    shear_fracture_pct     NUMERIC(6,2),
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    version     INTEGER     NOT NULL DEFAULT 1
);

-- ─── Compression Test ─────────────────────────────────────────────────────────
CREATE TABLE compression_test_params (
    param_id                    UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    session_id                  UUID NOT NULL UNIQUE
                                    REFERENCES test_sessions(session_id) ON DELETE CASCADE,
    specimen_diameter_mm        NUMERIC(8,3),
    specimen_height_mm          NUMERIC(8,3),
    crosshead_speed_mm_per_min  NUMERIC(8,3),
    strain_rate_per_s           NUMERIC(10,6),
    test_temp_celsius           NUMERIC(8,2),
    lubrication                 TEXT,
    -- Results
    yield_strength_mpa          NUMERIC(10,3),
    peak_stress_mpa             NUMERIC(10,3),
    strain_at_fracture_pct      NUMERIC(8,3),
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    version     INTEGER     NOT NULL DEFAULT 1
);

-- ─── SEM / EBSD / EDS ────────────────────────────────────────────────────────
CREATE TABLE sem_params (
    param_id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    session_id                UUID NOT NULL UNIQUE
                                  REFERENCES test_sessions(session_id) ON DELETE CASCADE,
    imaging_mode              TEXT CHECK (imaging_mode IN
                                  ('SE','BSE','EBSD','EDS','WDS','CL','other')),
    accelerating_voltage_kv   NUMERIC(6,2),
    working_distance_mm       NUMERIC(6,2),
    magnification_range       TEXT,
    beam_current_na           NUMERIC(8,4),
    coating_material          TEXT,
    coating_thickness_nm      NUMERIC(8,2),
    etchant                   TEXT,
    step_size_um              NUMERIC(8,4),
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    version     INTEGER     NOT NULL DEFAULT 1
);

-- ─── XRD ─────────────────────────────────────────────────────────────────────
CREATE TABLE xrd_params (
    param_id                UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    session_id              UUID NOT NULL UNIQUE
                                REFERENCES test_sessions(session_id) ON DELETE CASCADE,
    radiation_source        TEXT,
    wavelength_angstrom     NUMERIC(8,5),
    two_theta_range_deg     TEXT,
    step_size_deg           NUMERIC(6,4),
    scan_speed_deg_per_min  NUMERIC(6,3),
    detector_type           TEXT,
    sample_prep             TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    version     INTEGER     NOT NULL DEFAULT 1
);

-- ─── OCC triggers ────────────────────────────────────────────────────────────
CREATE TRIGGER tensile_test_params_occ
    BEFORE UPDATE ON tensile_test_params
    FOR EACH ROW EXECUTE FUNCTION occ_update_trigger_function();

CREATE TRIGGER hardness_test_params_occ
    BEFORE UPDATE ON hardness_test_params
    FOR EACH ROW EXECUTE FUNCTION occ_update_trigger_function();

CREATE TRIGGER charpy_test_params_occ
    BEFORE UPDATE ON charpy_test_params
    FOR EACH ROW EXECUTE FUNCTION occ_update_trigger_function();

CREATE TRIGGER compression_test_params_occ
    BEFORE UPDATE ON compression_test_params
    FOR EACH ROW EXECUTE FUNCTION occ_update_trigger_function();

CREATE TRIGGER sem_params_occ
    BEFORE UPDATE ON sem_params
    FOR EACH ROW EXECUTE FUNCTION occ_update_trigger_function();

CREATE TRIGGER xrd_params_occ
    BEFORE UPDATE ON xrd_params
    FOR EACH ROW EXECUTE FUNCTION occ_update_trigger_function();

-- migrate:down
DROP TRIGGER IF EXISTS xrd_params_occ             ON xrd_params;
DROP TRIGGER IF EXISTS sem_params_occ             ON sem_params;
DROP TRIGGER IF EXISTS compression_test_params_occ ON compression_test_params;
DROP TRIGGER IF EXISTS charpy_test_params_occ     ON charpy_test_params;
DROP TRIGGER IF EXISTS hardness_test_params_occ   ON hardness_test_params;
DROP TRIGGER IF EXISTS tensile_test_params_occ    ON tensile_test_params;

DROP TABLE IF EXISTS xrd_params;
DROP TABLE IF EXISTS sem_params;
DROP TABLE IF EXISTS compression_test_params;
DROP TABLE IF EXISTS charpy_test_params;
DROP TABLE IF EXISTS hardness_test_params;
DROP TABLE IF EXISTS tensile_test_params;

ALTER TABLE test_sessions DROP COLUMN IF EXISTS data_file_uri;
ALTER TABLE test_sessions DROP COLUMN IF EXISTS data_file_size_gb;

ALTER TABLE test_sessions DROP CONSTRAINT IF EXISTS test_sessions_test_type_check;
