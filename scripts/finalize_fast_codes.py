#!/usr/bin/env python3
"""Assign the canonical DD-MM-YY-MF{machine}-{runno}-{params} pass_code to every sintering op.

The FAST importers insert with pass_code = NULL; this derives the code from the machine's OWN
run number carried in source_run_uid ('fast25|<VersuchNr>' / 'fast250|<No>'):

    FAST 25  run 8738  ->  08-01-24-MF25-8738-1600C_63kN
    FAST 250 run 331   ->  20-07-26-MF250-331

The machine tag (25/250) is required because VersuchNr and No overlap. source_run_uid is
uniquely indexed, so (machine, runno) — and therefore the whole code — is globally unique by
construction; no synthetic counter is needed, and the code traces straight back to the machine
program. Deterministic and idempotent (no ordering dependence), unlike the old row_number()
scheme from migration 20260711000091. Any sintering op missing source_run_uid falls back to a
date-ordered counter so it still gets a unique code.

Run AFTER the importers and the clear, BEFORE the orchestrator drain (so trace CSVs upload
under the real op code).

Usage: DATABASE_URL=… python scripts/finalize_fast_codes.py
"""

from __future__ import annotations

import os
import sys

import psycopg2

RENUMBER = """
WITH seq AS (
    SELECT operation_id,
           -- machine run tag from source_run_uid, e.g. 'fast25|8738' -> 'MF25-8738'
           CASE WHEN source_run_uid ~ '^fast[0-9]+\\|.+' THEN
               'MF' || replace(split_part(source_run_uid, '|', 1), 'fast', '')
                    || '-' || split_part(source_run_uid, '|', 2)
           END AS tag,
           -- fallback for any row without a machine run id: a date-ordered counter
           'MF' || row_number() OVER (ORDER BY operation_date, operation_id)::text AS fallback,
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
           COALESCE(seq.tag, seq.fallback),
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
