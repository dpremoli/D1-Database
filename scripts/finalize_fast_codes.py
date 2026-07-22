#!/usr/bin/env python3
"""Assign the canonical DD-MM-YY-MF{n}-{params} pass_code to every sintering operation.

The FAST importers insert with pass_code = NULL; this reproduces the deterministic
renumber from migration 20260711000091 (ordered by operation_date, then operation_id) so
codes are globally unique and stable across re-runs. Run AFTER the importers and the clear,
BEFORE the orchestrator drain (so trace CSVs upload under the real op code).

Usage: DATABASE_URL=… python scripts/finalize_fast_codes.py
"""
from __future__ import annotations

import os
import sys

import psycopg2

RENUMBER = """
WITH seq AS (
    SELECT operation_id,
           row_number() OVER (ORDER BY operation_date, operation_id) AS n,
           concat_ws('_',
               CASE WHEN sintering_max_temp_celsius IS NOT NULL THEN trim_scale(sintering_max_temp_celsius)::text || 'C'   END,
               CASE WHEN sintering_max_force_kn      IS NOT NULL THEN trim_scale(sintering_max_force_kn)::text      || 'kN'  END,
               CASE WHEN sintering_mould_diameter_mm IS NOT NULL THEN trim_scale(sintering_mould_diameter_mm)::text || 'dia' END
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
"""


def main() -> None:
    dsn = os.environ.get("DATABASE_URL") or sys.exit("ERROR: DATABASE_URL required")
    conn = psycopg2.connect(dsn)
    cur = conn.cursor()
    cur.execute(RENUMBER)
    print(f"assigned pass_code to {cur.rowcount} sintering operations")
    conn.commit()
    cur.close()
    conn.close()


if __name__ == "__main__":
    main()
