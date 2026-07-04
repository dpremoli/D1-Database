-- migrate:up
-- Back-generate operation codes (pass_code) for FAST / sintering operations that
-- don't have one, using the same rule as the d1-operation-code interface:
--   {sample_code}-MF[-{maxTemp}C_{maxForce}kN_{mouldDia}dia]
-- only including the parameters that are set. Only fills blank codes (never
-- clobbers a manually-entered one).

-- Trim trailing-zero noise like the interface's num() (970.00 -> "970", 25.50 -> "25.5").
CREATE OR REPLACE FUNCTION _clean_num(v NUMERIC) RETURNS TEXT LANGUAGE sql IMMUTABLE AS $$
    SELECT CASE WHEN v IS NULL THEN NULL
                ELSE trim(TRAILING '.' FROM trim(TRAILING '0' FROM v::text)) END;
$$;

WITH codes AS (
    SELECT mo.operation_id,
        CASE WHEN COALESCE(s.sample_code, '') <> '' THEN s.sample_code || '-MF' ELSE 'MF' END
        || CASE WHEN p.parts <> '' THEN '-' || p.parts ELSE '' END AS code
    FROM manufacturing_operations mo
    LEFT JOIN physical_samples s ON s.sample_id = mo.sample_id
    CROSS JOIN LATERAL (
        SELECT array_to_string(ARRAY(
            SELECT x FROM (VALUES
                (CASE WHEN mo.sintering_max_temp_celsius IS NOT NULL THEN _clean_num(mo.sintering_max_temp_celsius) || 'C'   END),
                (CASE WHEN mo.sintering_max_force_kn      IS NOT NULL THEN _clean_num(mo.sintering_max_force_kn)      || 'kN'  END),
                (CASE WHEN mo.sintering_mould_diameter_mm IS NOT NULL THEN _clean_num(mo.sintering_mould_diameter_mm) || 'dia' END)
            ) v(x) WHERE x IS NOT NULL
        ), '_') AS parts
    ) p
    WHERE mo.process_category = 'sintering'
      AND (mo.pass_code IS NULL OR mo.pass_code = '')
)
UPDATE manufacturing_operations t
SET pass_code = c.code
FROM codes c
WHERE t.operation_id = c.operation_id;

DROP FUNCTION _clean_num(NUMERIC);

-- migrate:down
UPDATE manufacturing_operations SET pass_code = NULL
WHERE process_category = 'sintering' AND (pass_code LIKE '%-MF%' OR pass_code LIKE 'MF-%' OR pass_code = 'MF');
