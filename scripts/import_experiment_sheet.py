#!/usr/bin/env python3
"""Import an AMRC Experiment Sheet's machining passes into manufacturing_operations,
grouped under a machining-trial campaign.

Header-driven: the "Experiment Sheet" tab's columns are located by header name (the
sheets vary in column order and some add an Edge ID column), so the same importer works
across templates. Only facing/roughing passes are imported — any "Tap Testing" section
rows are skipped automatically because they carry no Facing Pass ID.

Per row: machining_* params, tool (matched), sample (matched), insert/edge (matched or
raw → legacy field). Material is derived from the alloy code embedded in the workpiece
code (e.g. 97-**AA**-MF → Ti-64; 15-**AF**-MO → Ti-17); operation_date from the trailing
date in the workpiece code. Campaign project/owner are copied onto each op (this writes
via psycopg2 and bypasses the Directus campaign-inherit hook).

Idempotent: keyed by source_run_uid = sha1(campaign_id|PassID)[:16];
INSERT … ON CONFLICT (source_run_uid) DO NOTHING.

Usage (python container on the d1net network):
    DATABASE_URL=… python scripts/import_experiment_sheet.py "<xlsx>" \
        --campaign-id <uuid> [--dry-run]
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import os
import re
import sys
import uuid

import openpyxl
import psycopg2
import psycopg2.extras

SHEET = "Experiment Sheet"
SOURCE_SYSTEM = "experiment_sheet"
METHOD_TURNING = "a7181c9c-2381-535a-9cb7-6fc3834990f1"   # MT — Turning
EQUIP_NLX2500 = "8ffb7acc-15f7-5276-81ea-9cd859e8bcf5"    # NLX-2500 | 700
_NS = uuid.uuid5(uuid.NAMESPACE_DNS, "d1-database.experiment-sheet.v1")

PASS_RE = re.compile(r"-(F\d+|R)$")           # facing F<n> or roughing R
DATE_RE = re.compile(r"(\d{4})-(\d{1,2})-(\d{1,2})")

# header label (normalised) -> internal key
HEADERS = {
    "facing pass id": "pass_id", "facing pass #": "pass_num",
    "workpiece id": "workpiece", "workpiece information": "workpiece_info",
    "program (g96 / g97)": "program", "facing force data file id": "force_file_id",
    "vc [m/min]": "vc", "max rpm": "rpm", "fz [mm/rev]": "fz",
    "axial [mm]": "axial", "diameter [mm]": "diameter",
    "tool id": "tool", "insert id": "insert", "edge id": "edge",
    "new edge": "new_edge", "tacho (y/n)": "tacho", "coolant (y/n)": "coolant",
    "coolant pressure [bar]": "coolant_bar", "chips collected (y/n)": "chips",
    "sem captured": "sem", "cut time [min]": "cut_time",
    "captured with": "captured_with", "freq. [khz]": "freq", "notes": "notes",
}


def hnorm(s):
    return re.sub(r"\s+", " ", str(s).strip().lower())


def clean_str(v):
    s = str(v).strip() if v is not None else ""
    return s if s and s.lower() not in ("none", "n/a", "na", "n/s", "#n/a", "`") else None


def clean_float(v):
    if v is None:
        return None
    try:
        f = float(v)
    except (ValueError, TypeError):
        return None
    return f if f != 0.0 else None


def yn(v):
    s = clean_str(v)
    return None if s is None else s.strip().upper().startswith("Y")


def fmt_cut_time(v):
    if isinstance(v, dt.time):
        return f"{v.hour * 60 + v.minute}:{v.second:02d} min"
    return clean_str(v)


def norm_tool(s):
    return re.sub(r"\s+", "", s).upper()


def norm_sample(code):
    m = re.match(r"^(.*?)(\d{4})-(\d{1,2})-(\d{1,2})$", code)
    if not m:
        return code
    head, y, mo, d = m.groups()
    return f"{head}{y}-{int(mo)}-{int(d)}"


def alloy_of(workpiece):
    parts = workpiece.split("-")
    return parts[1].upper() if len(parts) > 1 else None


def date_of(workpiece):
    m = DATE_RE.search(workpiece)
    if not m:
        return None
    y, mo, d = (int(x) for x in m.groups())
    try:
        return dt.date(y, mo, d)
    except ValueError:
        return None


def find_header(rows):
    for i, r in enumerate(rows):
        for c in r:
            if c is not None and hnorm(c) == "facing pass id":
                return i, {hnorm(c): j for j, c in enumerate(r) if c is not None and hnorm(c) in HEADERS}
    sys.exit("ERROR: no 'Facing Pass ID' header found in the Experiment Sheet tab")


def read_rows(path):
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    ws = wb[SHEET]
    rows = list(ws.iter_rows(values_only=True))
    hidx, hmap = find_header(rows)
    # label->key via HEADERS, then key->col index
    col = {HEADERS[lbl]: j for lbl, j in hmap.items()}

    def cell(r, key):
        j = col.get(key)
        return r[j] if (j is not None and j < len(r)) else None

    out = []
    for r in rows[hidx + 1:]:
        pass_id = clean_str(cell(r, "pass_id"))
        workpiece = clean_str(cell(r, "workpiece"))
        if not pass_id or not PASS_RE.search(pass_id):
            continue                         # skips tap-test / section / blank rows
        if not workpiece or workpiece.lower() in ("noise", "test runs"):
            continue
        out.append({
            "pass_id": pass_id, "pass_num": cell(r, "pass_num"), "workpiece": workpiece,
            "workpiece_info": clean_str(cell(r, "workpiece_info")),
            "program": clean_str(cell(r, "program")),
            "force_file_id": clean_str(cell(r, "force_file_id")),
            "vc": clean_float(cell(r, "vc")), "rpm": clean_float(cell(r, "rpm")),
            "fz": clean_float(cell(r, "fz")), "axial": clean_float(cell(r, "axial")),
            "diameter": clean_float(cell(r, "diameter")),
            "tool": clean_str(cell(r, "tool")), "insert": clean_str(cell(r, "insert")),
            "edge": clean_str(cell(r, "edge")),
            "new_edge": yn(cell(r, "new_edge")), "tacho": yn(cell(r, "tacho")),
            "coolant": yn(cell(r, "coolant")), "coolant_bar": clean_float(cell(r, "coolant_bar")),
            "chips": yn(cell(r, "chips")), "sem": clean_str(cell(r, "sem")),
            "cut_time": fmt_cut_time(cell(r, "cut_time")),
            "captured_with": clean_str(cell(r, "captured_with")), "freq": clean_float(cell(r, "freq")),
            "notes": clean_str(cell(r, "notes")),
        })
    return out


def build(row, campaign_id):
    pid = row["pass_id"]
    is_rough = pid.endswith("-R")
    op_code = row["force_file_id"] or pid
    insert_raw = " / ".join(filter(None, [row["insert"], row["edge"] and f"edge:{row['edge']}"]))
    notes = " | ".join(filter(None, [
        row["workpiece_info"] and f"Workpiece: {row['workpiece_info']}",
        row["program"] and f"Program: {row['program']}",
        row["cut_time"] and f"Cut time: {row['cut_time']}",
        row["sem"] and f"SEM captured: {row['sem']}",
        row["notes"],
    ]))
    try:
        pass_num = int(row["pass_num"]) if row["pass_num"] is not None else None
    except (ValueError, TypeError):
        pass_num = None
    return {
        "source_run_uid": hashlib.sha1(f"{campaign_id}|{pid}".encode()).hexdigest()[:16],
        "operation_id": str(uuid.uuid5(_NS, f"{campaign_id}|{pid}")),
        "subtype": "MT-R" if is_rough else "MT-F",
        "pass_code": op_code, "force_file_id": op_code,
        "operation_sequence": pass_num, "operation_date": date_of(row["workpiece"]),
        "workpiece": row["workpiece"], "alloy": alloy_of(row["workpiece"]),
        "tool": row["tool"], "insert_raw": insert_raw or None,
        "edge": row["edge"] or row["insert"], "legacy_uid": pid,
        "vc": row["vc"], "rpm": row["rpm"], "fz": row["fz"], "axial": row["axial"], "diameter": row["diameter"],
        "new_edge": row["new_edge"], "tacho": row["tacho"], "coolant": row["coolant"],
        "coolant_bar": row["coolant_bar"], "chips": row["chips"],
        "force_captured": op_code is not None and not is_rough,
        "captured_with": row["captured_with"], "freq": row["freq"], "outcome_notes": notes,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("path")
    ap.add_argument("--campaign-id", required=True)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    db = os.environ.get("DATABASE_URL") or sys.exit("ERROR: DATABASE_URL required")
    conn = psycopg2.connect(db)
    cur = conn.cursor()
    cur.execute("SELECT project_id, owner FROM campaigns WHERE campaign_id = %s", (args.campaign_id,))
    camp = cur.fetchone() or sys.exit(f"ERROR: campaign {args.campaign_id} not found")
    project_id, owner = camp

    ops = list({o["source_run_uid"]: o for o in (build(r, args.campaign_id) for r in read_rows(args.path))}.values())
    facing = sum(1 for o in ops if o["subtype"] == "MT-F")
    print(f"Parsed {len(ops)} unique passes — facing {facing}, roughing {len(ops) - facing}")

    cur.execute("SELECT tool_id, tool_code, tool_name FROM tools")
    tool_lookup = {}
    for tid, code, name in cur.fetchall():
        for key in filter(None, (code, name)):
            tool_lookup[norm_tool(key)] = tid
    cur.execute("SELECT sample_id, sample_code FROM physical_samples")
    sample_lookup = {norm_sample(c): s for s, c in cur.fetchall() if c}
    cur.execute("SELECT edge_id, edge_code FROM insert_edges")
    edge_lookup = {c.strip().upper(): e for e, c in cur.fetchall() if c}
    cur.execute("SELECT alloy_code, material_id FROM materials")
    mat_lookup = {a: m for a, m in cur.fetchall()}

    tools_m = samples_m = edges_m = mats_m = 0
    un_tools, un_samples = set(), set()
    values = []
    for o in ops:
        tool_id = tool_lookup.get(norm_tool(o["tool"])) if o["tool"] else None
        if o["tool"]:
            tools_m += 1 if tool_id else 0
            (un_tools.add(o["tool"]) if not tool_id else None)
        sample_id = sample_lookup.get(norm_sample(o["workpiece"]))
        samples_m += 1 if sample_id else 0
        (un_samples.add(o["workpiece"]) if not sample_id else None)
        edge_id = edge_lookup.get(o["edge"].strip().upper()) if o["edge"] else None
        edges_m += 1 if edge_id else 0
        material_id = mat_lookup.get(o["alloy"]) if o["alloy"] else None
        mats_m += 1 if material_id else 0
        values.append((
            o["operation_id"], METHOD_TURNING, EQUIP_NLX2500, "machining",
            o["source_run_uid"], SOURCE_SYSTEM, o["operation_date"],
            args.campaign_id, project_id, owner, material_id, sample_id, tool_id, edge_id,
            o["subtype"], o["pass_code"], o["force_file_id"], o["operation_sequence"],
            o["vc"], o["rpm"], o["fz"], o["axial"], o["diameter"],
            o["new_edge"], o["tacho"], o["coolant"], o["coolant_bar"], o["chips"],
            o["force_captured"], o["captured_with"], o["freq"],
            o["insert_raw"], o["legacy_uid"], o["outcome_notes"],
        ))

    print(f"  tools matched:   {tools_m}/{sum(1 for o in ops if o['tool'])}  (unmatched: {sorted(un_tools)})")
    print(f"  samples matched: {samples_m}/{len(ops)}  (unmatched: {sorted(un_samples)})")
    print(f"  insert edges matched: {edges_m}  | materials matched: {mats_m}")

    if args.dry_run:
        print("[dry-run] no writes.")
        cur.close(); conn.close(); return

    cols = [
        "operation_id", "method_id", "equipment_id", "process_category",
        "source_run_uid", "source_system", "operation_date",
        "campaign_id", "project_id", "owner", "material_id", "sample_id", "tool_id", "insert_edge_id",
        "machining_operation_subtype", "pass_code", "force_file_id", "operation_sequence",
        "machining_cutting_speed_m_per_min", "machining_spindle_speed_rpm",
        "machining_feed_mm_per_rev", "machining_axial_depth_of_cut_mm", "machining_workpiece_diameter_mm",
        "machining_new_edge", "machining_tacho_used", "machining_coolant_used",
        "machining_coolant_pressure_bar", "machining_chips_collected",
        "machining_force_captured", "capture_software", "capture_frequency_khz",
        "machining_legacy_insert_edge_id", "machining_legacy_machining_uid", "outcome_notes",
    ]
    psycopg2.extras.execute_values(
        cur,
        f"INSERT INTO manufacturing_operations ({', '.join(cols)}) VALUES %s "
        f"ON CONFLICT (source_run_uid) WHERE source_run_uid IS NOT NULL DO NOTHING",
        values,
    )
    inserted = cur.rowcount
    conn.commit()
    print(f"\nInserted {inserted} operations ({len(ops) - inserted} already present / skipped).")
    cur.close(); conn.close()


if __name__ == "__main__":
    main()
