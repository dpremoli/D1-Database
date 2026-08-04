#!/usr/bin/env python3
r"""Host-side orchestrator: populate machining_force_analysis from archive .mat files.

Runs on the Windows host (which alone can reach the Kerberos/DFS archive share and
the local DB + Directus). For each machining operation that has a `.mat` force file
linked (via operation_data_files), it invokes scripts/matlab/process_force.m
*read-only* over the file, then ingests the JSON metrics + downsampled series/fft
into machining_force_analysis and uploads the FRM fingerprint PNG to Directus.

The archive is only ever read: process_force.m opens the .mat non-writable and this
script never writes back to the share.

Two phases (run together by default, or separately):
    --discover   scan operation_data_files, enqueue pending rows (idempotent)
    --run        claim pending rows and process them (bounded parallelism + throttle)

Usage
-----
    # one-off, scoped to a single sample's files, verbose:
    DATABASE_URL=postgres://d1:change_me@localhost:5432/d1_database \
    DIRECTUS_URL=http://localhost:8055 \
    DIRECTUS_ADMIN_EMAIL=admin@example.com DIRECTUS_ADMIN_PASSWORD=change_me_admin \
        py scripts/force_orchestrator.py --discover --run --file-like '%10-AA-MF%' -v

    # background crawler: 2 MATLAB workers, 5 s between launches, 200 files/pass:
        py scripts/force_orchestrator.py --discover --run --workers 2 --throttle 5 --limit 200

    # requeue failures / reprocess everything:
        py scripts/force_orchestrator.py --discover --retry-errors
        py scripts/force_orchestrator.py --discover --reprocess --file-like '%FRM%'

    # daemon mode: runs forever, polling force_crawler_state (a Directus singleton)
    # for live workers/throttle/scope + a running/paused toggle. This is what the
    # d1-force-crawler admin module controls — start it once on the host, then
    # drive it from the browser:
        py scripts/force_orchestrator.py --daemon

Environment
-----------
    DATABASE_URL            required — Postgres DSN.
    ARCHIVE_UNC             archive root (default \\uosfstore.shef.ac.uk\shared\star_group1).
    MATLAB_EXE              matlab.exe (default auto-detected under C:\Program Files\MATLAB).
    DIRECTUS_URL            default http://localhost:8055.
    DIRECTUS_ADMIN_EMAIL / DIRECTUS_ADMIN_PASSWORD   for FRM upload (login → token).
    FORCE_WORKDIR           scratch dir for MATLAB outputs (default: system temp).
"""

from __future__ import annotations

import argparse
import concurrent.futures
import glob
import json
import logging
import os
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

import psycopg2
import psycopg2.extras
import requests

log = logging.getLogger("force_orchestrator")

SCRIPT_DIR = Path(__file__).resolve().parent
MATLAB_SRC = SCRIPT_DIR / "matlab"  # holds process_force.m

ARCHIVE_UNC = os.environ.get(
    "ARCHIVE_UNC", r"\\uosfstore.shef.ac.uk\shared\star_group1"
)
DIRECTUS_URL = os.environ.get("DIRECTUS_URL", "http://localhost:8055").rstrip("/")

# Phase 2 Potree octrees: PotreeConverter builds them from a LAS; they are written under
# OCTREE_DIR (the Caddy-served ./infra/octrees mount) as <op_id>/ and streamed by the
# browser. POTREE_CONVERTER is auto-detected if unset.
OCTREE_DIR = Path(
    os.environ.get("OCTREE_DIR", str(SCRIPT_DIR.parent / "infra" / "octrees"))
)


def detect_potree_converter() -> str | None:
    env = os.environ.get("POTREE_CONVERTER")
    if env and Path(env).exists():
        return env
    cands = glob.glob(
        os.path.expanduser(r"~/Downloads/PotreeConverter*/**/PotreeConverter.exe"),
        recursive=True,
    )
    cands += glob.glob(r"C:\Program Files\PotreeConverter*\PotreeConverter.exe")
    return cands[0] if cands else None


# Scalar columns written from summary.json (JSON key == column name).
SUMMARY_COLS = [
    "file_version",
    "sample_rate",
    "feed",
    "cut_diameter",
    "surface_speed",
    "depth_of_cut",
    "max_rpm",
    "dyno_gain",
    "n_raw",
    "cut_start_idx",
    "cut_end_idx",
    "peak_fx",
    "peak_fy",
    "peak_fz",
    "mean_rpm",
    "trigger_time",
    "pulses_per_rev",
]
# process_force emits `version` not `file_version`.
SUMMARY_ALIASES = {"file_version": "version"}


# --------------------------------------------------------------------------- env
def detect_matlab() -> str:
    exe = os.environ.get("MATLAB_EXE")
    if exe and Path(exe).exists():
        return exe
    cands = sorted(glob.glob(r"C:\Program Files\MATLAB\*\bin\matlab.exe"), reverse=True)
    if not cands:
        log.error("matlab.exe not found; set MATLAB_EXE")
        sys.exit(2)
    return cands[0]


def matlab_release(exe: str) -> str:
    m = re.search(r"MATLAB\\(R20\d\d[ab])\\", exe)
    return m.group(1) if m else "unknown"


def unc_for(archive_path: str) -> str:
    """POSIX-relative archive_path -> full UNC path on the read-only share."""
    return ARCHIVE_UNC + "\\" + archive_path.replace("/", "\\")


def mlq(s: str) -> str:
    """Escape a string for a MATLAB single-quoted literal."""
    return s.replace("'", "''")


# ----------------------------------------------------------------------- discover
def _scope_sql(args):
    """Scope for the discovery INSERT, whose SELECT already joins df + mo."""
    frag, params = [], []
    if args.file_like:
        frag.append("df.metadata->>'archive_path' ILIKE %s")
        params.append(args.file_like)
    if args.op_code:
        frag.append("mo.operation_code ILIKE %s")
        params.append(args.op_code)
    if args.file_id:
        frag.append("df.id = %s")
        params.append(args.file_id)
    return (" AND " + " AND ".join(frag)) if frag else "", params


def _scope_exists(args, alias="a"):
    """Scope for queries over machining_force_analysis rows, via EXISTS on the
    row's own file/op — no joins, so no row multiplication or FOR UPDATE clashes."""
    frag, params = [], []
    fconds, fparams = [], []
    if args.file_like:
        fconds.append("df.metadata->>'archive_path' ILIKE %s")
        fparams.append(args.file_like)
    if args.file_id:
        fconds.append("df.id = %s")
        fparams.append(args.file_id)
    if fconds:
        frag.append(
            f"EXISTS (SELECT 1 FROM directus_files df "
            f"WHERE df.id = {alias}.directus_files_id AND {' AND '.join(fconds)})"
        )
        params.extend(fparams)
    if args.op_code:
        frag.append(
            f"EXISTS (SELECT 1 FROM manufacturing_operations mo "
            f"WHERE mo.operation_id = {alias}.operation_id AND mo.operation_code ILIKE %s)"
        )
        params.append(args.op_code)
    return (" AND " + " AND ".join(frag)) if frag else "", params


def reset_stale_processing(conn, minutes: int = 30) -> int:
    """Rows stuck in 'processing' with no worker actually running them (the daemon
    was killed/crashed/restarted mid-batch — claim_batch flips status to 'processing'
    BEFORE the work starts, and until this existed nothing ever put them back). Safe
    to run anytime: a row genuinely still being processed just got updated recently,
    so it won't match the staleness window."""
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE machining_force_analysis
               SET status='pending', updated_at=now()
             WHERE status='processing' AND updated_at < now() - (%s || ' minutes')::interval
        """,
            [minutes],
        )
        n = cur.rowcount
    conn.commit()
    if n:
        log.info(
            "reset %d stale 'processing' row(s) (older than %d min) back to pending",
            n,
            minutes,
        )
    return n


def discover(conn, args) -> int:
    scope, sparams = _scope_sql(args)
    with conn.cursor() as cur:
        # 1. enqueue never-seen .mat files
        cur.execute(
            f"""
            INSERT INTO machining_force_analysis (operation_id, directus_files_id, fingerprint, status)
            SELECT od.operation_id, df.id, df.metadata->>'fingerprint', 'pending'
            FROM operation_data_files od
            JOIN directus_files df ON df.id = od.directus_files_id
            JOIN manufacturing_operations mo ON mo.operation_id = od.operation_id
            WHERE lower(df.metadata->>'archive_path') LIKE '%%.mat'
              AND NOT EXISTS (SELECT 1 FROM machining_force_analysis a WHERE a.directus_files_id = df.id)
              {scope}
            ON CONFLICT (directus_files_id) DO NOTHING
        """,
            sparams,
        )
        inserted = cur.rowcount

        # 2. reset rows that should be re-run (reprocess / retry errors / stale file)
        escope, eparams = _scope_exists(args, "a")
        cur.execute(
            f"""
            UPDATE machining_force_analysis a
               SET status='pending', error_message=NULL, updated_at=now()
              FROM directus_files df
             WHERE a.directus_files_id = df.id
               AND a.status <> 'pending'
               AND ( %s
                     OR (a.status = 'error' AND %s)
                     OR (a.status = 'done'  AND a.fingerprint IS DISTINCT FROM df.metadata->>'fingerprint') )
               {escope}
        """,
            [args.reprocess, args.retry_errors, *eparams],
        )
        reset = cur.rowcount
    conn.commit()
    log.info("discover: %d new enqueued, %d reset to pending", inserted, reset)
    return inserted + reset


def _octree_threshold(conn) -> int:
    """The point count above which an op is served as an octree (force_crawler_state.
    octree_threshold, falling back to live_cache_points, then 5M)."""
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT COALESCE(octree_threshold, live_cache_points, 5000000) "
                "FROM force_crawler_state WHERE id='00000000-0000-0000-0000-000000000001'"
            )
            row = cur.fetchone()
        if row and row[0]:
            return int(row[0])
    except psycopg2.Error:
        conn.rollback()
    return 5_000_000


def enqueue_pregen_octrees(conn) -> int:
    """Pre-build the (raw) Potree octree for every processed op whose full-resolution point
    count exceeds the auto-route threshold and doesn't have one yet — so large maps open in
    Full mode instantly instead of waiting minutes for an on-demand build. Idempotent: only
    touches rows with no octree (octree_status IS NULL). The grid octree stays on-demand."""
    threshold = _octree_threshold(conn)
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE machining_force_analysis
               SET octree_status='pending', octree_requested_at=now(), updated_at=now()
             WHERE status='done'
               AND octree_status IS NULL
               AND cut_start_idx IS NOT NULL AND cut_end_idx IS NOT NULL
               AND (cut_end_idx - cut_start_idx) > %s
        """,
            [threshold],
        )
        n = cur.rowcount
    conn.commit()
    if n:
        log.info(
            "pre-gen: enqueued %d octree build(s) for ops over %d points", n, threshold
        )
    return n


def enqueue_pregen_grids(conn) -> int:
    """When force_crawler_state.grid_pregen is on, pre-build the interpolated-grid octree for
    every big op that already has a raw octree but no grid yet — so Full+Gridded opens
    instantly instead of waiting on an on-demand build. Off by default (a grid build is
    heavier than a raw octree). Idempotent: only rows with grid_octree_status IS NULL."""
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT grid_pregen FROM force_crawler_state "
                "WHERE id='00000000-0000-0000-0000-000000000001'"
            )
            row = cur.fetchone()
        if not (row and row[0]):
            return 0
    except psycopg2.Error:
        conn.rollback()
        return 0
    threshold = _octree_threshold(conn)
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE machining_force_analysis
               SET grid_octree_status='pending', grid_octree_requested_at=now(), updated_at=now()
             WHERE status='done'
               AND grid_octree_status IS NULL
               AND octree_status='done'
               AND cut_start_idx IS NOT NULL AND cut_end_idx IS NOT NULL
               AND (cut_end_idx - cut_start_idx) > %s
        """,
            [threshold],
        )
        n = cur.rowcount
    conn.commit()
    if n:
        log.info(
            "pre-gen: enqueued %d grid-octree build(s) for ops over %d points",
            n,
            threshold,
        )
    return n


def claim_batch(conn, args, limit: int):
    """Atomically move up to `limit` pending rows to 'processing'; return them."""
    scope, sparams = _scope_exists(args, "a")
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            f"""
            WITH picked AS (
                SELECT a.id
                FROM machining_force_analysis a
                WHERE a.status = 'pending' {scope}
                ORDER BY a.created_at
                LIMIT {int(limit)}
                FOR UPDATE SKIP LOCKED
            )
            UPDATE machining_force_analysis a
               SET status='processing', updated_at=now()
              FROM picked
             WHERE a.id = picked.id
         RETURNING a.id, a.operation_id, a.directus_files_id,
                   a.frm_fx AS old_fx, a.frm_fy AS old_fy, a.frm_fz AS old_fz,
                   a.live_cache_file AS old_cache, a.live_render_points, a.pulses_per_rev, a.inner_diameter, a.outer_diameter, a.filter_chain::text AS filter_chain,
                   (SELECT metadata->>'archive_path' FROM directus_files WHERE id = a.directus_files_id) AS archive_path,
                   (SELECT metadata->>'fingerprint'  FROM directus_files WHERE id = a.directus_files_id) AS fingerprint
        """,
            sparams,
        )
        rows = cur.fetchall()
    conn.commit()
    return rows


# ------------------------------------------------------------------------ process
# Sampling settings default (mirrors process_force.m's own defaults); overridden
# per-run by force_crawler_state, so admins control these without touching code.
DEFAULT_SAMPLING = {
    "series_points": 3000,
    "fft_points": 3000,
    "frm_downsample_step": 5,
    "frm_dpi": 300,
    "live_cache_points": 250000,
    "pulses_per_rev": 1,
}


def load_sampling_opts(conn) -> dict:
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                "SELECT series_points, fft_points, frm_downsample_step, frm_dpi, live_cache_points, "
                "pulses_per_rev FROM force_crawler_state WHERE id='00000000-0000-0000-0000-000000000001'"
            )
            row = cur.fetchone()
        if row:
            return {k: int(v) for k, v in row.items()}
    except psycopg2.Error:
        conn.rollback()
    return dict(DEFAULT_SAMPLING)


def matlab_opts_literal(opts: dict) -> str:
    """A MATLAB struct() literal for process_force's 3rd (opts) argument."""
    parts = []
    for k, v in opts.items():
        if isinstance(v, str):
            parts.append(f"'{k}','{mlq(v)}'")
        elif isinstance(v, float):
            parts.append(f"'{k}',{v}")
        else:
            parts.append(f"'{k}',{int(v)}")
    return "struct(" + ",".join(parts) + ")"


def run_matlab(
    exe: str, unc: str, outdir: str, timeout: int, matlab_opts: dict
) -> tuple[bool, str]:
    stmt = (
        f"addpath('{mlq(str(MATLAB_SRC))}'); "
        f"process_force('{mlq(unc)}','{mlq(outdir)}',{matlab_opts_literal(matlab_opts)})"
    )
    try:
        p = subprocess.run(
            [exe, "-batch", stmt], capture_output=True, text=True, timeout=timeout
        )
    except subprocess.TimeoutExpired:
        return False, f"matlab timeout after {timeout}s"
    if p.returncode != 0:
        tail = (p.stderr or p.stdout or "").strip().splitlines()[-5:]
        return False, f"matlab exit {p.returncode}: {' | '.join(tail)}"
    return True, ""


def process_file(row, exe: str, timeout: int, matlab_opts: dict) -> dict:
    """Run MATLAB for one file. Returns a result dict (no DB / network here).
    A row's live_render_points (a Tier-2 "Process at N points" request from the
    dashboard) overrides live_cache_points just for that file — so the browser can
    ask for a denser (down to 1:1) point cloud without changing the global setting."""
    workroot = os.environ.get("FORCE_WORKDIR")
    outdir = tempfile.mkdtemp(prefix="force_", dir=workroot)
    res = {
        "id": row["id"],
        "outdir": outdir,
        "status": "error",
        "message": "",
        "summary": {},
    }
    try:
        req = row.get("live_render_points")
        if req and int(req) > 0:
            matlab_opts = {**matlab_opts, "live_cache_points": int(req)}
        ppr = row.get("pulses_per_rev")
        if ppr and int(ppr) > 0:
            matlab_opts = {**matlab_opts, "pulses_per_rev": int(ppr)}
        inner = row.get("inner_diameter")
        if inner and float(inner) > 0:
            matlab_opts = {**matlab_opts, "inner_diam": float(inner)}
        outer = row.get("outer_diameter")
        if outer and float(outer) > 0:
            matlab_opts = {**matlab_opts, "outer_diam": float(outer)}
        fchain = row.get("filter_chain")
        if fchain:
            matlab_opts = {**matlab_opts, "filter_chain": str(fchain)}
        unc = unc_for(row["archive_path"])
        ok, err = run_matlab(exe, unc, outdir, timeout, matlab_opts)
        if not ok:
            res["message"] = err
            return res
        summ_path = Path(outdir) / "summary.json"
        if not summ_path.exists():
            res["message"] = "no summary.json produced"
            return res
        summary = json.loads(summ_path.read_text(encoding="utf-8"))
        res["summary"] = summary
        if summary.get("status") != "done":
            res["message"] = summary.get(
                "message", "processing reported non-done status"
            )
            return res
        res["status"] = "done"
    except Exception as e:  # noqa: BLE001 - want the message recorded
        res["message"] = f"{type(e).__name__}: {e}"
    return res


# ------------------------------------------------------- viewport render (Phase 1c)
def _ml_literal(v) -> str:
    """MATLAB literal for a Python scalar/str/nested-dict (for the render opts struct)."""
    if isinstance(v, bool):
        return "1" if v else "0"
    if isinstance(v, int):
        return str(v)
    if isinstance(v, float):
        return repr(v)
    if isinstance(v, str):
        return "'" + mlq(v) + "'"
    if isinstance(v, dict):
        return (
            "struct("
            + ",".join(f"'{k}',{_ml_literal(val)}" for k, val in v.items())
            + ")"
        )
    raise ValueError(f"unsupported opt type: {type(v)}")


def claim_render(conn, limit: int = 4):
    """Atomically move up to `limit` pending viewport-render requests to 'processing'."""
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            """
            WITH picked AS (
                SELECT id FROM machining_force_analysis
                 WHERE render_status='pending'
                 ORDER BY render_requested_at NULLS FIRST
                 LIMIT %s FOR UPDATE SKIP LOCKED
            )
            UPDATE machining_force_analysis a SET render_status='processing', updated_at=now()
              FROM picked WHERE a.id = picked.id
         RETURNING a.id, a.pulses_per_rev, a.inner_diameter, a.outer_diameter, a.filter_chain::text AS filter_chain, a.render_bounds, a.render_axis, a.render_colormap,
                   a.render_cmin, a.render_cmax, a.render_file AS old_render,
                   (SELECT metadata->>'archive_path' FROM directus_files WHERE id = a.directus_files_id) AS archive_path
        """,
            [limit],
        )
        rows = cur.fetchall()
    conn.commit()
    return rows


def process_render_row(
    conn, directus, row, exe: str, timeout: int, matlab_opts: dict
) -> str:
    """Render one viewport request via MATLAB, upload the PNG, and record render_file.
    process_force('mat','outdir', struct(... ,'viewport',struct('axis',...,'out',...)))
    re-renders ONLY the requested bounds at full resolution, then returns early."""
    outdir = tempfile.mkdtemp(prefix="frmvp_", dir=os.environ.get("FORCE_WORKDIR"))
    try:
        b = row.get("render_bounds") or {}
        if not row.get("archive_path"):
            raise ValueError("no archive .mat linked to this analysis row")
        for k in ("xmin", "xmax", "ymin", "ymax"):
            if b.get(k) is None:
                raise ValueError(f"render_bounds.{k} missing")
        out_png = str(Path(outdir) / "viewport.png")
        vp = {
            "axis": row.get("render_axis") or "Fz",
            "xmin": float(b["xmin"]),
            "xmax": float(b["xmax"]),
            "ymin": float(b["ymin"]),
            "ymax": float(b["ymax"]),
            "colormap": row.get("render_colormap") or "viridis",
            "out": out_png,
        }
        if row.get("render_cmin") is not None and row.get("render_cmax") is not None:
            vp["cmin"] = float(row["render_cmin"])
            vp["cmax"] = float(row["render_cmax"])
        opts = {k: int(v) for k, v in matlab_opts.items()}
        ppr = row.get("pulses_per_rev")
        if ppr and int(ppr) > 0:
            opts["pulses_per_rev"] = int(ppr)
        inner = row.get("inner_diameter")
        if inner and float(inner) > 0:
            opts["inner_diam"] = float(inner)
        outer = row.get("outer_diameter")
        if outer and float(outer) > 0:
            opts["outer_diam"] = float(outer)
        fchain = row.get("filter_chain")
        if fchain:
            opts["filter_chain"] = str(fchain)
        opts["viewport"] = vp
        stmt = (
            f"addpath('{mlq(str(MATLAB_SRC))}'); "
            f"process_force('{mlq(unc_for(row['archive_path']))}','{mlq(outdir)}',{_ml_literal(opts)})"
        )
        p = subprocess.run(
            [exe, "-batch", stmt], capture_output=True, text=True, timeout=timeout
        )
        if p.returncode != 0 or not Path(out_png).exists():
            tail = (p.stderr or p.stdout or "").strip().splitlines()[-5:]
            raise RuntimeError("matlab render failed: " + " | ".join(tail))
        stem = Path(row["archive_path"]).stem
        fid = directus.upload_frm(out_png, f"FRM viewport — {stem}")
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE machining_force_analysis SET render_status='done', render_file=%s, "
                "render_error=NULL, updated_at=now() WHERE id=%s",
                [fid, row["id"]],
            )
        conn.commit()
        if row.get("old_render") and row["old_render"] != fid:
            directus.delete_file(row["old_render"])
        log.info("[RENDER] %s viewport -> %s", stem, fid)
        return "done"
    except Exception as e:  # noqa: BLE001
        conn.rollback()
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE machining_force_analysis SET render_status='error', render_error=%s, "
                "updated_at=now() WHERE id=%s",
                [str(e)[:2000], row["id"]],
            )
        conn.commit()
        log.error("[RENDER-ERR] %s", e)
        return "error"
    finally:
        shutil.rmtree(outdir, ignore_errors=True)


def handle_renders(conn, exe: str, directus) -> int:
    """Process all pending viewport-render requests once. Interactive (a user is waiting
    on the download), so this runs regardless of the bulk-crawl pause state."""
    rows = claim_render(conn)
    if not rows:
        return 0
    matlab_opts = load_sampling_opts(conn)
    for r in rows:
        process_render_row(conn, directus, r, exe, 900, matlab_opts)
    return len(rows)


# ------------------------------------------------------- Potree octree build (Phase 2)
def claim_octree(conn, limit: int = 2):
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            """
            WITH picked AS (
                SELECT id FROM machining_force_analysis
                 WHERE octree_status='pending'
                 ORDER BY octree_requested_at NULLS FIRST
                 LIMIT %s FOR UPDATE SKIP LOCKED
            )
            UPDATE machining_force_analysis a SET octree_status='processing', updated_at=now()
              FROM picked WHERE a.id = picked.id
         RETURNING a.id, a.operation_id, a.pulses_per_rev, a.inner_diameter, a.outer_diameter, a.filter_chain::text AS filter_chain,
                   (SELECT metadata->>'archive_path' FROM directus_files WHERE id = a.directus_files_id) AS archive_path
        """,
            [limit],
        )
        rows = cur.fetchall()
    conn.commit()
    return rows


def _read_octree_bin(path: str):
    import numpy as np

    with open(path, "rb") as f:
        magic, n = struct.unpack("<II", f.read(8))
        if magic != 0x44314F43:
            raise RuntimeError(f"bad octree bin magic {magic:#x}")
        a = np.frombuffer(f.read(n * 5 * 4), dtype="<f4")
    return n, a[0:n], a[n : 2 * n], a[2 * n : 3 * n], a[3 * n : 4 * n], a[4 * n : 5 * n]


def _read_grid_bin(path: str):
    """Read a D1GR interpolated-grid binary: magic, N, fidelity, arm_ratio, cell_mm header
    then float32 x,y,Fx,Fy,Fz [N]. NaN fidelity/arm_ratio -> None (stored NULL)."""
    import numpy as np

    with open(path, "rb") as f:
        magic, n = struct.unpack("<II", f.read(8))
        if magic != 0x44314752:
            raise RuntimeError(f"bad grid bin magic {magic:#x}")
        fidelity, arm_ratio, cell_mm = struct.unpack("<fff", f.read(12))
        a = np.frombuffer(f.read(n * 5 * 4), dtype="<f4")
    fid = None if fidelity != fidelity else float(fidelity)  # NaN check
    ratio = None if arm_ratio != arm_ratio else float(arm_ratio)
    return (
        n,
        fid,
        ratio,
        float(cell_mm),
        a[0:n],
        a[n : 2 * n],
        a[2 * n : 3 * n],
        a[3 * n : 4 * n],
        a[4 * n : 5 * n],
    )


def _patch_octree_climits(meta_path: Path, fx, fy, fz) -> None:
    """Rewrite the Fx/Fy/Fz attribute min/max in a PotreeConverter metadata.json to the
    prctile [1,99] of each series, so the octree viewer's colour scale matches the FRM PNGs
    and the live cloud (which both clip at 1/99). Best-effort: leaves the file untouched on
    any error."""
    import numpy as np

    try:
        meta = json.loads(meta_path.read_text())
        pct = {"Fx": fx, "Fy": fy, "Fz": fz}
        for a in meta.get("attributes", []):
            arr = pct.get(a.get("name"))
            if arr is None or len(arr) == 0:
                continue
            lo, hi = (float(v) for v in np.percentile(arr, [1, 99]))
            if hi <= lo:
                hi = lo + 1.0
            a["min"] = [lo]
            a["max"] = [hi]
        meta_path.write_text(json.dumps(meta))
    except Exception as e:  # noqa: BLE001
        log.warning("[OCTREE] climits patch skipped: %s", e)


def process_octree_row(
    conn, row, exe: str, timeout: int, matlab_opts: dict, potree_exe: str
) -> str:
    """MATLAB emits the full-res cloud -> laspy writes a LAS (force axes as attributes) ->
    PotreeConverter builds the octree -> publish under OCTREE_DIR/<op_id>/ for Caddy."""
    import laspy
    import numpy as np

    outdir = tempfile.mkdtemp(prefix="octree_", dir=os.environ.get("FORCE_WORKDIR"))
    try:
        if not row.get("archive_path"):
            raise ValueError("no archive .mat linked to this analysis row")
        binp = str(Path(outdir) / "cloud.bin")
        opts = {k: int(v) for k, v in matlab_opts.items()}
        ppr = row.get("pulses_per_rev")
        if ppr and int(ppr) > 0:
            opts["pulses_per_rev"] = int(ppr)
        inner = row.get("inner_diameter")
        if inner and float(inner) > 0:
            opts["inner_diam"] = float(inner)
        outer = row.get("outer_diameter")
        if outer and float(outer) > 0:
            opts["outer_diam"] = float(outer)
        fchain = row.get("filter_chain")
        if fchain:
            opts["filter_chain"] = str(fchain)
        opts["octree_out"] = binp
        stmt = (
            f"addpath('{mlq(str(MATLAB_SRC))}'); "
            f"process_force('{mlq(unc_for(row['archive_path']))}','{mlq(outdir)}',{_ml_literal(opts)})"
        )
        p = subprocess.run(
            [exe, "-batch", stmt], capture_output=True, text=True, timeout=timeout
        )
        if p.returncode != 0 or not Path(binp).exists():
            tail = (p.stderr or p.stdout or "").strip().splitlines()[-5:]
            raise RuntimeError("matlab octree emit failed: " + " | ".join(tail))
        n, x, y, fx, fy, fz = _read_octree_bin(binp)
        if n == 0:
            raise RuntimeError("empty cloud")

        las_path = str(Path(outdir) / "cloud.las")
        h = laspy.LasHeader(point_format=3)
        h.offsets = [float(x.min()), float(y.min()), 0.0]
        h.scales = [0.001, 0.001, 0.001]
        for nm in ("Fx", "Fy", "Fz"):
            h.add_extra_dim(laspy.ExtraBytesParams(name=nm, type=np.float32))
        las = laspy.LasData(h)
        las.x = x.astype(np.float64)
        las.y = y.astype(np.float64)
        las.z = np.zeros(n)
        las.Fx = fx
        las.Fy = fy
        las.Fz = fz
        lo, hi = float(fz.min()), float(fz.max())
        las.intensity = np.clip(
            (fz - lo) / ((hi - lo) or 1.0) * 65535, 0, 65535
        ).astype(np.uint16)
        las.write(las_path)

        octmp = str(Path(outdir) / "octree")
        pc = subprocess.run(
            [potree_exe, las_path, "-o", octmp],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        if pc.returncode != 0 or not (Path(octmp) / "metadata.json").exists():
            tail = (pc.stderr or pc.stdout or "").strip().splitlines()[-5:]
            raise RuntimeError("PotreeConverter failed: " + " | ".join(tail))

        # PotreeConverter records each attribute's TRUE min/max. The FRM PNGs (and the live
        # cloud) colour by prctile [1,99] to clip force spikes; the octree viewer reads its
        # colour range straight from these attribute min/max, so without this it would look
        # washed-out and different from every other view. Overwrite Fx/Fy/Fz min/max with the
        # same 1/99 percentiles so all three renderers share one colour scale.
        _patch_octree_climits(Path(octmp) / "metadata.json", fx, fy, fz)

        op = str(row["operation_id"])
        dst = OCTREE_DIR / op
        if dst.exists():
            shutil.rmtree(dst, ignore_errors=True)
        dst.mkdir(parents=True, exist_ok=True)
        for fn in ("metadata.json", "hierarchy.bin", "octree.bin"):
            shutil.copy2(Path(octmp) / fn, dst / fn)

        with conn.cursor() as cur:
            cur.execute(
                "UPDATE machining_force_analysis SET octree_status='done', octree_path=%s, "
                "octree_points=%s, octree_error=NULL, updated_at=now() WHERE id=%s",
                [op, int(n), row["id"]],
            )
        conn.commit()
        log.info("[OCTREE] %s -> %s (%d pts)", Path(row["archive_path"]).stem, op, n)
        return "done"
    except Exception as e:  # noqa: BLE001
        conn.rollback()
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE machining_force_analysis SET octree_status='error', octree_error=%s, "
                "updated_at=now() WHERE id=%s",
                [str(e)[:2000], row["id"]],
            )
        conn.commit()
        log.error("[OCTREE-ERR] %s", e)
        return "error"
    finally:
        shutil.rmtree(outdir, ignore_errors=True)


def handle_octrees(conn, exe: str) -> int:
    """Build Potree octrees for any pending requests. Needs PotreeConverter + laspy; if
    either is missing, requests are left pending (logged once)."""
    potree_exe = detect_potree_converter()
    if not potree_exe:
        return 0
    try:
        import laspy  # noqa: F401
    except ImportError:
        log.warning(
            "laspy not installed (pip install laspy) — octree requests left pending"
        )
        return 0
    rows = claim_octree(conn)
    if not rows:
        return 0
    matlab_opts = load_sampling_opts(conn)
    for r in rows:
        process_octree_row(conn, r, exe, 3600, matlab_opts, potree_exe)
    return len(rows)


# ------------------------------------------------- interpolated-grid octree build
def load_grid_opts(conn) -> dict:
    """Grid interpolation settings from force_crawler_state (density capped at 8192)."""
    opts = {"n": 2048, "method": "splat", "cv_arm_step": 10}
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                "SELECT grid_density, grid_method FROM force_crawler_state "
                "WHERE id='00000000-0000-0000-0000-000000000001'"
            )
            row = cur.fetchone()
        if row:
            opts["n"] = min(8192, max(16, int(row["grid_density"] or 2048)))
            m = (row["grid_method"] or "splat").lower()
            opts["method"] = m if m in ("splat", "natural") else "splat"
    except psycopg2.Error:
        conn.rollback()
    return opts


def claim_grid(conn, limit: int = 2):
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            """
            WITH picked AS (
                SELECT id FROM machining_force_analysis
                 WHERE grid_octree_status='pending'
                 ORDER BY grid_octree_requested_at NULLS FIRST
                 LIMIT %s FOR UPDATE SKIP LOCKED
            )
            UPDATE machining_force_analysis a SET grid_octree_status='processing', updated_at=now()
              FROM picked WHERE a.id = picked.id
         RETURNING a.id, a.operation_id, a.pulses_per_rev, a.inner_diameter, a.outer_diameter, a.filter_chain::text AS filter_chain,
                   (SELECT metadata->>'archive_path' FROM directus_files WHERE id = a.directus_files_id) AS archive_path
        """,
            [limit],
        )
        rows = cur.fetchall()
    conn.commit()
    return rows


def process_grid_row(
    conn,
    row,
    exe: str,
    timeout: int,
    matlab_opts: dict,
    grid_opts: dict,
    potree_exe: str,
) -> str:
    """MATLAB interpolates the spiral onto a grid + emits D1GR -> laspy LAS (force axes as
    int16-scaled attrs; force is 12-bit at source so this is lossless) -> PotreeConverter ->
    publish under OCTREE_DIR/grid/<op_id>/ for Caddy. Records grid_octree_* + grid_fidelity
    + grid_arm_ratio + grid_cell_mm."""
    import laspy
    import numpy as np

    outdir = tempfile.mkdtemp(prefix="grid_", dir=os.environ.get("FORCE_WORKDIR"))
    try:
        if not row.get("archive_path"):
            raise ValueError("no archive .mat linked to this analysis row")
        binp = str(Path(outdir) / "grid.bin")
        opts = {k: int(v) for k, v in matlab_opts.items()}
        ppr = row.get("pulses_per_rev")
        if ppr and int(ppr) > 0:
            opts["pulses_per_rev"] = int(ppr)
        inner = row.get("inner_diameter")
        if inner and float(inner) > 0:
            opts["inner_diam"] = float(inner)
        outer = row.get("outer_diameter")
        if outer and float(outer) > 0:
            opts["outer_diam"] = float(outer)
        fchain = row.get("filter_chain")
        if fchain:
            opts["filter_chain"] = str(fchain)
        opts["grid_out"] = binp
        opts["grid"] = {
            "n": int(grid_opts["n"]),
            "method": str(grid_opts["method"]),
            "cv_arm_step": int(grid_opts["cv_arm_step"]),
        }
        stmt = (
            f"addpath('{mlq(str(MATLAB_SRC))}'); "
            f"process_force('{mlq(unc_for(row['archive_path']))}','{mlq(outdir)}',{_ml_literal(opts)})"
        )
        p = subprocess.run(
            [exe, "-batch", stmt], capture_output=True, text=True, timeout=timeout
        )
        if p.returncode != 0 or not Path(binp).exists():
            tail = (p.stderr or p.stdout or "").strip().splitlines()[-5:]
            raise RuntimeError("matlab grid emit failed: " + " | ".join(tail))
        n, fidelity, arm_ratio, cell_mm, x, y, fx, fy, fz = _read_grid_bin(binp)
        if n == 0:
            raise RuntimeError("empty grid (no supported cells)")

        las_path = str(Path(outdir) / "grid.las")
        h = laspy.LasHeader(point_format=3)
        h.offsets = [float(x.min()), float(y.min()), 0.0]
        h.scales = [0.001, 0.001, 0.001]
        # Force axes as float32 extra dims (identical to the raw octree path). int16-scaled
        # dims were tried for storage savings, but PotreeConverter 2.1.1 discards the LAS
        # extra-dim scale/offset and stores raw int16 codes (min/max [-32500,32500]); the
        # colour pipeline (metadata climits + shader + colorbar) is all in Newtons, so raw
        # codes would render wrong colours. float32 keeps everything in Newtons and correct.
        for nm in ("Fx", "Fy", "Fz"):
            h.add_extra_dim(laspy.ExtraBytesParams(name=nm, type=np.float32))
        las = laspy.LasData(h)
        las.x = x.astype(np.float64)
        las.y = y.astype(np.float64)
        las.z = np.zeros(n)
        las.Fx = fx
        las.Fy = fy
        las.Fz = fz
        lo, hi = float(fz.min()), float(fz.max())
        las.intensity = np.clip(
            (fz - lo) / ((hi - lo) or 1.0) * 65535, 0, 65535
        ).astype(np.uint16)
        las.write(las_path)

        octmp = str(Path(outdir) / "octree")
        pc = subprocess.run(
            [potree_exe, las_path, "-o", octmp],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        if pc.returncode != 0 or not (Path(octmp) / "metadata.json").exists():
            tail = (pc.stderr or pc.stdout or "").strip().splitlines()[-5:]
            raise RuntimeError("PotreeConverter failed: " + " | ".join(tail))
        _patch_octree_climits(Path(octmp) / "metadata.json", fx, fy, fz)

        op = str(row["operation_id"])
        dst = OCTREE_DIR / "grid" / op
        if dst.exists():
            shutil.rmtree(dst, ignore_errors=True)
        dst.mkdir(parents=True, exist_ok=True)
        for fn in ("metadata.json", "hierarchy.bin", "octree.bin"):
            shutil.copy2(Path(octmp) / fn, dst / fn)

        with conn.cursor() as cur:
            cur.execute(
                "UPDATE machining_force_analysis SET grid_octree_status='done', "
                "grid_octree_path=%s, grid_octree_points=%s, grid_fidelity=%s, "
                "grid_arm_ratio=%s, grid_cell_mm=%s, grid_octree_error=NULL, updated_at=now() "
                "WHERE id=%s",
                [f"grid/{op}", int(n), fidelity, arm_ratio, cell_mm, row["id"]],
            )
        conn.commit()
        log.info(
            "[GRID] %s -> grid/%s (%d cells, fidelity=%s)",
            Path(row["archive_path"]).stem,
            op,
            n,
            fidelity,
        )
        return "done"
    except Exception as e:  # noqa: BLE001
        conn.rollback()
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE machining_force_analysis SET grid_octree_status='error', "
                "grid_octree_error=%s, updated_at=now() WHERE id=%s",
                [str(e)[:2000], row["id"]],
            )
        conn.commit()
        log.error("[GRID-ERR] %s", e)
        return "error"
    finally:
        shutil.rmtree(outdir, ignore_errors=True)


def handle_grids(conn, exe: str) -> int:
    """Build interpolated-grid octrees for any pending requests (needs PotreeConverter + laspy)."""
    potree_exe = detect_potree_converter()
    if not potree_exe:
        return 0
    try:
        import laspy  # noqa: F401
    except ImportError:
        log.warning("laspy not installed — grid octree requests left pending")
        return 0
    rows = claim_grid(conn)
    if not rows:
        return 0
    matlab_opts = load_sampling_opts(conn)
    grid_opts = load_grid_opts(conn)
    for r in rows:
        process_grid_row(conn, r, exe, 3600, matlab_opts, grid_opts, potree_exe)
    return len(rows)


# ----------------------------------------------------------------------- directus
# Directus File Library folders for generated artifacts.
FRM_FOLDER_NAME = os.environ.get("FRM_FOLDER_NAME", "Force Fingerprints")
CACHE_FOLDER_NAME = os.environ.get("FORCE_CACHE_FOLDER_NAME", "Force Live Cache")


class Directus:
    def __init__(self):
        self.enabled = bool(os.environ.get("DIRECTUS_ADMIN_EMAIL"))
        self._token = None
        self._folder_id = None
        self._cache_folder_id = None

    def _login(self):
        # Retry transient network/timeout failures — under heavy host load (many
        # concurrent MATLAB workers), Directus can occasionally be slow to respond;
        # this is what previously surfaced as ReadTimeoutError and (before the
        # daemon-loop resilience fix) could crash the whole daemon.
        last_err = None
        for attempt, backoff in enumerate((0, 3, 8), start=1):
            if backoff:
                time.sleep(backoff)
            try:
                r = requests.post(
                    f"{DIRECTUS_URL}/auth/login",
                    json={
                        "email": os.environ["DIRECTUS_ADMIN_EMAIL"],
                        "password": os.environ.get("DIRECTUS_ADMIN_PASSWORD", ""),
                    },
                    timeout=30,
                )
                r.raise_for_status()
                self._token = r.json()["data"]["access_token"]
                return
            except requests.RequestException as e:
                last_err = e
                log.warning("login attempt %d/3 failed: %s", attempt, e)
        raise last_err

    def _hdr(self):
        if self._token is None:
            self._login()
        return {"Authorization": f"Bearer {self._token}"}

    def _folder(self) -> str | None:
        """Get (or create) the FRM folder in directus_folders; cache its id."""
        if self._folder_id:
            return self._folder_id
        q = requests.get(
            f"{DIRECTUS_URL}/folders",
            headers=self._hdr(),
            params={"filter[name][_eq]": FRM_FOLDER_NAME, "limit": 1},
            timeout=30,
        )
        q.raise_for_status()
        found = q.json().get("data") or []
        if found:
            self._folder_id = found[0]["id"]
        else:
            c = requests.post(
                f"{DIRECTUS_URL}/folders",
                headers=self._hdr(),
                json={"name": FRM_FOLDER_NAME},
                timeout=30,
            )
            c.raise_for_status()
            self._folder_id = c.json()["data"]["id"]
        return self._folder_id

    def _cache_folder(self) -> str | None:
        """Get (or create) the live-cache folder in directus_folders; cache its id."""
        if self._cache_folder_id:
            return self._cache_folder_id
        q = requests.get(
            f"{DIRECTUS_URL}/folders",
            headers=self._hdr(),
            params={"filter[name][_eq]": CACHE_FOLDER_NAME, "limit": 1},
            timeout=30,
        )
        q.raise_for_status()
        found = q.json().get("data") or []
        if found:
            self._cache_folder_id = found[0]["id"]
        else:
            c = requests.post(
                f"{DIRECTUS_URL}/folders",
                headers=self._hdr(),
                json={"name": CACHE_FOLDER_NAME},
                timeout=30,
            )
            c.raise_for_status()
            self._cache_folder_id = c.json()["data"]["id"]
        return self._cache_folder_id

    def _upload(self, path: str, title: str, folder: str, mime: str) -> str | None:
        """Shared upload body: retries once on token expiry (401) AND retries transient
        network/timeout failures with backoff (see _login for why — a busy host running
        many concurrent MATLAB workers can make Directus occasionally slow to respond)."""
        last_err = None
        for net_attempt, backoff in enumerate((0, 4, 10), start=1):
            if backoff:
                time.sleep(backoff)
            try:
                for attempt in (1, 2):  # retry once on token expiry
                    with open(path, "rb") as fh:
                        r = requests.post(
                            f"{DIRECTUS_URL}/files",
                            headers=self._hdr(),
                            data={"title": title, "folder": folder},
                            files={"file": (Path(path).name, fh, mime)},
                            timeout=120,
                        )
                    if r.status_code == 401 and attempt == 1:
                        self._token = None
                        continue
                    r.raise_for_status()
                    return r.json()["data"]["id"]
            except requests.RequestException as e:
                last_err = e
                log.warning(
                    "upload attempt %d/3 for %s failed: %s",
                    net_attempt,
                    Path(path).name,
                    e,
                )
        raise last_err

    def upload_frm(self, png_path: str, title: str) -> str | None:
        """Upload a PNG into the FRM folder on Directus local storage; return its id."""
        if not self.enabled:
            return None
        return self._upload(png_path, title, self._folder(), "image/png")

    def upload_cache(self, bin_path: str, title: str) -> str | None:
        """Upload the live-cache .bin (octet-stream) into the cache folder; return its id."""
        if not self.enabled:
            return None
        return self._upload(
            bin_path, title, self._cache_folder(), "application/octet-stream"
        )

    def delete_file(self, file_id):
        """Best-effort delete of a superseded FRM file (keeps the folder tidy)."""
        if not self.enabled or not file_id:
            return
        try:
            requests.delete(
                f"{DIRECTUS_URL}/files/{file_id}", headers=self._hdr(), timeout=30
            )
        except requests.RequestException:
            pass


# ------------------------------------------------------------------------- ingest
def _num(v):
    """None/NaN/'' -> None; else the value (Postgres NUMERIC/BIGINT/TIMESTAMPTZ tolerate the rest)."""
    if v is None:
        return None
    if isinstance(v, float) and v != v:  # NaN
        return None
    if (
        isinstance(v, str) and v == ""
    ):  # e.g. trigger_time absent from the .mat metadata
        return None
    return v


def ingest(conn, row, res, frm_ids, mrelease):
    s = res["summary"]
    if res["status"] == "done":
        vals = {c: _num(s.get(SUMMARY_ALIASES.get(c, c))) for c in SUMMARY_COLS}
        series = Path(res["outdir"]) / "series.json"
        fft = Path(res["outdir"]) / "fft.json"
        series_txt = series.read_text(encoding="utf-8") if series.exists() else None
        fft_txt = fft.read_text(encoding="utf-8") if fft.exists() else None
        set_cols = ", ".join(f"{c}=%s" for c in SUMMARY_COLS)
        with conn.cursor() as cur:
            cur.execute(
                f"""
                UPDATE machining_force_analysis SET
                    status='done', error_message=NULL, {set_cols},
                    series=%s::jsonb, fft=%s::jsonb,
                    frm_fx=%s, frm_fy=%s, frm_fz=%s, live_cache_file=%s,
                    live_render_points=NULL,
                    fingerprint=%s, matlab_version=%s, processed_at=now(), updated_at=now()
                WHERE id=%s
            """,
                [
                    *[vals[c] for c in SUMMARY_COLS],
                    series_txt,
                    fft_txt,
                    frm_ids.get("frm_fx"),
                    frm_ids.get("frm_fy"),
                    frm_ids.get("frm_fz"),
                    frm_ids.get("live_cache_file"),
                    row["fingerprint"],
                    mrelease,
                    row["id"],
                ],
            )
    else:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE machining_force_analysis
                   SET status='error', error_message=%s, matlab_version=%s,
                       live_render_points=NULL, processed_at=now(), updated_at=now()
                 WHERE id=%s
            """,
                [res["message"][:2000], mrelease, row["id"]],
            )
    conn.commit()


# --------------------------------------------------------------------------- main
def process_batch(conn, args, exe, mrelease, directus, batch_size, on_progress=None):
    """Claim up to `batch_size` pending rows and process them. Returns (done, errors).
    `on_progress(archive_path, status)` is called as each file finishes, so a
    caller (e.g. the daemon loop) can surface live activity."""
    rows = claim_batch(conn, args, batch_size)
    if not rows:
        return 0, 0
    log.info("claimed %d file(s)", len(rows))
    matlab_opts = load_sampling_opts(conn)
    done = errors = 0
    submit_lock = threading.Lock()
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
        futs = {}
        for r in rows:
            if args.throttle:
                with submit_lock:
                    time.sleep(args.throttle)
            futs[pool.submit(process_file, r, exe, args.timeout, matlab_opts)] = r
        for fut in concurrent.futures.as_completed(futs):
            r = futs[fut]
            res = fut.result()
            frm_ids = {}
            try:
                if res["status"] == "done":
                    stem = Path(r["archive_path"]).stem
                    for ax in ("Fx", "Fy", "Fz"):
                        png = Path(res["outdir"]) / f"frm_{ax}.png"
                        if png.exists():
                            frm_ids[f"frm_{ax.lower()}"] = directus.upload_frm(
                                str(png), f"FRM {ax} — {stem}"
                            )
                    cache = Path(res["outdir"]) / "live_cache.bin"
                    if cache.exists():
                        frm_ids["live_cache_file"] = directus.upload_cache(
                            str(cache), f"Live cache — {stem}"
                        )
                ingest(conn, r, res, frm_ids, mrelease)
                if res["status"] == "done":  # delete superseded FRM + cache files
                    new = set(frm_ids.values())
                    for old in (
                        r.get("old_fx"),
                        r.get("old_fy"),
                        r.get("old_fz"),
                        r.get("old_cache"),
                    ):
                        if old and old not in new:
                            directus.delete_file(old)
                done += 1 if res["status"] == "done" else 0
                errors += 1 if res["status"] != "done" else 0
                tag = res["status"].upper()
                log.info(
                    "[%s] %s%s",
                    tag,
                    r["archive_path"],
                    "" if res["status"] == "done" else f" — {res['message']}",
                )
                if on_progress:
                    on_progress(r["archive_path"], res["status"])
            except Exception as e:  # noqa: BLE001
                # A failure HERE (e.g. a Directus upload timeout) must not (a) abandon
                # the rest of this batch's already-completed futures, orphaning their
                # results, or (b) leave this row stuck in 'processing' forever with no
                # path back to pending/error. Mark it failed and keep going. This is
                # what silently killed the whole daemon before: an unhandled upload
                # ReadTimeout propagated out of this loop entirely.
                log.exception("post-process failed for %s: %s", r["archive_path"], e)
                try:
                    with conn.cursor() as cur:
                        cur.execute(
                            "UPDATE machining_force_analysis SET status='error', "
                            "error_message=%s, updated_at=now() WHERE id=%s",
                            [f"post-process error: {e}"[:2000], r["id"]],
                        )
                    conn.commit()
                except Exception:  # noqa: BLE001
                    try:
                        conn.rollback()
                    except Exception:  # noqa: BLE001
                        pass
                errors += 1
                if on_progress:
                    on_progress(r["archive_path"], "error")
            finally:
                shutil.rmtree(res["outdir"], ignore_errors=True)
    return done, errors


def run_queue(conn, args, exe, mrelease):
    directus = Directus()
    if not directus.enabled:
        log.warning(
            "DIRECTUS_ADMIN_EMAIL unset — FRM PNGs will not be uploaded (frm_file stays NULL)"
        )

    handle_renders(conn, exe, directus)  # process any pending viewport-download renders
    handle_octrees(conn, exe)  # build any pending Potree octrees
    handle_grids(conn, exe)  # build any pending interpolated-grid octrees

    total = 0
    while True:
        batch = (
            min(args.workers * 2, args.limit - total)
            if args.limit
            else args.workers * 2
        )
        if batch <= 0:
            break
        done, errors = process_batch(conn, args, exe, mrelease, directus, batch)
        if done + errors == 0:
            break
        total += done + errors
        if args.limit and total >= args.limit:
            break
    log.info("run: processed %d file(s)", total)
    return total


# ------------------------------------------------------------------------- daemon
class _DaemonArgs:
    """Adapts a force_crawler_state DB row to the attrs claim_batch()/process_batch() expect."""

    def __init__(self, row):
        self.workers = max(1, int(row["workers"] or 1))
        self.throttle = float(row["throttle_seconds"] or 0)
        self.timeout = 1800
        self.file_like = row["file_like"] or None
        self.op_code = row["op_code_like"] or None
        self.file_id = None
        self.reprocess = False
        self.retry_errors = False


def _load_state(conn):
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            "SELECT * FROM force_crawler_state WHERE id = '00000000-0000-0000-0000-000000000001'"
        )
        return cur.fetchone()


def run_daemon(conn, exe, mrelease, discover_every: int) -> int:
    """Long-running loop for the host: polls force_crawler_state for live settings
    (workers/throttle/scope) and desired_state (running/paused), processes a batch
    per iteration, and writes heartbeat/activity/counters back for the admin module."""
    directus = Directus()
    if not directus.enabled:
        log.warning("DIRECTUS_ADMIN_EMAIL unset — FRM PNGs will not be uploaded")
    pid = os.getpid()
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE force_crawler_state SET daemon_pid=%s, daemon_started_at=now() "
            "WHERE id='00000000-0000-0000-0000-000000000001'",
            [pid],
        )
    conn.commit()
    log.info("daemon started (pid=%d); polling force_crawler_state", pid)

    session_done = session_errors = 0
    last_discover = 0.0

    def mark(activity: str):
        """Best-effort status write — never let a failure here cascade into the caller."""
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE force_crawler_state SET current_activity=%s, last_heartbeat_at=now() "
                    "WHERE id='00000000-0000-0000-0000-000000000001'",
                    [activity[:900]],
                )
            conn.commit()
        except Exception:  # noqa: BLE001
            try:
                conn.rollback()
            except Exception:  # noqa: BLE001
                pass

    try:
        while True:
            # Every iteration's work is wrapped so ANY failure (a Directus upload
            # timeout, a transient DB hiccup, a bad file) is logged and the daemon
            # sleeps + retries — it must never die silently. A dead daemon leaves the
            # whole queue stuck with no visible error (this crashed once from an
            # unhandled requests.exceptions.ReadTimeout during upload_frm(), which
            # killed the process outright with nothing in the DB to explain why).
            try:
                state = _load_state(conn)
                if state is None:
                    log.error(
                        "force_crawler_state row missing; re-run the migration. Retrying in 30s."
                    )
                    time.sleep(30)
                    continue

                # interactive viewport-download renders — process first, and regardless
                # of the bulk-crawl pause state (a user is waiting on the PNG).
                nr = handle_renders(conn, exe, directus)
                if nr:
                    log.info("daemon: processed %d viewport render request(s)", nr)

                no = handle_octrees(conn, exe)
                if no:
                    log.info("daemon: built %d Potree octree(s)", no)

                ng = handle_grids(conn, exe)
                if ng:
                    log.info("daemon: built %d interpolated-grid octree(s)", ng)

                if state["desired_state"] != "running":
                    mark("paused")
                    time.sleep(5)
                    continue

                dargs = _DaemonArgs(state)

                if time.time() - last_discover > discover_every:
                    mark("discovering")
                    reset_stale_processing(conn)
                    n = discover(conn, dargs)
                    enqueue_pregen_octrees(conn)  # pre-build octrees for big ops
                    enqueue_pregen_grids(conn)  # + grid octrees when grid_pregen is on
                    last_discover = time.time()
                    with conn.cursor() as cur:
                        cur.execute(
                            "UPDATE force_crawler_state SET last_discover_at=now() "
                            "WHERE id='00000000-0000-0000-0000-000000000001'"
                        )
                    conn.commit()
                    if n:
                        log.info("daemon discover: %d row(s) enqueued/reset", n)

                mark("claiming batch")

                def on_progress(path, status):
                    nonlocal session_done, session_errors
                    if status == "done":
                        session_done += 1
                    else:
                        session_errors += 1
                    try:
                        with conn.cursor() as cur:
                            cur.execute(
                                """
                                UPDATE force_crawler_state
                                   SET current_activity=%s, processed_count=%s, error_count=%s,
                                       last_heartbeat_at=now(), updated_at=now()
                                 WHERE id='00000000-0000-0000-0000-000000000001'
                            """,
                                [
                                    f"{status}: {path}"[:900],
                                    session_done,
                                    session_errors,
                                ],
                            )
                        conn.commit()
                    except Exception:  # noqa: BLE001
                        try:
                            conn.rollback()
                        except Exception:  # noqa: BLE001
                            pass

                done, errors = process_batch(
                    conn,
                    dargs,
                    exe,
                    mrelease,
                    directus,
                    dargs.workers * 2,
                    on_progress=on_progress,
                )
                if done + errors == 0:
                    mark("idle (queue empty)")
                    time.sleep(10)
            except KeyboardInterrupt:
                raise
            except Exception as e:  # noqa: BLE001 — a daemon must survive its own iterations
                log.exception("daemon iteration failed (continuing): %s", e)
                try:
                    conn.rollback()
                except Exception:  # noqa: BLE001
                    pass
                mark(f"error (retrying): {e}")
                time.sleep(15)
    except KeyboardInterrupt:
        log.info("daemon stopping (Ctrl+C)")
        mark("stopped")
    return session_done


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument(
        "--discover", action="store_true", help="scan + enqueue pending rows"
    )
    ap.add_argument("--run", action="store_true", help="process pending rows")
    ap.add_argument(
        "--reprocess",
        action="store_true",
        help="on discover, reset all matching rows to pending",
    )
    ap.add_argument(
        "--retry-errors",
        action="store_true",
        help="on discover, requeue rows in 'error'",
    )
    ap.add_argument(
        "--file-like", help="scope: archive_path ILIKE pattern, e.g. '%%10-AA-MF%%'"
    )
    ap.add_argument(
        "--op-code", help="scope: manufacturing_operations.operation_code ILIKE pattern"
    )
    ap.add_argument("--file-id", help="scope: a single directus_files id")
    ap.add_argument(
        "--workers", type=int, default=1, help="parallel MATLAB processes (default 1)"
    )
    ap.add_argument(
        "--throttle", type=float, default=0.0, help="seconds to wait between launches"
    )
    ap.add_argument(
        "--limit", type=int, default=0, help="max files to process this run (0 = all)"
    )
    ap.add_argument(
        "--timeout", type=int, default=1800, help="per-file MATLAB timeout, seconds"
    )
    ap.add_argument(
        "--dry-run",
        action="store_true",
        help="discover only; report the queue, process nothing",
    )
    ap.add_argument(
        "--daemon",
        action="store_true",
        help="run forever, polling force_crawler_state for live settings/start-stop "
        "(for the d1-force-crawler admin module)",
    )
    ap.add_argument(
        "--discover-every",
        type=int,
        default=300,
        help="daemon: seconds between automatic discover passes (default 300)",
    )
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )
    if not (args.discover or args.run or args.daemon):
        args.discover = args.run = True  # default: both phases

    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        log.error("DATABASE_URL is required")
        return 2
    exe = detect_matlab()
    mrelease = matlab_release(exe)
    log.info("MATLAB: %s (%s)  archive: %s", exe, mrelease, ARCHIVE_UNC)

    conn = psycopg2.connect(dsn)
    try:
        if args.daemon:
            run_daemon(conn, exe, mrelease, args.discover_every)
            return 0
        if args.discover:
            reset_stale_processing(conn)
            discover(conn, args)
            enqueue_pregen_octrees(conn)  # pre-build octrees for big ops
            enqueue_pregen_grids(conn)  # + grid octrees when grid_pregen is on
        with conn.cursor() as cur:
            cur.execute(
                "SELECT status, count(*) FROM machining_force_analysis GROUP BY status ORDER BY status"
            )
            log.info(
                "queue: %s",
                ", ".join(f"{k}={v}" for k, v in cur.fetchall()) or "(empty)",
            )
        if args.run and not args.dry_run:
            run_queue(conn, args, exe, mrelease)
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
