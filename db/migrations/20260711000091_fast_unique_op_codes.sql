-- migrate:up
-- FAST (sintering) operations were imported without a sample link and without a
-- sequence, so their generated codes (e.g. "MF-950C_97kN") collided heavily — one
-- code was shared by 66 operations. Rebuild every sintering pass_code as a globally
-- unique, date-stamped code:  DD-MM-YY-MF{n}-{params}
--   e.g. 22-04-21-MF1-950C_11kN_20dia
-- The MF{n} counter is a global running number over all sintering ops (ordered by
-- date), so uniqueness no longer depends on a sample or on the sinter parameters.
-- Deterministic (orders by date, then operation_id) → re-running yields identical
-- codes. code_sort is a generated column and updates automatically.

WITH seq AS (
    SELECT operation_id,
           row_number() OVER (ORDER BY operation_date, operation_id) AS n,
           concat_ws('_',
               CASE WHEN sintering_max_temp_celsius   IS NOT NULL THEN trim_scale(sintering_max_temp_celsius)::text   || 'C'   END,
               CASE WHEN sintering_max_force_kn        IS NOT NULL THEN trim_scale(sintering_max_force_kn)::text        || 'kN'  END,
               CASE WHEN sintering_mould_diameter_mm   IS NOT NULL THEN trim_scale(sintering_mould_diameter_mm)::text   || 'dia' END
           ) AS params
    FROM manufacturing_operations
    WHERE process_category = 'sintering'
)
UPDATE manufacturing_operations m
   SET pass_code = concat_ws('-',
           to_char(m.operation_date, 'DD-MM-YY'),
           'MF' || seq.n::text,
           nullif(seq.params, '')
       )
  FROM seq
 WHERE m.operation_id = seq.operation_id;

-- migrate:down
-- No meaningful revert: the previous codes were non-unique and lossy. Leaving the
-- unique codes in place on rollback is safe (they remain valid operation codes).
SELECT 1;
