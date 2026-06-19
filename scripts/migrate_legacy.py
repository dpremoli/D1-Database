#!/usr/bin/env python3
"""Phase 8 — Legacy data migration from Sample_Data.xlsx into D1 PostgreSQL.

Reads the AppSheet/Sheets export and loads every entity into the target schema
in FK-dependency order. Safe to re-run: existing rows are skipped via
ON CONFLICT DO NOTHING (materials use COALESCE to back-fill missing density).

Provenance: every imported row records 'Imported from legacy AppSheet export'
in its notes / outcome_notes field so the audit trail is clear.

Usage
-----
    pip install -r scripts/requirements.txt
    DATABASE_URL="postgres://d1:change_me@localhost:5432/d1_database" \\
        python3 scripts/migrate_legacy.py --xlsx /path/to/Sample_Data.xlsx

    # Dry-run (prints row counts only, no DB writes):
    python3 scripts/migrate_legacy.py --xlsx /path/to/Sample_Data.xlsx --dry-run
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
import uuid
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path
from typing import Any

import openpyxl
import psycopg2
import psycopg2.extras

log = logging.getLogger("migrate_legacy")

# Stable UUID namespace — every re-run of this script produces the same UUIDs
# for the same AppSheet legacy IDs, making the migration safely idempotent.
_LEGACY_NS = uuid.uuid5(uuid.NAMESPACE_DNS, "d1-database.legacy-migration.v1")

LEGACY_NOTE = "Imported from legacy AppSheet/Sheets export (Phase 8 migration)."


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def legacy_uuid(raw_id: Any) -> uuid.UUID:
    """Deterministic UUID from any AppSheet legacy ID (hex, float-str, etc.)."""
    return uuid.uuid5(_LEGACY_NS, str(raw_id).strip())


def clean_str(v: Any) -> str | None:
    s = str(v).strip() if v is not None else None
    return s if s and s.lower() not in ("none", "n/a", "na") else None


def clean_float(v: Any) -> float | None:
    if v is None:
        return None
    try:
        f = float(v)
        return None if f == 0.0 else f
    except (ValueError, TypeError):
        return None


def clean_date(v: Any) -> date | None:
    """Parse Excel datetime / date string; return None for garbage dates."""
    if v is None:
        return None
    if isinstance(v, (datetime, date)):
        d = v if isinstance(v, date) else v.date()
        # Excel zero epoch: 1899-12-30 == empty cell
        if d.year == 1899:
            return None
        return d
    s = str(v).strip()
    # "1899-12-30: 00:00:00" pattern = empty
    if s.startswith("1899"):
        return None
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y"):
        try:
            return datetime.strptime(s[:10], fmt).date()
        except ValueError:
            pass
    return None


def clean_bool(v: Any) -> bool:
    if isinstance(v, bool):
        return v
    if isinstance(v, str):
        return v.strip().lower() in ("true", "yes", "1")
    return bool(v) if v is not None else False


def sheet_rows(wb: openpyxl.Workbook, name: str) -> tuple[list[str], list[dict]]:
    """Return (headers, list_of_dicts) for a sheet, skipping blank rows."""
    ws = wb[name]
    raw = list(ws.iter_rows(values_only=True))
    headers = [str(h) for h in raw[0] if h is not None]
    rows = []
    for r in raw[1:]:
        if not any(v is not None for v in r):
            continue
        rows.append(dict(zip(headers, r[: len(headers)])))
    return headers, rows


def extract_tool_uuid(tool_field: str | None) -> str | None:
    """Extract hex legacy ID from '(072192a6) DDJNL2525X15JETI' format."""
    if not tool_field:
        return None
    m = re.match(r"\(([0-9a-fA-F]+)\)", str(tool_field).strip())
    return m.group(1) if m else None


# ---------------------------------------------------------------------------
# Loaders — one function per target table
# ---------------------------------------------------------------------------

def load_alloying_elements(cur, rows: list[dict], dry: bool) -> int:
    data = []
    for r in rows:
        sym = clean_str(r.get("Symbol"))
        name = clean_str(r.get("Name"))
        num = r.get("Atomic Number")
        if not (sym and name and num):
            continue
        data.append((sym, name, int(float(num))))
    if not dry:
        psycopg2.extras.execute_values(
            cur,
            """INSERT INTO alloying_elements (symbol, element_name, atomic_number)
               VALUES %s ON CONFLICT DO NOTHING""",
            data,
        )
    return len(data)


def load_materials(cur, rows: list[dict], dry: bool) -> int:
    data = []
    for r in rows:
        code = clean_str(r.get("Code"))
        name = clean_str(r.get("Alloy"))
        if not (code and name):
            continue
        density = clean_float(r.get("Density"))
        export_ctrl = clean_bool(r.get("Export Controlled?"))
        datasheet = clean_str(r.get("Link"))
        overview = clean_str(r.get("Overview"))
        notes = f"{LEGACY_NOTE} Overview: {overview}" if overview else LEGACY_NOTE
        data.append((
            str(legacy_uuid(code)),  # stable material_id
            code, name, density, export_ctrl, datasheet,
            notes[:2000] if notes else LEGACY_NOTE,
        ))
    if not dry:
        psycopg2.extras.execute_values(
            cur,
            """INSERT INTO materials
                 (material_id, alloy_code, common_name, density_g_per_cm3,
                  export_controlled, datasheet_url, notes)
               VALUES %s
               ON CONFLICT (alloy_code) DO UPDATE SET
                 density_g_per_cm3 = COALESCE(materials.density_g_per_cm3,
                                               EXCLUDED.density_g_per_cm3),
                 datasheet_url = COALESCE(materials.datasheet_url,
                                          EXCLUDED.datasheet_url)""",
            data,
        )
    return len(data)


def load_equipment(cur, rows: list[dict], dry: bool) -> int:
    data = []
    for r in rows:
        name = clean_str(r.get("Machine"))
        if not name:
            continue
        # Sanitise machine name for use as code (replace special chars)
        code = re.sub(r"[^A-Za-z0-9_\-]", "-", name).strip("-")
        eq_type = clean_str(r.get("Type")) or "Unknown"
        data.append((
            str(legacy_uuid(name)),
            code, name, eq_type, LEGACY_NOTE,
        ))
    if not dry:
        psycopg2.extras.execute_values(
            cur,
            """INSERT INTO equipment
                 (equipment_id, equipment_code, equipment_name, equipment_type, notes)
               VALUES %s ON CONFLICT (equipment_code) DO NOTHING""",
            data,
        )
    return len(data)


def load_tools(cur, rows: list[dict], dry: bool) -> int:
    data = []
    for r in rows:
        uid = clean_str(r.get("Unique ID"))
        name = clean_str(r.get("Name"))
        if not (uid and name):
            continue
        tool_type = clean_str(r.get("Operation")) or clean_str(r.get("Op Type"))
        mfr = clean_str(r.get("Manufacturer"))
        notes = f"{LEGACY_NOTE} Manufacturer: {mfr}" if mfr else LEGACY_NOTE
        data.append((
            str(legacy_uuid(uid)),
            uid, name, tool_type, notes,
        ))
    if not dry:
        psycopg2.extras.execute_values(
            cur,
            """INSERT INTO tools (tool_id, tool_code, tool_name, tool_type, notes)
               VALUES %s ON CONFLICT (tool_code) DO NOTHING""",
            data,
        )
    return len(data)


def load_insert_types(cur, rows: list[dict], dry: bool) -> int:
    data = []
    for r in rows:
        name = clean_str(r.get("Name"))
        if not name:
            continue
        mfr = clean_str(r.get("Manufacturer"))
        data.append((
            str(legacy_uuid(name)),
            name, mfr,
        ))
    if not dry:
        psycopg2.extras.execute_values(
            cur,
            """INSERT INTO insert_types (insert_type_id, type_code, manufacturer)
               VALUES %s ON CONFLICT (type_code) DO NOTHING""",
            data,
        )
    return len(data)


def load_manufacturing_methods(cur, op_rows: list[dict], code_rows: list[dict],
                                dry: bool) -> int:
    # Seed already covers FAST/MF, Forged/MO etc.  Add any missing from sheets.
    method_map = {
        "Turning": ("MC", "CNC Turning"),
        "Milling": ("MM", "CNC Milling"),
        "FAST": ("MF", "FAST/SPS Sintering"),
        "Forged": ("MO", "Forging"),
        "Rolled": ("MR", "Rolling"),
        "Cast": ("MCA", "Casting"),
        "Additive": ("MAM", "Additive Manufacturing"),
        "HIP": ("MHIP", "Hot Isostatic Pressing"),
        "EDM": ("MEDM", "Electrical Discharge Machining"),
        "Machined": ("MC2", "Machining (General)"),
        "Unknown": ("MUK", "Unknown Manufacturing Route"),
        "Other": ("MOTH", "Other Manufacturing Route"),
    }
    # Augment from Manufacturing Codes sheet
    for r in code_rows:
        meth = clean_str(r.get("Method"))
        code = clean_str(r.get("Code"))
        if meth and code and meth not in method_map:
            method_map[meth] = (code, meth)

    data = []
    for method_name, (code, display) in method_map.items():
        data.append((
            str(legacy_uuid(f"method:{code}")),
            code, display, LEGACY_NOTE,
        ))
    if not dry:
        psycopg2.extras.execute_values(
            cur,
            """INSERT INTO manufacturing_methods
                 (method_id, method_code, method_name, description)
               VALUES %s ON CONFLICT (method_code) DO NOTHING""",
            data,
        )
    return len(data)


def load_method_parameters(cur, dry: bool) -> int:
    """Insert the known FAST and Turning/Milling parameter templates."""
    # Look up method IDs by code
    if dry:
        return 0
    cur.execute("SELECT method_id, method_code FROM manufacturing_methods")
    method_ids = {row[1]: row[0] for row in cur.fetchall()}

    fast_params = [
        ("recipe_number", "Recipe #", "text", None, False, 1),
        ("batch_number", "Batch #", "text", None, False, 2),
        ("mass_grams", "Mass (g)", "numeric", "g", False, 3),
        ("mould_diameter_mm", "Mould Diameter", "numeric", "mm", False, 4),
        ("atmosphere", "Atmosphere", "text", None, False, 5),
        ("tc_pyro_control", "TC/Pyro Control", "text", None, False, 6),
        ("max_force_kn", "Max Force", "numeric", "kN", False, 7),
        ("max_temp_celsius", "Max Temperature", "numeric", "°C", False, 8),
        ("voltage_at_max_t_v", "Voltage at Max T", "numeric", "V", False, 9),
        ("power_at_max_t_kw", "Power at Max T", "numeric", "kW", False, 10),
        ("ptc_top_celsius", "PTC Top", "numeric", "°C", False, 11),
        ("ptc_bot_celsius", "PTC Bot", "numeric", "°C", False, 12),
        ("coshh_ref", "CoSHH Ref #", "text", None, False, 13),
        ("material_type", "Material Type", "text", None, False, 14),
    ]
    turning_params = [
        ("rpm", "RPM", "numeric", "rpm", False, 1),
        ("vc_m_per_min", "Cutting Speed", "numeric", "m/min", False, 2),
        ("feed_mm_per_rev", "Feed Rate", "numeric", "mm/rev", False, 3),
        ("ap_mm", "Depth of Cut", "numeric", "mm", False, 4),
        ("axial_mm", "Axial Depth", "numeric", "mm", False, 5),
        ("cut_length_mm", "Cut Length", "numeric", "mm", False, 6),
        ("coolant_used", "Coolant Used", "boolean", None, False, 7),
        ("coolant_pressure", "Coolant Pressure", "text", None, False, 8),
        ("new_edge", "New Edge?", "boolean", None, False, 9),
        ("op_type", "Op Type", "text", None, False, 10),
        ("chips_collected", "Chips Collected", "boolean", None, False, 11),
        ("chips_ref_code", "Chips Ref Code", "text", None, False, 12),
        ("legacy_insert_edge_id", "Legacy Insert Edge ID", "text", None, False, 13),
        ("experiment_sheet", "Experiment Sheet URL", "text", None, False, 14),
    ]

    inserted = 0
    for code, params in [("MF", fast_params), ("MC", turning_params), ("MM", turning_params)]:
        mid = method_ids.get(code)
        if not mid:
            continue
        for pname, disp, dtype, unit, req, sort in params:
            try:
                cur.execute(
                    """INSERT INTO method_parameters
                         (parameter_id, method_id, parameter_name, display_name,
                          data_type, unit_of_measure, is_required, sort_order)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                       ON CONFLICT (method_id, parameter_name) DO NOTHING""",
                    (
                        str(legacy_uuid(f"param:{code}:{pname}")),
                        mid, pname, disp, dtype, unit, req, sort,
                    ),
                )
                inserted += cur.rowcount
            except psycopg2.Error as e:
                log.warning("method_parameter skip %s.%s: %s", code, pname, e)
                cur.connection.rollback()
    return inserted


def load_tool_boxes(cur, rows: list[dict], insert_rows: list[dict],
                    itype_map: dict, dry: bool) -> tuple[int, dict]:
    """Returns (count, box_id_to_uuid_map)."""
    # Find insert types by name
    if not dry:
        cur.execute("SELECT insert_type_id, type_code FROM insert_types")
        itype_uuid = {r[1]: r[0] for r in cur.fetchall()}
    else:
        itype_uuid = {}

    # Collect all box IDs referenced by inserts (to catch orphans)
    known_box_ids = {str(r.get("Box ID")) for r in rows if r.get("Box ID")}
    ref_box_ids = {str(r.get("Insert Box")) for r in insert_rows if r.get("Insert Box")}
    orphan_ids = ref_box_ids - known_box_ids

    box_uuid_map: dict[str, str] = {}
    data = []

    for r in rows:
        bid = clean_str(r.get("Box ID"))
        if not bid:
            continue
        itype_name = clean_str(r.get("Insert Type"))
        itype_id = itype_uuid.get(itype_name) if itype_name else None
        box_code = bid  # Use raw Box ID as code (unique per row)
        box_uuid = str(legacy_uuid(f"box:{bid}"))
        box_uuid_map[bid] = box_uuid
        data.append((
            box_uuid, box_code,
            itype_name or "Unknown",  # description = insert type name
            clean_str(r.get("Location")),
            itype_id, LEGACY_NOTE,
        ))

    # Synthetic placeholder for the one orphan box
    for oid in orphan_ids:
        box_uuid = str(legacy_uuid(f"box:{oid}"))
        box_uuid_map[oid] = box_uuid
        data.append((
            box_uuid, oid, "Unknown (not in inventory)",
            None, None,
            f"{LEGACY_NOTE} WARNING: box referenced by inserts but missing from Insert Boxes Inventory.",
        ))

    if not dry:
        psycopg2.extras.execute_values(
            cur,
            """INSERT INTO tool_boxes
                 (tool_box_id, tool_box_code, description, location, insert_type_id, notes)
               VALUES %s ON CONFLICT (tool_box_code) DO NOTHING""",
            data,
        )
    return len(data), box_uuid_map


def load_cutting_inserts(cur, rows: list[dict], box_uuid_map: dict,
                          itype_map: dict, dry: bool) -> tuple[int, dict]:
    """Returns (count, insert_uid_to_uuid_map)."""
    if not dry:
        cur.execute("SELECT insert_type_id, type_code FROM insert_types")
        itype_uuid = {r[1]: r[0] for r in cur.fetchall()}
    else:
        itype_uuid = {}

    insert_uuid_map: dict[str, str] = {}
    data = []
    seen_codes: set[str] = set()

    for r in rows:
        uid = clean_str(r.get("Unique ID"))
        if not uid:
            continue
        box_hex = clean_str(r.get("Insert Box"))
        box_uuid = box_uuid_map.get(box_hex) if box_hex else None
        if not box_uuid:
            log.warning("Cutting insert %s: parent box %s not found, skipping", uid, box_hex)
            continue
        itype_name = clean_str(r.get("Insert Type"))
        itype_id = itype_uuid.get(itype_name) if itype_name else None
        pos = r.get("Position In Box")
        insert_number = int(float(pos)) if pos is not None else None
        # insert_code: box_code-#position
        insert_code = f"{box_hex}-#{insert_number}" if insert_number else f"{box_hex}-{uid[:4]}"
        if insert_code in seen_codes:
            insert_code = f"{insert_code}-{uid[:4]}"
        seen_codes.add(insert_code)
        status = clean_str(r.get("Status"))
        is_depleted = status and status.lower() in ("used", "depleted", "consumed")
        insert_uuid = str(legacy_uuid(f"insert:{uid}"))
        insert_uuid_map[uid] = insert_uuid
        data.append((
            insert_uuid, insert_code, box_uuid,
            itype_id, insert_number, is_depleted, LEGACY_NOTE,
        ))

    if not dry:
        psycopg2.extras.execute_values(
            cur,
            """INSERT INTO cutting_inserts
                 (insert_id, insert_code, tool_box_id, insert_type_id,
                  insert_number, is_depleted, notes)
               VALUES %s ON CONFLICT (insert_code) DO NOTHING""",
            data,
        )
    return len(data), insert_uuid_map


def load_insert_edges(cur, rows: list[dict], insert_uuid_map: dict,
                      box_uuid_map: dict, dry: bool) -> tuple[int, dict]:
    """Returns (count, edge_uid_to_uuid_map).

    edge_code = {box_hex}-#{insert_position}-f{letter}
    where letter = A/B/C/D based on edge Number (1→A, 2→B, ...).
    """
    edge_uuid_map: dict[str, str] = {}
    data = []
    seen_codes: set[str] = set()

    # Build a map: insert_uid → (box_hex, insert_number) for code derivation
    if not dry:
        cur.execute(
            "SELECT ci.insert_code, ci.insert_number, tb.tool_box_code "
            "FROM cutting_inserts ci JOIN tool_boxes tb ON ci.tool_box_id=tb.tool_box_id"
        )
        insert_info: dict[str, tuple] = {r[0]: (r[2], r[1]) for r in cur.fetchall()}
    else:
        insert_info = {}

    for r in rows:
        eid = clean_str(r.get("Edge ID"))
        if not eid:
            continue
        parent_uid = clean_str(r.get("Parent Insert"))
        insert_uuid = insert_uuid_map.get(parent_uid) if parent_uid else None
        if not insert_uuid:
            log.warning("Insert edge %s: parent insert %s not found, skipping", eid, parent_uid)
            continue

        number = r.get("Number")
        edge_num = int(float(number)) if number is not None else 1
        # edge letter: A=1, B=2, C=3, D=4, ...
        edge_letter = chr(ord("A") + edge_num - 1) if edge_num <= 26 else str(edge_num)
        edge_identifier = f"f{edge_letter}"

        parent_box_hex = clean_str(r.get("Parent Box"))
        # Look up box code + insert number from DB (or derive from map)
        box_code = parent_box_hex or "UNK"
        # find insert number: look at insert_uuid_map to get the insert code
        # which was: f"{box_hex}-#{insert_number}"
        insert_number = None
        for k, v in insert_uuid_map.items():
            if v == insert_uuid:
                # k is the original uid; look at data to get position
                pass
        # Simpler: just use edge_identifier as unique suffix within insert
        edge_code = f"{box_code}-{parent_uid[:4]}-{edge_identifier}"
        if edge_code in seen_codes:
            edge_code = f"{edge_code}-{eid[:4]}"
        seen_codes.add(edge_code)

        is_used = clean_bool(r.get("Status"))
        edge_uuid = str(legacy_uuid(f"edge:{eid}"))
        edge_uuid_map[eid] = edge_uuid
        data.append((
            edge_uuid, edge_code, insert_uuid,
            edge_identifier, is_used, LEGACY_NOTE,
        ))

    if not dry:
        psycopg2.extras.execute_values(
            cur,
            """INSERT INTO insert_edges
                 (edge_id, edge_code, insert_id, edge_identifier, is_used, notes)
               VALUES %s ON CONFLICT (edge_code) DO NOTHING""",
            data,
        )
    return len(data), edge_uuid_map


def load_physical_samples(cur, rows: list[dict], material_map: dict,
                           dry: bool) -> tuple[int, dict]:
    """Returns (count, legacy_uid_to_uuid_map).

    Imports all Inventory rows (both 'Sample' and 'Equipment' item types).
    Equipment items are mapped to form='Equipment' and noted accordingly.
    """
    sample_uuid_map: dict[str, str] = {}
    data = []

    for r in rows:
        uid = clean_str(r.get("Unique ID"))
        code = clean_str(r.get("Item Code"))
        if not (uid and code):
            continue
        alloy_name = clean_str(r.get("Alloy"))
        mat_id = material_map.get(alloy_name)
        geo = clean_str(r.get("Geometry")) or clean_str(r.get("Item Type")) or "Unknown"
        mfg_date = clean_date(r.get("Manufacturing Date"))
        export_ctrl = clean_bool(r.get("Export Controlled?"))
        notes_parts = [LEGACY_NOTE]
        if r.get("Nickname"):
            notes_parts.append(f"Nickname: {r['Nickname']}")
        if r.get("Notes"):
            notes_parts.append(f"Notes: {r['Notes']}")
        if r.get("Location"):
            notes_parts.append(f"Location: {r['Location']}")
        if r.get("Surface Finish"):
            notes_parts.append(f"Surface finish: {r['Surface Finish']}")
        if alloy_name and not mat_id:
            notes_parts.append(f"Legacy alloy (unresolved): {alloy_name}")
        notes = " | ".join(notes_parts)

        s_uuid = str(legacy_uuid(f"sample:{uid}"))
        sample_uuid_map[uid] = s_uuid
        data.append((
            s_uuid,
            code,
            mat_id,
            geo.lower() if geo else "unknown",
            clean_float(r.get("Weight [g]")),
            clean_float(r.get("⌀ [mm]")),
            clean_float(r.get("z [mm]")),
            clean_float(r.get("y [mm]")),
            "active",
            mfg_date,
            export_ctrl,
            notes[:4000],
        ))

    if not dry:
        psycopg2.extras.execute_values(
            cur,
            """INSERT INTO physical_samples
                 (sample_id, sample_code, material_id, form, mass_grams,
                  diameter_mm, length_mm, thickness_mm, current_status,
                  manufactured_date, export_controlled, notes)
               VALUES %s ON CONFLICT (sample_code) DO NOTHING""",
            data,
        )
    return len(data), sample_uuid_map


def load_sample_genealogy(cur, rows: list[dict], sample_uuid_map: dict,
                           dry: bool) -> tuple[int, list[str]]:
    """Insert parent→child genealogy from Inventory[Parent] field.

    Returns (inserted, [skipped_reasons]).
    """
    data = []
    skipped = []

    for r in rows:
        child_uid = clean_str(r.get("Unique ID"))
        parent_uid = clean_str(r.get("Parent"))
        if not (child_uid and parent_uid):
            continue
        child_uuid = sample_uuid_map.get(child_uid)
        parent_uuid = sample_uuid_map.get(parent_uid)
        if not child_uuid:
            skipped.append(f"child {child_uid} not in sample_uuid_map")
            continue
        if not parent_uuid:
            skipped.append(
                f"parent {parent_uid} for child {r.get('Item Code')} not found"
            )
            continue
        if child_uuid == parent_uuid:
            skipped.append(f"self-loop on {child_uid}")
            continue
        data.append((child_uuid, parent_uuid, "cut_from"))

    # Deduplicate
    data = list({(c, p, rt) for c, p, rt in data})

    if not dry:
        psycopg2.extras.execute_values(
            cur,
            """INSERT INTO sample_genealogy
                 (child_sample_id, parent_sample_id, relationship_type)
               VALUES %s ON CONFLICT DO NOTHING""",
            data,
        )
    return len(data), skipped


def load_fast_runs(
    cur,
    fast_rows: list[dict],
    inv_rows: list[dict],
    sample_uuid_map: dict,
    equipment_map: dict,
    method_map: dict,
    dry: bool,
) -> tuple[int, int]:
    """Import the subset of FAST Runs that have a linked Inventory sample.

    Returns (imported, skipped_no_sample).
    """
    # Build reverse map: fast_run_uid → list of sample uids
    fast_to_samples: dict[str, list[str]] = defaultdict(list)
    for r in inv_rows:
        sid = clean_str(r.get("Unique ID"))
        mfg_op = clean_str(r.get("Manufacturing Operation ID"))
        if sid and mfg_op:
            fast_to_samples[mfg_op].append(sid)

    fast_method_id = method_map.get("MF")
    data = []
    skipped_no_sample = 0

    for r in fast_rows:
        uid = clean_str(r.get("Unique ID"))
        if not uid:
            continue
        sample_uids = fast_to_samples.get(uid, [])
        if not sample_uids:
            skipped_no_sample += 1
            continue

        op_date = clean_date(r.get("Date")) or clean_date(r.get("Process DateTime"))
        machine_name = clean_str(r.get("Machine"))
        equipment_id = equipment_map.get(machine_name)
        operator = clean_str(r.get("User"))
        notes_text = clean_str(r.get("Notes"))

        metadata = {}
        for key, col in [
            ("recipe_number", "Recipe #"),
            ("batch_number", "Batch #"),
            ("atmosphere", "Atmosphere"),
            ("tc_pyro_control", "TC/Pyro control"),
            ("material_type", "Material Type"),
            ("coshh_ref", "CoSHH Ref #"),
        ]:
            v = clean_str(r.get(col))
            if v:
                metadata[key] = v
        for key, col in [
            ("mass_grams", "Mass (g)"),
            ("mould_diameter_mm", "Mould diameter (mm)"),
            ("max_force_kn", "Max Force (kN)"),
            ("max_temp_celsius", "Max Temp (°C)"),
            ("voltage_at_max_t_v", "Voltage at Max T (V)"),
            ("power_at_max_t_kw", "Power at Max T (kW)"),
            ("ptc_top_celsius", "PTC top (°C)"),
            ("ptc_bot_celsius", "PTC bot (°C)"),
        ]:
            v = clean_float(r.get(col))
            if v is not None:
                metadata[key] = v
        material_free_text = clean_str(r.get("Material"))
        if material_free_text:
            metadata["legacy_material_text"] = material_free_text
        metadata["legacy_fast_run_uid"] = uid

        outcome = notes_text or ""
        outcome = f"{LEGACY_NOTE} {outcome}".strip()

        for sample_uid in sample_uids:
            s_uuid = sample_uuid_map.get(sample_uid)
            if not s_uuid:
                continue
            op_uuid = str(legacy_uuid(f"fast_op:{uid}:{sample_uid}"))
            data.append((
                op_uuid,
                s_uuid,
                fast_method_id,
                equipment_id,
                operator,
                op_date,
                json.dumps(metadata),
                outcome,
            ))

    if not dry:
        psycopg2.extras.execute_values(
            cur,
            """INSERT INTO manufacturing_operations
                 (operation_id, sample_id, method_id, equipment_id,
                  operator_name, operation_date, recorded_metadata, outcome_notes)
               VALUES %s ON CONFLICT DO NOTHING""",
            data,
        )
    return len(data), skipped_no_sample


def load_machining_ops(
    cur,
    rows: list[dict],
    sample_uuid_map: dict,
    equipment_map: dict,
    tool_uuid_map: dict,
    method_map: dict,
    dry: bool,
) -> tuple[int, list[str]]:
    """Import Machining Operations. Returns (imported, [warnings])."""
    warnings_out: list[str] = []
    data = []

    for r in rows:
        uid = clean_str(r.get("Unique ID"))
        if not uid:
            continue
        workpiece_uid = clean_str(r.get("Workpiece ID"))
        s_uuid = sample_uuid_map.get(workpiece_uid) if workpiece_uid else None
        if not s_uuid:
            warnings_out.append(
                f"Machining op {uid}: workpiece {workpiece_uid} not found — skipped"
            )
            continue

        operation_type = clean_str(r.get("Operation")) or "Turning"
        method_code = "MM" if operation_type.lower() == "milling" else "MC"
        method_id = method_map.get(method_code)

        machine_name = clean_str(r.get("Machine"))
        equipment_id = equipment_map.get(machine_name)

        # Tool: "(hex_id) Name" format
        tool_raw = clean_str(r.get("Tool"))
        tool_hex = extract_tool_uuid(tool_raw) if tool_raw else None
        tool_uuid = tool_uuid_map.get(tool_hex) if tool_hex else None

        # insert_edge_id: legacy human-readable codes; store in metadata only
        legacy_edge_id = clean_str(r.get("Insert Edge ID"))

        abs_pass = r.get("Abs Pass #")
        op_seq = None
        if abs_pass is not None and str(abs_pass).strip():
            try:
                op_seq = int(float(abs_pass))
            except (ValueError, TypeError):
                pass

        freq_hz = clean_float(r.get("Capture Frequency [Hz]"))
        freq_khz = freq_hz / 1000.0 if freq_hz else None

        sw = clean_str(r.get("Software Used"))
        ver = clean_str(r.get("Version"))
        capture_sw = " ".join(filter(None, [sw, ver])) or None

        force_link = clean_str(r.get("Force File Link"))
        nc_prog = clean_str(r.get("NC Program"))
        op_date_raw = r.get("Creation Date")
        op_date = clean_date(op_date_raw)

        metadata: dict = {"legacy_machining_uid": uid}
        for key, col in [
            ("op_type", "Op Type"),
            ("coolant_pressure", "Coolant Pressure"),
            ("chips_ref_code", "Chips Ref Code"),
            ("experiment_sheet", "Experiment Sheet"),
            ("operation_code", "Operation Code"),
        ]:
            v = clean_str(r.get(col))
            if v:
                metadata[key] = v
        for key, col in [
            ("rpm", "RPM"),
            ("vc_m_per_min", "Vc [m/min]"),
            ("feed_mm_per_rev", "FR [mm/rev]"),
            ("axial_mm", "Axial [mm]"),
            ("diameter_mm", "⌀ [mm]"),
            ("ap_mm", "Ap [mm]"),
            ("cut_length_mm", "Cut Length [mm]"),
            ("max_rpm", "Max RPM"),
        ]:
            v = clean_float(r.get(col))
            if v is not None:
                metadata[key] = v
        for key, col in [
            ("force_captured", "Force Captured"),
            ("new_edge", "New Edge?"),
            ("tacho_used", "Tacho Used"),
            ("coolant_used", "Coolant Used"),
            ("chips_collected", "Chips Collected"),
        ]:
            raw = r.get(col)
            if raw is not None:
                metadata[key] = clean_bool(raw)
        if legacy_edge_id and legacy_edge_id.upper() != "N/A":
            metadata["legacy_insert_edge_id"] = legacy_edge_id

        notes = clean_str(r.get("Notes")) or ""
        outcome = f"{LEGACY_NOTE} {notes}".strip()
        pass_code = clean_str(r.get("Operation Code"))

        op_uuid = str(legacy_uuid(f"machining_op:{uid}"))
        data.append((
            op_uuid, s_uuid, method_id, equipment_id, tool_uuid,
            clean_str(r.get("User")), op_seq, pass_code, op_date,
            json.dumps(metadata),
            capture_sw, freq_khz, force_link,
            nc_prog, outcome,
        ))

    if not dry:
        psycopg2.extras.execute_values(
            cur,
            """INSERT INTO manufacturing_operations
                 (operation_id, sample_id, method_id, equipment_id, tool_id,
                  operator_name, operation_sequence, pass_code, operation_date,
                  recorded_metadata, capture_software, capture_frequency_khz,
                  file_storage_pointer, nc_program_text, outcome_notes)
               VALUES %s ON CONFLICT DO NOTHING""",
            data,
        )
    return len(data), warnings_out


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def build_lookup_maps(cur, dry: bool) -> tuple[dict, dict, dict, dict]:
    """Return (material_map, equipment_map, tool_map, method_map) from DB."""
    if dry:
        return {}, {}, {}, {}
    cur.execute("SELECT common_name, material_id FROM materials")
    material_map = {r[0]: r[1] for r in cur.fetchall()}
    # Also map by alloy_code for FAST run alloy lookups
    cur.execute("SELECT alloy_code, material_id FROM materials")
    material_map.update({r[0]: r[1] for r in cur.fetchall()})

    cur.execute("SELECT equipment_name, equipment_id FROM equipment")
    equipment_map = {r[0]: r[1] for r in cur.fetchall()}

    cur.execute("SELECT tool_code, tool_id FROM tools")
    tool_map = {r[0]: r[1] for r in cur.fetchall()}

    cur.execute("SELECT method_code, method_id FROM manufacturing_methods")
    method_map = {r[0]: r[1] for r in cur.fetchall()}

    return material_map, equipment_map, tool_map, method_map


def print_report(stats: dict, warnings: list[str]) -> None:
    print("\n" + "=" * 60)
    print("D1 Legacy Migration — Reconciliation Report")
    print("=" * 60)
    print(f"\n{'Table':<40} {'Rows processed':>15}")
    print("-" * 56)
    for table, count in stats.items():
        print(f"  {table:<38} {count:>15}")
    total = sum(stats.values())
    print("-" * 56)
    print(f"  {'TOTAL':<38} {total:>15}")
    if warnings:
        print(f"\n{'─'*60}")
        print(f"WARNINGS / SKIPPED ({len(warnings)}):")
        for w in warnings[:50]:
            print(f"  ⚠ {w}")
        if len(warnings) > 50:
            print(f"  ... and {len(warnings) - 50} more (see log)")
    print("\n✓ Migration complete.\n")


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--xlsx", required=True, help="Path to Sample_Data.xlsx")
    p.add_argument("--dry-run", action="store_true",
                   help="Print counts only; make no DB changes")
    args = p.parse_args()

    xlsx_path = Path(args.xlsx)
    if not xlsx_path.exists():
        sys.exit(f"ERROR: {xlsx_path} not found")

    db_url = os.environ.get("DATABASE_URL")
    if not db_url and not args.dry_run:
        sys.exit("ERROR: DATABASE_URL env var required (or use --dry-run)")

    log.info("Loading %s …", xlsx_path.name)
    wb = openpyxl.load_workbook(xlsx_path, read_only=True, data_only=True)

    # Load all sheets
    _, ae_rows = sheet_rows(wb, "Alloying Elements")
    _, alloy_rows = sheet_rows(wb, "Alloy Codes")
    _, machine_rows = sheet_rows(wb, "Machines")
    _, tool_rows = sheet_rows(wb, "Tools")
    _, itype_rows = sheet_rows(wb, "Insert Types")
    _, op_rows = sheet_rows(wb, "Operation")
    _, mfg_code_rows = sheet_rows(wb, "Manufacturing Codes")
    _, box_rows = sheet_rows(wb, "Insert Boxes Inventory")
    _, insert_rows = sheet_rows(wb, "Inserts")
    _, edge_rows = sheet_rows(wb, "Inserts Edges")
    _, inv_rows = sheet_rows(wb, "Inventory")
    _, fast_rows = sheet_rows(wb, "FAST Runs")
    _, mop_rows = sheet_rows(wb, "Machining Operations")

    stats: dict[str, int] = {}
    all_warnings: list[str] = []

    if args.dry_run:
        log.info("DRY RUN — no database writes")
        conn = None
        cur = None
    else:
        conn = psycopg2.connect(db_url)
        conn.autocommit = False
        cur = conn.cursor()

    try:
        log.info("Loading alloying_elements …")
        stats["alloying_elements"] = load_alloying_elements(cur, ae_rows, args.dry_run)

        log.info("Loading materials …")
        stats["materials"] = load_materials(cur, alloy_rows, args.dry_run)

        log.info("Loading equipment …")
        stats["equipment"] = load_equipment(cur, machine_rows, args.dry_run)

        log.info("Loading tools …")
        stats["tools"] = load_tools(cur, tool_rows, args.dry_run)

        log.info("Loading insert_types …")
        stats["insert_types"] = load_insert_types(cur, itype_rows, args.dry_run)

        log.info("Loading manufacturing_methods …")
        stats["manufacturing_methods"] = load_manufacturing_methods(
            cur, op_rows, mfg_code_rows, args.dry_run
        )

        log.info("Loading method_parameters …")
        stats["method_parameters"] = load_method_parameters(cur, args.dry_run)

        log.info("Loading tool_boxes …")
        n_boxes, box_uuid_map = load_tool_boxes(
            cur, box_rows, insert_rows, {}, args.dry_run
        )
        stats["tool_boxes"] = n_boxes

        log.info("Loading cutting_inserts …")
        n_inserts, insert_uuid_map = load_cutting_inserts(
            cur, insert_rows, box_uuid_map, {}, args.dry_run
        )
        stats["cutting_inserts"] = n_inserts

        log.info("Loading insert_edges …")
        n_edges, edge_uuid_map = load_insert_edges(
            cur, edge_rows, insert_uuid_map, box_uuid_map, args.dry_run
        )
        stats["insert_edges"] = n_edges

        # Refresh lookup maps from DB (now populated)
        material_map, equipment_map, tool_map, method_map = build_lookup_maps(
            cur, args.dry_run
        )

        log.info("Loading physical_samples …")
        n_samples, sample_uuid_map = load_physical_samples(
            cur, inv_rows, material_map, args.dry_run
        )
        stats["physical_samples"] = n_samples

        log.info("Loading sample_genealogy …")
        n_gen, gen_skip = load_sample_genealogy(
            cur, inv_rows, sample_uuid_map, args.dry_run
        )
        stats["sample_genealogy"] = n_gen
        all_warnings.extend(gen_skip)

        log.info("Loading FAST Run operations …")
        n_fast, fast_skipped = load_fast_runs(
            cur, fast_rows, inv_rows, sample_uuid_map,
            equipment_map, method_map, args.dry_run,
        )
        stats["manufacturing_operations (FAST)"] = n_fast
        if fast_skipped:
            all_warnings.append(
                f"{fast_skipped} FAST Runs skipped — no linked Inventory sample "
                f"(Manufacturing Operation ID not set in Inventory sheet)"
            )

        log.info("Loading Machining Operations …")
        n_mop, mop_warn = load_machining_ops(
            cur, mop_rows, sample_uuid_map, equipment_map,
            tool_map, method_map, args.dry_run,
        )
        stats["manufacturing_operations (Machining)"] = n_mop
        all_warnings.extend(mop_warn)

        if not args.dry_run:
            conn.commit()
            log.info("Transaction committed.")

    except Exception:
        if conn:
            conn.rollback()
        log.exception("Migration failed — rolled back")
        raise
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()

    print_report(stats, all_warnings)


if __name__ == "__main__":
    main()
