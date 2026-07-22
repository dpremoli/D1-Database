#!/usr/bin/env python3
r"""Host-side importer: populate fast_run_data from FAST sintering trace CSVs.

The FAST machines (FCT HP D 25 / 250) export raw per-run CSVs in two different
shapes. This script normalises either shape into one canonical comma/US-decimal CSV
(via scripts/fast_mapping.normalize_fast_csv), uploads it to Directus renamed to the
operation code, and records the series catalog + run metadata in fast_run_data. The
d1-fast-dashboard then fetches the CSV and plots it.

Two sources (the archive share is host-only, so both funnel through this one host
normaliser):
    * staged_file        — a raw CSV the user uploaded through the dashboard (fetched
                           back from Directus, normalised, replaced with <op_code>.csv)
    * import_archive_path — a path in the archive index the user picked (read directly)

Modes
-----
    # process every pending fast_run_data row once:
        py scripts/fast_orchestrator.py --run

    # one-off import of a specific archive CSV for an operation:
        py scripts/fast_orchestrator.py --import \
            --archive-path 'Shared/Machining/FRM/8. Milling.../x.CSV' --operation <uuid>

    # daemon: poll fast_run_data for pending imports forever
        py scripts/fast_orchestrator.py --daemon

Environment: DATABASE_URL, DIRECTUS_URL, DIRECTUS_ADMIN_EMAIL/PASSWORD, ARCHIVE_UNC.
NOTE: like force_orchestrator, a running --daemon does NOT reload edited source —
restart it after changing this script or fast_mapping.py.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
import time
from pathlib import Path

import psycopg2
import psycopg2.extras
import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fast_mapping import normalize_fast_csv  # noqa: E402

log = logging.getLogger("fast_orchestrator")

ARCHIVE_UNC = os.environ.get("ARCHIVE_UNC", r"\\uosfstore.shef.ac.uk\shared\star_group1")
DIRECTUS_URL = os.environ.get("DIRECTUS_URL", "http://localhost:8055").rstrip("/")
TRACES_FOLDER_NAME = os.environ.get("FAST_TRACES_FOLDER_NAME", "FAST Traces")


def unc_for(archive_path: str) -> str:
    """POSIX-relative archive_path -> full UNC path on the read-only share."""
    return ARCHIVE_UNC + "\\" + archive_path.replace("/", "\\")


def safe_filename(code: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", code or "fast").strip("_") + ".csv"


# --------------------------------------------------------------------- directus
class Directus:
    def __init__(self):
        self.enabled = bool(os.environ.get("DIRECTUS_ADMIN_EMAIL"))
        self._token = None
        self._folder_id = None

    def _login(self):
        r = requests.post(f"{DIRECTUS_URL}/auth/login", json={
            "email": os.environ["DIRECTUS_ADMIN_EMAIL"],
            "password": os.environ.get("DIRECTUS_ADMIN_PASSWORD", ""),
        }, timeout=30)
        r.raise_for_status()
        self._token = r.json()["data"]["access_token"]

    def _hdr(self):
        if self._token is None:
            self._login()
        return {"Authorization": f"Bearer {self._token}"}

    def _folder(self):
        if self._folder_id:
            return self._folder_id
        q = requests.get(f"{DIRECTUS_URL}/folders", headers=self._hdr(),
                         params={"filter[name][_eq]": TRACES_FOLDER_NAME, "limit": 1}, timeout=30)
        q.raise_for_status()
        found = q.json().get("data") or []
        if found:
            self._folder_id = found[0]["id"]
        else:
            c = requests.post(f"{DIRECTUS_URL}/folders", headers=self._hdr(),
                              json={"name": TRACES_FOLDER_NAME}, timeout=30)
            c.raise_for_status()
            self._folder_id = c.json()["data"]["id"]
        return self._folder_id

    def download(self, file_id: str) -> bytes:
        for attempt in (1, 2):
            r = requests.get(f"{DIRECTUS_URL}/assets/{file_id}", headers=self._hdr(), timeout=120)
            if r.status_code == 401 and attempt == 1:
                self._token = None
                continue
            r.raise_for_status()
            return r.content

    def upload_csv(self, name: str, data: bytes) -> str:
        folder = self._folder()
        for attempt in (1, 2):
            r = requests.post(f"{DIRECTUS_URL}/files", headers=self._hdr(),
                              data={"title": name, "folder": folder},
                              files={"file": (name, data, "text/csv")}, timeout=120)
            if r.status_code == 401 and attempt == 1:
                self._token = None
                continue
            r.raise_for_status()
            return r.json()["data"]["id"]

    def delete_file(self, file_id):
        if not file_id:
            return
        try:
            requests.delete(f"{DIRECTUS_URL}/files/{file_id}", headers=self._hdr(), timeout=30)
        except requests.RequestException:
            pass


# ------------------------------------------------------------------------- db
def connect():
    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        log.error("DATABASE_URL is required")
        sys.exit(2)
    return psycopg2.connect(dsn)


def op_code(conn, operation_id: str) -> str:
    with conn.cursor() as cur:
        cur.execute("SELECT pass_code FROM manufacturing_operations WHERE operation_id=%s", [operation_id])
        row = cur.fetchone()
    return (row[0] if row and row[0] else str(operation_id)[:8])


def claim_pending(conn, limit: int):
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("""
            WITH picked AS (
                SELECT id FROM fast_run_data WHERE status='pending'
                ORDER BY created_at LIMIT %s FOR UPDATE SKIP LOCKED
            )
            UPDATE fast_run_data f SET status='processing', updated_at=now()
              FROM picked WHERE f.id = picked.id
         RETURNING f.id, f.operation_id, f.staged_file, f.import_archive_path,
                   f.directus_files_id AS old_file
        """, [limit])
        rows = cur.fetchall()
    conn.commit()
    return rows


def ensure_row(conn, operation_id: str, *, archive_path=None, staged_file=None):
    """Create or reset a fast_run_data row to pending for an operation (upsert)."""
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO fast_run_data (operation_id, status, import_archive_path, staged_file)
            VALUES (%s, 'pending', %s, %s)
            ON CONFLICT (operation_id) DO UPDATE
               SET status='pending', import_archive_path=EXCLUDED.import_archive_path,
                   staged_file=EXCLUDED.staged_file, error_message=NULL, updated_at=now()
        """, [operation_id, archive_path, staged_file])
    conn.commit()


# -------------------------------------------------------------------- process
def process_row(conn, directus: Directus, row) -> str:
    """Normalise + upload one claimed row. Returns 'done' | 'error'."""
    fid = row["id"]
    try:
        if row.get("staged_file"):
            raw = directus.download(row["staged_file"])
        elif row.get("import_archive_path"):
            raw = Path(unc_for(row["import_archive_path"])).read_bytes()
        else:
            raise ValueError("no staged_file or import_archive_path to import from")

        res = normalize_fast_csv(raw)
        code = op_code(conn, row["operation_id"])
        new_file = directus.upload_csv(safe_filename(code), res["csv_text"].encode("utf-8"))

        with conn.cursor() as cur:
            cur.execute("""
                UPDATE fast_run_data SET
                    status='done', error_message=NULL, directus_files_id=%s,
                    machine_format=%s, plant=%s, recipe=%s, run_start=%s,
                    n_rows=%s, duration_s=%s, series=%s::jsonb, summary=%s::jsonb,
                    staged_file=NULL, import_archive_path=NULL,
                    processed_at=now(), updated_at=now()
                WHERE id=%s
            """, [new_file, res["format"], res["plant"], res["recipe"], res["run_start"],
                  res["n_rows"], res["duration_s"], json.dumps(res["columns"]),
                  json.dumps(res.get("summary") or {}), fid])
        conn.commit()

        # tidy: delete superseded normalised file + the staging raw
        if row.get("old_file") and row["old_file"] != new_file:
            directus.delete_file(row["old_file"])
        if row.get("staged_file"):
            directus.delete_file(row["staged_file"])
        log.info("[DONE] %s -> %s (%d rows, %d series)", code, safe_filename(code), res["n_rows"], len(res["columns"]))
        return "done"
    except Exception as e:  # noqa: BLE001
        conn.rollback()
        with conn.cursor() as cur:
            cur.execute("UPDATE fast_run_data SET status='error', error_message=%s, "
                        "staged_file=NULL, import_archive_path=NULL, updated_at=now() WHERE id=%s",
                        [str(e)[:2000], fid])
        conn.commit()
        log.error("[ERROR] row %s: %s", fid, e)
        return "error"


def run_once(conn, directus: Directus, limit: int) -> int:
    total = 0
    while True:
        rows = claim_pending(conn, min(5, limit - total) if limit else 5)
        if not rows:
            break
        for r in rows:
            process_row(conn, directus, r)
            total += 1
        if limit and total >= limit:
            break
    return total


# --------------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", action="store_true", help="process all pending rows once")
    ap.add_argument("--import", dest="do_import", action="store_true", help="enqueue one archive import (needs --archive-path + --operation)")
    ap.add_argument("--archive-path", help="archive path (POSIX-relative) to normalise")
    ap.add_argument("--operation", help="operation_id (uuid) for --import")
    ap.add_argument("--daemon", action="store_true", help="poll pending imports forever")
    ap.add_argument("--poll", type=float, default=5.0, help="daemon poll seconds (default 5)")
    ap.add_argument("--limit", type=int, default=0, help="max rows this run (0 = all)")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()

    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S")
    conn = connect()
    directus = Directus()
    if not directus.enabled:
        log.error("DIRECTUS_ADMIN_EMAIL unset — cannot upload normalised CSVs")
        sys.exit(2)
    log.info("FAST importer  archive: %s  directus: %s", ARCHIVE_UNC, DIRECTUS_URL)

    if args.do_import:
        if not (args.archive_path and args.operation):
            log.error("--import needs --archive-path and --operation")
            sys.exit(2)
        ensure_row(conn, args.operation, archive_path=args.archive_path)
        n = run_once(conn, directus, 1)
        log.info("import: processed %d row(s)", n)
        return

    if args.daemon:
        log.info("daemon started (pid=%d); polling fast_run_data", os.getpid())
        while True:
            try:
                run_once(conn, directus, 0)
            except psycopg2.Error as e:
                log.error("db error: %s", e)
                conn.rollback()
            time.sleep(args.poll)

    # default: --run
    n = run_once(conn, directus, args.limit)
    log.info("run: processed %d row(s)", n)


if __name__ == "__main__":
    main()