#!/usr/bin/env python3
"""Backfill the clock time into manufacturing_operations.operation_date for FAST/SPS runs.

The original import stored the date only. The source log sheets carry a per-run time, but
they're a living document (rows edited/added since import), so the deterministic
source_run_uid no longer matches for most rows. Instead we match on STABLE fields that are
also stored in the DB:

  Tier 1: (recipe, batch, max_temp, max_force)  — a press cycle is unique by its results
  Tier 2: (date, recipe, batch)                 — fallback for runs missing temp/force

A key is only used when it maps to a single distinct time on the source side AND the DB op
is still at midnight (so we never overwrite an already-timed value). Only the time is set;
the (already date-corrected) date is preserved.

Usage: DATABASE_URL=… python /scripts/backfill_fast_times.py /data [--dry-run]
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import psycopg2
import psycopg2.extras
from import_fast_logs import clean_code, clean_float, fmt_date, fmt_time, read_runs


def rnum(v):
    f = clean_float(v)
    return None if f is None else f"{round(f, 1)}"


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    folder = args[0] if args else "/data"
    dry = "--dry-run" in sys.argv

    # source: build measurement-key and date-key -> set of times
    m_src: dict[str, set] = {}
    d_src: dict[str, set] = {}
    for r in read_runs(folder):
        t = fmt_time(r.get("time"))
        if not t or ":" not in t:
            continue
        d = fmt_date(r.get("date"))
        recipe = clean_code(r.get("recipe")) or ""
        batch = clean_code(r.get("batch")) or ""
        temp, force = rnum(r.get("maxtemp")), rnum(r.get("maxforce"))
        if temp and force:
            m_src.setdefault(f"{recipe}|{batch}|{temp}|{force}", set()).add(t)
        if d is not None:
            d_src.setdefault(f"{d}|{recipe}|{batch}", set()).add(t)
    m_uni = {k: next(iter(v)) for k, v in m_src.items() if len(v) == 1}
    d_uni = {k: next(iter(v)) for k, v in d_src.items() if len(v) == 1}
    print(f"source unique measurement-keys: {len(m_uni)}   date-keys: {len(d_uni)}")

    db = os.environ.get("DATABASE_URL") or sys.exit("ERROR: DATABASE_URL required")
    conn = psycopg2.connect(db)
    cur = conn.cursor()
    cur.execute("SET TIME ZONE 'UTC'")
    cur.execute("""
        SELECT operation_id, operation_date::date::text,
               sintering_recipe_number, sintering_batch_number,
               sintering_max_temp_celsius, sintering_max_force_kn
        FROM manufacturing_operations
        WHERE source_system='fast_log' AND operation_date IS NOT NULL
          AND operation_date::time = '00:00:00'
    """)
    updates, t1, t2 = [], 0, 0
    for oid, d, recipe, batch, temp, force in cur.fetchall():
        recipe, batch = recipe or "", batch or ""
        temp, force = (
            (f"{round(float(temp), 1)}" if temp is not None else None),
            (f"{round(float(force), 1)}" if force is not None else None),
        )
        t = None
        if temp and force:
            t = m_uni.get(f"{recipe}|{batch}|{temp}|{force}")
            if t:
                t1 += 1
        if not t:
            t = d_uni.get(f"{d}|{recipe}|{batch}")
            if t:
                t2 += 1
        if t:
            updates.append((oid, f"{d} {t}"))
    print(f"matched: {len(updates)}  (tier1 measurement={t1}, tier2 date={t2})")

    if dry:
        for oid, ts in updates[:5]:
            print("   e.g.", oid, "->", ts)
        cur.close()
        conn.close()
        return

    psycopg2.extras.execute_values(
        cur,
        "UPDATE manufacturing_operations o SET operation_date = v.ts::timestamp "
        "FROM (VALUES %s) AS v(oid, ts) WHERE o.operation_id = v.oid::uuid",
        updates,
    )
    print(f"updated: {cur.rowcount}")
    conn.commit()
    cur.close()
    conn.close()


if __name__ == "__main__":
    main()
