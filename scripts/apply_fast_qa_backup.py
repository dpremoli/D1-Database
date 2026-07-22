#!/usr/bin/env python3
"""Re-attach sheet-only QA fields (from fast_log_qa_backup) to the rebuilt runs.

The deleted sheet rows were logged as "FCT HP D 250" but actually cover mostly FAST 25 runs
(1,747 of 1,895 backup rows share a calendar day with a rebuilt FAST 25 op vs 463 for 250).
So we match against BOTH rebuilt machines. The reliable common key is (date, max_temp,
max_force) — the same key backfill_fast_times.py used — because the rebuilt FAST 25 rows
carry temp/force from the MDB. We fall back to a unique same-day run when temp/force are
absent. A backup row is applied ONLY when it resolves to exactly one op, and only fills the
columns the machine data left NULL (coshh_ref, ptc_top/bot, mass, mould, outcome_notes).

The backup table is never modified, so unmatched QA stays available for later reconciliation.

Usage: DATABASE_URL=… python scripts/apply_fast_qa_backup.py [--dry-run]
"""
from __future__ import annotations

import os
import sys

import psycopg2
import psycopg2.extras

# Candidate rebuilt sintering ops per calendar date, with temp/force for disambiguation.
CANDIDATES = """
SELECT operation_date::date AS d, operation_id,
       sintering_max_temp_celsius, sintering_max_force_kn
FROM manufacturing_operations
WHERE source_system IN ('fast_25', 'fast_250') AND process_category = 'sintering'
"""

BACKUP = """
SELECT operation_date::date AS d, max_temp_celsius, max_force_kn,
       coshh_ref, ptc_top_celsius, ptc_bot_celsius,
       mass_grams, mould_diameter_mm, outcome_notes
FROM fast_log_qa_backup
WHERE operation_date IS NOT NULL
"""


def _r(v):
    return None if v is None else round(float(v), 1)

# Fill only where the rebuilt row is currently NULL/empty.
UPDATE = """
UPDATE manufacturing_operations SET
    sintering_coshh_ref        = COALESCE(sintering_coshh_ref, %(coshh)s),
    sintering_ptc_top_celsius  = COALESCE(sintering_ptc_top_celsius, %(ptc_top)s),
    sintering_ptc_bot_celsius  = COALESCE(sintering_ptc_bot_celsius, %(ptc_bot)s),
    sintering_mass_grams       = COALESCE(sintering_mass_grams, %(mass)s),
    sintering_mould_diameter_mm= COALESCE(sintering_mould_diameter_mm, %(mould)s),
    outcome_notes = CASE WHEN NULLIF(btrim(COALESCE(outcome_notes,'')),'') IS NULL
                         THEN %(notes)s ELSE outcome_notes END,
    updated_at = now()
WHERE operation_id = %(oid)s
"""


def main() -> None:
    dry = "--dry-run" in sys.argv
    dsn = os.environ.get("DATABASE_URL") or sys.exit("ERROR: DATABASE_URL required")
    conn = psycopg2.connect(dsn)
    cur = conn.cursor()

    cur.execute(CANDIDATES)
    by_date: dict[object, list] = {}
    for d, oid, temp, force in cur.fetchall():
        by_date.setdefault(d, []).append((oid, _r(temp), _r(force)))

    cur.execute(BACKUP)
    backup = cur.fetchall()

    applied_tf = applied_day = ambiguous = nomatch = 0
    updates = []
    for d, btemp, bforce, coshh, ptc_top, ptc_bot, mass, mould, notes in backup:
        cands = by_date.get(d, [])
        if not cands:
            nomatch += 1
            continue
        oid = None
        bt, bf = _r(btemp), _r(bforce)
        if bt is not None and bf is not None:
            tf = [c for c in cands if c[1] == bt and c[2] == bf]
            if len(tf) == 1:
                oid, applied_tf = tf[0][0], applied_tf + 1
            elif len(tf) > 1:
                ambiguous += 1
                continue
        if oid is None:                       # no temp/force match — fall back to unique day
            if len(cands) == 1:
                oid, applied_day = cands[0][0], applied_day + 1
            else:
                ambiguous += 1
                continue
        updates.append({"oid": oid, "coshh": coshh, "ptc_top": ptc_top, "ptc_bot": ptc_bot,
                        "mass": mass, "mould": mould, "notes": notes})

    print(f"backup rows: {len(backup)}")
    print(f"  matched by (date,temp,force): {applied_tf}")
    print(f"  matched by unique same-day run: {applied_day}")
    print(f"  ambiguous (skipped): {ambiguous}")
    print(f"  no rebuilt run that day: {nomatch}")

    if dry:
        print("[dry-run] no writes.")
        cur.close(); conn.close(); return

    for u in updates:
        cur.execute(UPDATE, u)
    conn.commit()
    print(f"applied QA to {len(updates)} operations (only filled NULL fields)")
    cur.close()
    conn.close()


if __name__ == "__main__":
    main()
