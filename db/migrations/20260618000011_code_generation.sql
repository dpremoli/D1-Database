-- migrate:up
-- Shared deterministic code-generation functions.
-- These are IMMUTABLE pure functions — given the same inputs they always return
-- the same output, making them safe for use in generated columns or application code.
--
-- All human-readable IDs (sample_code, pass_code, force_file_id) are PROJECTIONS
-- of relational data — never primary keys. They are regenerable from FK + parameter
-- data. See docs/experiment-sheets-and-naming.md for the naming hierarchy.

-- ---------------------------------------------------------------------------
-- sample_code: {seq}-{alloy_code}-{method_code}-{YYYY-MM-DD}
-- Example: 10-AA-MF-2023-06-03
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION generate_sample_code(
    p_sequence          INTEGER,
    p_alloy_code        TEXT,
    p_method_code       TEXT,
    p_manufactured_date DATE
)
    RETURNS TEXT
    LANGUAGE sql
    IMMUTABLE
    STRICT
AS $$
    SELECT
        p_sequence::TEXT
        || '-' || p_alloy_code
        || '-' || p_method_code
        || '-' || TO_CHAR(p_manufactured_date, 'YYYY-MM-DD')
$$;

COMMENT ON FUNCTION generate_sample_code(INTEGER, TEXT, TEXT, DATE)
    IS 'Generates the human-readable sample pseudonym.'
       ' Pattern: {seq}-{alloy_code}-{method_code}-{YYYY-MM-DD}.'
       ' E.g. generate_sample_code(10, ''AA'', ''MF'', ''2023-06-03'') → 10-AA-MF-2023-06-03.';

-- ---------------------------------------------------------------------------
-- pass_code: {sample_code}-{pass_type}{pass_number}
-- Example: 9-AA-MR-2023-03-23-F9  (F=facing pass, 9=ninth)
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION generate_pass_code(
    p_sample_code   TEXT,
    p_pass_type     TEXT,
    p_pass_number   INTEGER
)
    RETURNS TEXT
    LANGUAGE sql
    IMMUTABLE
    STRICT
AS $$
    SELECT p_sample_code || '-' || p_pass_type || p_pass_number::TEXT
$$;

COMMENT ON FUNCTION generate_pass_code(TEXT, TEXT, INTEGER)
    IS 'Generates the machining-pass pseudonym.'
       ' Pattern: {sample_code}-{pass_type}{n}. Pass types: F=facing, R=roughing.'
       ' E.g. generate_pass_code(''9-AA-MR-2023-03-23'', ''F'', 9) → 9-AA-MR-2023-03-23-F9.';

-- ---------------------------------------------------------------------------
-- force_file_id: {pass_code}-{Vc}MPM_{feed}feed_{DoC}DoC
-- Example: 9-AA-MR-2023-03-23-F9-20MPM_0.05feed_0.1DoC
--   Vc  = cutting speed [m/min]  (MPM = metres per minute)
--   feed = feed rate [mm/rev]
--   DoC  = depth of cut [mm]
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION generate_force_file_id(
    p_pass_code                 TEXT,
    p_cutting_speed_m_per_min   NUMERIC,
    p_feed_mm_per_rev           NUMERIC,
    p_depth_of_cut_mm           NUMERIC
)
    RETURNS TEXT
    LANGUAGE sql
    IMMUTABLE
    STRICT
AS $$
    SELECT
        p_pass_code
        || '-' || p_cutting_speed_m_per_min::TEXT || 'MPM'
        || '_' || p_feed_mm_per_rev::TEXT || 'feed'
        || '_' || p_depth_of_cut_mm::TEXT || 'DoC'
$$;

COMMENT ON FUNCTION generate_force_file_id(TEXT, NUMERIC, NUMERIC, NUMERIC)
    IS 'Generates the force-file human-readable ID from pass parameters.'
       ' Pattern: {pass_code}-{Vc}MPM_{feed}feed_{DoC}DoC.'
       ' The MinIO object key is built from this ID; it is regenerable from the operation row.';

-- migrate:down

DROP FUNCTION IF EXISTS generate_force_file_id(TEXT, NUMERIC, NUMERIC, NUMERIC);
DROP FUNCTION IF EXISTS generate_pass_code(TEXT, TEXT, INTEGER);
DROP FUNCTION IF EXISTS generate_sample_code(INTEGER, TEXT, TEXT, DATE);
