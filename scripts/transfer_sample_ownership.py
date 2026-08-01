#!/usr/bin/env python3
"""Transfer sample ownership from the legacy XLSX into physical_samples.owner.

The Inventory sheet's `Owner` column holds the researcher (email or full name).
Users were imported with deterministic UUIDs (legacy_uuid('d1_user:<email>')),
so we resolve Owner → that UUID and set physical_samples.owner. Only UUIDs that
actually exist in directus_users are written (owner has no hard FK, ADR-0002).

Usage:
  DATABASE_URL=postgres://d1:change_me@localhost:5432/d1_database \\
      python scripts/transfer_sample_ownership.py "<path to Sample_Data.xlsx>"
"""
from __future__ import annotations

import os
import sys
import uuid

import openpyxl
import psycopg2

_LEGACY_NS = uuid.uuid5(uuid.NAMESPACE_DNS, "d1-database.legacy-migration.v1")


def legacy_uuid(raw: str) -> str:
    return str(uuid.uuid5(_LEGACY_NS, str(raw).strip()))


def clean(v) -> str | None:
    s = str(v).strip() if v is not None else None
    return s if s and s.lower() not in ("none", "n/a", "na") else None


def sheet_rows(wb, name):
    ws = wb[name]
    raw = list(ws.iter_rows(values_only=True))
    hdr = [str(h) for h in raw[0] if h is not None]
    out = []
    for r in raw[1:]:
        if not any(x is not None for x in r):
            continue
        out.append({hdr[i]: r[i] for i in range(min(len(hdr), len(r)))})
    return out


def main() -> None:
    xlsx = sys.argv[1]
    wb = openpyxl.load_workbook(xlsx, read_only=True, data_only=True)

    # email/name → user UUID, from the Users sheet
    email_to_uuid: dict[str, str] = {}
    name_to_uuid: dict[str, str] = {}
    for u in sheet_rows(wb, "Users"):
        email = clean(u.get("Email") or u.get("Email Address") or u.get("email"))
        first = clean(u.get("First Name") or u.get("FirstName"))
        last = clean(u.get("Last Name") or u.get("Surname") or u.get("LastName"))
        if email:
            uid = legacy_uuid(f"d1_user:{email.lower()}")
            email_to_uuid[email.lower()] = uid
            if first and last:
                name_to_uuid[f"{first} {last}".lower()] = uid
    cg = "carolina.guerra@nottingham.ac.uk"
    email_to_uuid.setdefault(cg, legacy_uuid(f"d1_user:{cg}"))

    conn = psycopg2.connect(os.environ["DATABASE_URL"])
    cur = conn.cursor()
    cur.execute("SELECT id::text FROM directus_users")
    existing = {r[0] for r in cur.fetchall()}

    updated = 0
    unresolved: set[str] = set()
    for r in sheet_rows(wb, "Inventory"):
        code = clean(r.get("Item Code"))
        owner = clean(r.get("Owner"))
        if not (code and owner):
            continue
        key = owner.lower()
        uid = email_to_uuid.get(key) or name_to_uuid.get(key)
        if uid and uid in existing:
            cur.execute(
                "UPDATE physical_samples SET owner=%s WHERE sample_code=%s",
                (uid, code),
            )
            updated += cur.rowcount
        else:
            unresolved.add(owner)
    conn.commit()
    cur.close()
    conn.close()
    print(f"Set owner on {updated} samples.")
    if unresolved:
        print(f"Unresolved owners ({len(unresolved)}): {sorted(unresolved)}")


if __name__ == "__main__":
    main()
