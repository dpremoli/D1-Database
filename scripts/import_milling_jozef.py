#!/usr/bin/env python3
"""One-off: create milling operations for Jozef's trial .mat files.

The 19 force .mat files under
  Shared/Machining/FRM/8. Milling trials (Jozef)/1. Data/1. MAT/
are already indexed in directus_files but had no operations. This creates one
milling operation per file (method MM=Milling, process_category=machining, owner
Jozef McGowan, campaign "Milling Trials Joszef"), links the file via
operation_data_files, and is idempotent (deterministic uuid5 + ON CONFLICT /
NOT EXISTS). Afterwards run `force_orchestrator.py --discover` to enqueue the
force analysis (the running daemon then processes them).

Env: DATABASE_URL.
"""
import os
import re
import sys
import uuid

import psycopg2
import psycopg2.extras

NS = uuid.uuid5(uuid.NAMESPACE_DNS, "d1-database.milling-jozef.v1")

CAMPAIGN_ID = "d89b3eab-65df-474e-89ac-44488102ebfe"   # "Milling Trials Joszef" (code 8)
MM_METHOD_ID = "5834e821-4e0b-5e21-8584-b7f0f06e8983"  # Milling
JOZEF_PERSON = "a00a130e-3e3d-4a1a-89cd-702cc9dc4d7c"
JOZEF_USER = "a70c22ae-7a95-5cd7-8350-0336c539d226"
PATH_LIKE = "Shared/Machining/FRM/8. Milling trials%1. MAT/%"


def parse_date(sample_code: str):
    m = re.search(r"(\d{4})-(\d{1,2})-(\d{1,2})", sample_code)
    if not m:
        return None
    y, mo, d = m.groups()
    return f"{y}-{int(mo):02d}-{int(d):02d}"


def main():
    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        print("DATABASE_URL required", file=sys.stderr)
        sys.exit(2)
    conn = psycopg2.connect(dsn)
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    # canonical Shared/ copies of the milling .mat files (skip the User/ duplicates)
    cur.execute("""
        SELECT id, metadata->>'archive_path' AS path
        FROM directus_files
        WHERE metadata->>'archive_path' ILIKE %s
          AND lower(metadata->>'archive_path') LIKE '%%.mat'
        ORDER BY 2
    """, [PATH_LIKE])
    files = cur.fetchall()
    print(f"found {len(files)} milling .mat files")

    made_ops = made_links = skipped_nosample = 0
    for f in files:
        stem = os.path.splitext(os.path.basename(f["path"]))[0]         # e.g. 16-AA-MO-2017-6-18_Step1
        sample_code = stem.split("_")[0]                                 # 16-AA-MO-2017-6-18
        cur.execute("SELECT sample_id FROM physical_samples WHERE sample_code=%s", [sample_code])
        srow = cur.fetchone()
        if not srow:
            print(f"  ! no sample for {sample_code} ({stem}) — skipping")
            skipped_nosample += 1
            continue
        sample_id = srow["sample_id"]
        op_id = str(uuid.uuid5(NS, f"op:{stem}"))
        op_date = parse_date(sample_code)

        cur.execute("""
            INSERT INTO manufacturing_operations
                (operation_id, method_id, process_category, machining_operation_subtype,
                 sample_id, owner, owner_person_id, operator_name, campaign_id,
                 operation_date, pass_code, force_file_id)
            VALUES (%s, %s, 'machining', NULL, %s, %s, %s, 'Jozef McGowan', %s, %s, %s, %s)
            ON CONFLICT (operation_id) DO NOTHING
        """, [op_id, MM_METHOD_ID, sample_id, JOZEF_USER, JOZEF_PERSON, CAMPAIGN_ID,
              op_date, stem, stem])
        made_ops += cur.rowcount

        cur.execute("""
            INSERT INTO operation_data_files (operation_id, directus_files_id)
            SELECT %s, %s
            WHERE NOT EXISTS (
                SELECT 1 FROM operation_data_files
                WHERE operation_id=%s AND directus_files_id=%s)
        """, [op_id, f["id"], op_id, f["id"]])
        made_links += cur.rowcount

    conn.commit()
    print(f"operations created: {made_ops} | data-file links: {made_links} | skipped (no sample): {skipped_nosample}")
    conn.close()


if __name__ == "__main__":
    main()
