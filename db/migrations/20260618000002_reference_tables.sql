-- migrate:up
-- Reference / lookup tables that other tables FK into.
-- These are small, mostly static catalogues.

-- ---------------------------------------------------------------------------
-- Periodic-table reference (from Alloying Elements sheet, 119 rows).
-- ---------------------------------------------------------------------------
CREATE TABLE alloying_elements (
    symbol          VARCHAR(4)  NOT NULL,
    element_name    TEXT        NOT NULL,
    atomic_number   INTEGER     NOT NULL,
    CONSTRAINT alloying_elements_pkey PRIMARY KEY (symbol),
    CONSTRAINT alloying_elements_atomic_number_unique UNIQUE (atomic_number)
);

COMMENT ON TABLE alloying_elements
    IS 'Periodic-table reference for elements used in alloy compositions.';
COMMENT ON COLUMN alloying_elements.symbol
    IS 'Chemical symbol, e.g. Ti, Al, V. Primary key.';
COMMENT ON COLUMN alloying_elements.element_name
    IS 'Full element name, e.g. Titanium.';
COMMENT ON COLUMN alloying_elements.atomic_number
    IS 'Atomic number (Z). Unique.';

-- ---------------------------------------------------------------------------
-- ISO material-group classifications (P / M / K / N / S / H).
-- ---------------------------------------------------------------------------
CREATE TABLE material_iso_classifications (
    iso_code    VARCHAR(4)  NOT NULL,
    description TEXT        NOT NULL,
    colour_hex  VARCHAR(7),
    CONSTRAINT material_iso_classifications_pkey PRIMARY KEY (iso_code)
);

COMMENT ON TABLE material_iso_classifications
    IS 'ISO 513 material-group codes (P, M, K, N, S, H) for cutting-tool selection.';
COMMENT ON COLUMN material_iso_classifications.iso_code
    IS 'Single-letter ISO group code, e.g. P, M, K, N, S, H.';
COMMENT ON COLUMN material_iso_classifications.colour_hex
    IS 'ISO-assigned colour for the group, e.g. #0066CC for P (blue).';

-- ---------------------------------------------------------------------------
-- Materials / alloy catalogue (from Alloy Codes sheet, ~1037 rows).
-- ---------------------------------------------------------------------------
CREATE TABLE materials (
    material_id         UUID        NOT NULL DEFAULT uuid_generate_v4(),
    alloy_code          VARCHAR(32) NOT NULL,
    common_name         TEXT        NOT NULL,
    iso_code            VARCHAR(4),
    density_g_per_cm3   NUMERIC(8, 4),
    export_controlled   BOOLEAN     NOT NULL DEFAULT FALSE,
    datasheet_url       TEXT,
    notes               TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT materials_pkey PRIMARY KEY (material_id),
    CONSTRAINT materials_alloy_code_unique UNIQUE (alloy_code),
    CONSTRAINT materials_iso_code_fkey
        FOREIGN KEY (iso_code)
        REFERENCES material_iso_classifications (iso_code)
);

COMMENT ON TABLE materials
    IS 'Alloy/material catalogue. alloy_code (e.g. AA = Ti-6Al-4V) is the'
       ' human-readable key used in sample codes.';
COMMENT ON COLUMN materials.alloy_code
    IS 'Short code used in sample_code generation, e.g. AA for Ti-6Al-4V.';
COMMENT ON COLUMN materials.common_name
    IS 'Human-readable material name, e.g. Ti-6Al-4V Grade 5.';
COMMENT ON COLUMN materials.density_g_per_cm3
    IS 'Theoretical density in grams per cubic centimetre.';
COMMENT ON COLUMN materials.export_controlled
    IS 'TRUE if subject to ITAR/ECJU export controls. Drives RBAC visibility.';

-- ---------------------------------------------------------------------------
-- Manufacturing methods catalogue (from Operation + Manufacturing Codes sheets).
-- ---------------------------------------------------------------------------
CREATE TABLE manufacturing_methods (
    method_id       UUID        NOT NULL DEFAULT uuid_generate_v4(),
    method_code     VARCHAR(8)  NOT NULL,
    method_name     TEXT        NOT NULL,
    description     TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    version         INTEGER     NOT NULL DEFAULT 1,
    CONSTRAINT manufacturing_methods_pkey PRIMARY KEY (method_id),
    CONSTRAINT manufacturing_methods_code_unique UNIQUE (method_code)
);

COMMENT ON TABLE manufacturing_methods
    IS 'Catalogue of physical-transformation process types, e.g. FAST/SPS, Turning.';
COMMENT ON COLUMN manufacturing_methods.method_code
    IS 'Short code used in sample_code generation, e.g. MF=FAST, MO=Forged, MR=Rolled.';

-- ---------------------------------------------------------------------------
-- Method parameters — dynamic template engine.
-- Defines which key-value pairs are expected in manufacturing_operations.recorded_metadata
-- for a given method_id. This is the configuration; JSONB holds the runtime values.
-- ---------------------------------------------------------------------------
CREATE TABLE method_parameters (
    parameter_id    UUID        NOT NULL DEFAULT uuid_generate_v4(),
    method_id       UUID        NOT NULL,
    parameter_name  TEXT        NOT NULL,
    display_name    TEXT        NOT NULL,
    data_type       TEXT        NOT NULL,
    unit_of_measure TEXT,
    is_required     BOOLEAN     NOT NULL DEFAULT FALSE,
    sort_order      INTEGER     NOT NULL DEFAULT 0,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT method_parameters_pkey PRIMARY KEY (parameter_id),
    CONSTRAINT method_parameters_method_param_unique UNIQUE (method_id, parameter_name),
    CONSTRAINT method_parameters_method_id_fkey
        FOREIGN KEY (method_id)
        REFERENCES manufacturing_methods (method_id),
    CONSTRAINT method_parameters_data_type_check
        CHECK (data_type IN ('numeric', 'integer', 'text', 'boolean', 'file_uri', 'timestamp'))
);

COMMENT ON TABLE method_parameters
    IS 'Template: which JSONB keys are expected in manufacturing_operations.recorded_metadata'
       ' for each manufacturing_method. Validates the dynamic-template pattern.';
COMMENT ON COLUMN method_parameters.parameter_name
    IS 'JSONB key used in recorded_metadata, e.g. peak_temperature_celsius.';
COMMENT ON COLUMN method_parameters.data_type
    IS 'Expected data type: numeric, integer, text, boolean, file_uri, or timestamp.';
COMMENT ON COLUMN method_parameters.unit_of_measure
    IS 'Physical unit, e.g. degC, mm_per_min, bar, rpm. NULL if dimensionless.';

-- ---------------------------------------------------------------------------
-- Equipment / machines catalogue (from Machines sheet, 7 rows).
-- ---------------------------------------------------------------------------
CREATE TABLE equipment (
    equipment_id    UUID        NOT NULL DEFAULT uuid_generate_v4(),
    equipment_code  VARCHAR(64) NOT NULL,
    equipment_name  TEXT        NOT NULL,
    equipment_type  TEXT        NOT NULL,
    location        TEXT,
    is_active       BOOLEAN     NOT NULL DEFAULT TRUE,
    notes           TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    version         INTEGER     NOT NULL DEFAULT 1,
    CONSTRAINT equipment_pkey PRIMARY KEY (equipment_id),
    CONSTRAINT equipment_code_unique UNIQUE (equipment_code)
);

COMMENT ON TABLE equipment
    IS 'Physical machines and rigs used in manufacturing and testing.';
COMMENT ON COLUMN equipment.equipment_code
    IS 'Short identifier, e.g. NLX-2500. Unique.';
COMMENT ON COLUMN equipment.equipment_type
    IS 'Category, e.g. CNC_Lathe, FAST_Press, SEM, Hardness_Tester.';

-- ---------------------------------------------------------------------------
-- Tool holders (from Tools sheet, 19 rows).
-- ---------------------------------------------------------------------------
CREATE TABLE tools (
    tool_id     UUID        NOT NULL DEFAULT uuid_generate_v4(),
    tool_code   VARCHAR(64) NOT NULL,
    tool_name   TEXT        NOT NULL,
    tool_type   TEXT,
    is_active   BOOLEAN     NOT NULL DEFAULT TRUE,
    notes       TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    version     INTEGER     NOT NULL DEFAULT 1,
    CONSTRAINT tools_pkey PRIMARY KEY (tool_id),
    CONSTRAINT tools_code_unique UNIQUE (tool_code)
);

COMMENT ON TABLE tools
    IS 'Tool holders used in machining operations.';
COMMENT ON COLUMN tools.tool_type
    IS 'Category, e.g. Turning, Milling.';

-- ---------------------------------------------------------------------------
-- Insert types catalogue (from Insert Types sheet, 24 rows).
-- ---------------------------------------------------------------------------
CREATE TABLE insert_types (
    insert_type_id  UUID        NOT NULL DEFAULT uuid_generate_v4(),
    type_code       VARCHAR(64) NOT NULL,
    manufacturer    TEXT,
    iso_designation TEXT,
    substrate       TEXT,
    coating         TEXT,
    geometry_notes  TEXT,
    datasheet_url   TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    version         INTEGER     NOT NULL DEFAULT 1,
    CONSTRAINT insert_types_pkey PRIMARY KEY (insert_type_id),
    CONSTRAINT insert_types_code_unique UNIQUE (type_code)
);

COMMENT ON TABLE insert_types
    IS 'Cutting-insert catalogue: grades, coatings, geometries (e.g. Sandvik CNMG).';
COMMENT ON COLUMN insert_types.type_code
    IS 'Manufacturer part or grade code. Unique.';
COMMENT ON COLUMN insert_types.substrate
    IS 'Insert material: carbide, PCBN, PCD, ceramic, etc.';

-- migrate:down

DROP TABLE IF EXISTS insert_types CASCADE;
DROP TABLE IF EXISTS tools CASCADE;
DROP TABLE IF EXISTS equipment CASCADE;
DROP TABLE IF EXISTS method_parameters CASCADE;
DROP TABLE IF EXISTS manufacturing_methods CASCADE;
DROP TABLE IF EXISTS materials CASCADE;
DROP TABLE IF EXISTS material_iso_classifications CASCADE;
DROP TABLE IF EXISTS alloying_elements CASCADE;
