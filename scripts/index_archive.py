#!/usr/bin/env python3
"""Index the read-only SMB archive into the Directus File Library.

Walks the star_group1 subtree of the university file store and registers each
link-worthy file as a *pointer* row in directus_files (storage='star'), mirroring
the directory tree into directus_folders. No bytes are copied: Directus and the
worker plugins read the file from their own read-only `/mnt/archive` mount, and
the canonical relative path is also stored in directus_files.metadata.archive_path
so plugins can resolve a link without depending on filename_disk.

This makes the archive browsable in the Directus File Library (click-through, like
Explorer) so users can link a specific file to a manufacturing operation via the
"Linked Data Files" picker. It does NOT serve downloads through Directus.

Idempotent: folder/file IDs are deterministic (uuid5 of the relative path), so
re-runs upsert in place — safe as a nightly cron to keep the index current.

Usage
-----
    # In a container with the archive_share volume + DB on the compose network:
    make index-archive

    # On the host, against the mapped drive and the local DB:
    DATABASE_URL="postgres://d1:change_me@localhost:5432/d1_database" \
        ARCHIVE_ROOT='Z:\\star_group1' python scripts/index_archive.py

    # Preview only (no DB writes):
    ... python scripts/index_archive.py --dry-run

Environment
-----------
    DATABASE_URL   required — Postgres DSN.
    ARCHIVE_ROOT   path to the star_group1 root (default /mnt/archive/star_group1).
                   MUST equal Directus's STORAGE_STAR_ROOT so filename_disk resolves.
    STORAGE_NAME   Directus storage location name (default 'star').
    ROOT_FOLDER    File Library name for the top folder (default 'star_group1').
"""

from __future__ import annotations

import argparse
import json
import logging
import mimetypes
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import PurePosixPath

# psycopg2 is imported lazily inside main() so --dry-run needs no DB driver.

log = logging.getLogger("index_archive")

# Deterministic namespace — every run produces the same IDs for the same paths,
# so re-runs upsert rather than duplicate.
_NS = uuid.uuid5(uuid.NAMESPACE_DNS, "d1-database.archive-index.v1")

# Only these extensions are linked: matlab, word, pdf, excel, csv, tiff, ebsd.
ALLOWED_EXT = {
    ".mat", ".m", ".fig", ".mlx",          # MATLAB
    ".doc", ".docx",                         # Word
    ".pdf",                                   # PDF
    ".xls", ".xlsx", ".csv",                # Excel / CSV
    ".tif", ".tiff",                         # TIFF
    ".h5oina", ".ctf", ".ang", ".cpr", ".crc",  # EBSD
}

# mimetypes doesn't know the science formats; give Directus something sensible.
_EXTRA_MIME = {
    ".mat": "application/x-matlab-data",
    ".fig": "application/x-matlab-figure",
    ".mlx": "application/x-matlab-live-script",
    ".m": "text/x-matlab",
    ".h5oina": "application/x-hdf5",
    ".ctf": "application/octet-stream",
    ".ang": "application/octet-stream",
    ".cpr": "application/octet-stream",
    ".crc": "application/octet-stream",
}

# directus_files.filename_disk is varchar(255). Deep archive paths can exceed that;
# when they do we leave filename_disk NULL (the link still works via archive_path).
_FILENAME_DISK_MAX = 255

BATCH = 1000


def folder_id(relpath: str) -> uuid.UUID:
    return uuid.uuid5(_NS, "folder:" + relpath)


def file_id(relpath: str) -> uuid.UUID:
    return uuid.uuid5(_NS, "file:" + relpath)


def guess_type(name: str) -> str | None:
    ext = PurePosixPath(name).suffix.lower()
    if ext in _EXTRA_MIME:
        return _EXTRA_MIME[ext]
    return mimetypes.guess_type(name)[0]


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true", help="count only; no DB writes")
    ap.add_argument("--root", default=os.environ.get("ARCHIVE_ROOT", "/mnt/archive/star_group1"))
    args = ap.parse_args()

    root = args.root
    storage = os.environ.get("STORAGE_NAME", "star")
    root_folder_name = os.environ.get("ROOT_FOLDER", "star_group1")

    if not os.path.isdir(root):
        log.error("ARCHIVE_ROOT does not exist or is not a directory: %s", root)
        return 2

    conn = None
    if not args.dry_run:
        import psycopg2
        import psycopg2.extras
        dsn = os.environ.get("DATABASE_URL")
        if not dsn:
            log.error("DATABASE_URL is required (omit only with --dry-run)")
            return 2
        conn = psycopg2.connect(dsn)
        conn.autocommit = False

    now = datetime.now(timezone.utc)
    # Folders we've already ensured this run (memoised) → avoid redundant upserts.
    seen_folders: set[str] = set()
    folder_rows: list[tuple] = []
    file_rows: list[tuple] = []
    n_files = 0
    n_skipped = 0

    def flush_folders() -> None:
        if not folder_rows or conn is None:
            folder_rows.clear()
            return
        with conn.cursor() as cur:
            psycopg2.extras.execute_values(
                cur,
                "INSERT INTO directus_folders (id, name, parent) VALUES %s "
                "ON CONFLICT (id) DO NOTHING",
                folder_rows,
            )
        folder_rows.clear()

    def flush_files() -> None:
        if not file_rows or conn is None:
            file_rows.clear()
            return
        with conn.cursor() as cur:
            psycopg2.extras.execute_values(
                cur,
                """
                INSERT INTO directus_files
                    (id, storage, filename_disk, filename_download, type, folder,
                     filesize, metadata, created_on, modified_on, uploaded_on)
                VALUES %s
                ON CONFLICT (id) DO UPDATE SET
                    storage           = EXCLUDED.storage,
                    filename_disk     = EXCLUDED.filename_disk,
                    filename_download = EXCLUDED.filename_download,
                    type              = EXCLUDED.type,
                    folder            = EXCLUDED.folder,
                    filesize          = EXCLUDED.filesize,
                    metadata          = EXCLUDED.metadata,
                    modified_on       = EXCLUDED.modified_on
                """,
                file_rows,
            )
        file_rows.clear()

    def ensure_folder(rel_dir: str) -> uuid.UUID:
        """Ensure the folder row (and all its ancestors) exist; return its id."""
        fid = folder_id(rel_dir)
        if rel_dir in seen_folders:
            return fid
        if rel_dir == "":
            folder_rows.append((str(fid), root_folder_name, None))
        else:
            parent = PurePosixPath(rel_dir).parent
            parent_rel = "" if str(parent) == "." else str(parent)
            parent_id = ensure_folder(parent_rel)
            folder_rows.append((str(fid), PurePosixPath(rel_dir).name, str(parent_id)))
        seen_folders.add(rel_dir)
        return fid

    ensure_folder("")  # the top-level star_group1 folder

    for dirpath, _dirnames, filenames in os.walk(root):
        rel_dir_os = os.path.relpath(dirpath, root)
        rel_dir = "" if rel_dir_os == "." else PurePosixPath(*PurePosixPath(rel_dir_os.replace(os.sep, "/")).parts).as_posix()
        dir_fid = None  # resolved lazily, only if this dir has an allowed file

        for name in filenames:
            ext = PurePosixPath(name).suffix.lower()
            if ext not in ALLOWED_EXT:
                n_skipped += 1
                continue

            rel = name if rel_dir == "" else f"{rel_dir}/{name}"
            try:
                size = os.path.getsize(os.path.join(dirpath, name))
            except OSError as exc:  # transient SMB hiccup — skip, next run picks it up
                log.warning("stat failed, skipping %s: %s", rel, exc)
                continue

            if dir_fid is None:
                dir_fid = ensure_folder(rel_dir)

            fid = str(file_id(rel))
            filename_disk = rel if len(rel) <= _FILENAME_DISK_MAX else None
            metadata = json.dumps({
                "archive_path": rel,                       # canonical link, relative to star_group1
                "source": "uosfstore/shared/star_group1",
            })
            file_rows.append((
                fid, storage, filename_disk, name, guess_type(name), str(dir_fid),
                size, metadata, now, now, now,
            ))
            n_files += 1

            if len(file_rows) >= BATCH:
                flush_folders()  # parents before children (FK-free, but keeps order sane)
                flush_files()
                if conn is not None:
                    conn.commit()
                log.info("indexed %d files (%d skipped)…", n_files, n_skipped)

    flush_folders()
    flush_files()
    if conn is not None:
        conn.commit()
        conn.close()

    verb = "would index" if args.dry_run else "indexed"
    log.info("Done: %s %d files into %d folders (%d non-matching files skipped).",
             verb, n_files, len(seen_folders), n_skipped)
    return 0


if __name__ == "__main__":
    sys.exit(main())
