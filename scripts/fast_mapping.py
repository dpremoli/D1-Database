#!/usr/bin/env python3
"""Shared mapping for the FAST/SPS log import (and future Google-sheet sync).

Pure functions + lookup tables only — no I/O. Used by import_fast_logs.py
(local xlsx backfill) and, later, sync_fast_runs.py (live Sheets poller).

Source rows (per the FCT HP D 250 monthly log tabs) carry these columns:
  Date, Time, User, Batch #, Recipe #, Material, Mass (g), Mould diameter (mm),
  Atmosphere, TC/Pyro control, Max Force (kN), Max Temp (°C), Voltage at Max T (V),
  Power at Max T (kW), PTC top (°C), PTC bot (°C), Comments, Failures, Alarms
"""
from __future__ import annotations

import hashlib
import re
import uuid
from typing import Optional

SOURCE_SYSTEM = "fast_log"
SOURCE_MACHINE = "FCT HP D 250"  # the workbook == the machine
_NS = uuid.uuid5(uuid.NAMESPACE_DNS, "d1-database.fast-log.v1")

# ── Materials ────────────────────────────────────────────────────────────────
# New reusable material types to create (alloy_code, common_name). Approved set.
NEW_MATERIALS: list[tuple[str, str]] = [
    ("W",     "Tungsten"),
    ("T9S",   "T9S+ (Ti alloy)"),
    ("GE48",  "Ti-48Al-2Cr-2Nb (GE4822 TiAl)"),
    ("RHEA",  "Refractory high-entropy alloy"),
    ("TNM",   "TNM (γ-TiAl)"),
    ("CCMW",  "Co-Cr-Mo-W"),
    ("NITI",  "Nitinol (NiTi)"),
    ("174PH", "17-4 PH stainless steel"),
    ("14YWT", "14YWT ODS steel"),
    ("4140",  "AISI 4140 steel"),
    ("MOSI2", "Molybdenum disilicide (MoSi₂)"),
    ("TI2AC", "Ti₂AlC (MAX phase)"),
    ("SPIN",  "MgAl₂O₄ spinel"),
    ("SIO2",  "Silica (SiO₂)"),
    ("HAP",   "Hydroxyapatite (CaP)"),
    ("BITE",  "Bi-Te-Se (thermoelectric)"),
    ("BISB",  "Bi-Sb-Te (thermoelectric)"),
    ("ZNS",   "Zinc sulphide (ZnS)"),
    ("ZRO2",  "Zirconia (ZrO₂)"),
]

# Whole-string (normalised) matches — used for short/ambiguous names so we don't
# false-match substrings like "co" inside "cocrmow".
_EXACT = {
    "w": "W", "co": "CO", "cr": "CR", "ni": "NI", "mg": "MG",
    "nbsi": "NS", "hfc": "HF", "niti": "NITI", "mosi2": "MOSI2",
    "rhea": "RHEA", "tnm": "TNM", "ge4822": "GE48", "t9s+": "T9S",
    "t9s+ (ti)": "T9S", "14ywt": "14YWT", "sio2": "SIO2", "zns": "ZNS",
    "zro2": "ZRO2", "ti2alc": "TI2AC", "cocrmow": "CCMW", "brass": "BR",
    "sa508": "S8", "nacl": "NC",
}

# Ordered substring matches — first hit wins, so list more specific first.
_SUBSTR: list[tuple[str, str]] = [
    ("ti-6-4", "AA"), ("ti6-4", "AA"), ("ti 64", "AA"), ("ti-64", "AA"), ("ti64", "AA"),
    ("ti-6al-4v", "AA"),
    ("ti5553", "AG"), ("ti-5553", "AG"), ("ti 5553", "AG"), ("5553", "AG"),
    ("ti6242", "AC"), ("ti-6242", "AC"),
    ("ti6246", "AB"), ("ti-6246", "AB"),
    ("cp ti", "AD"), ("ti-cp", "AD"),
    ("ti-17", "AF"), ("ti 17", "AF"),
    ("inconel 718", "IN18"), ("in718", "IN18"), ("in 718", "IN18"),
    ("in625", "IN25"), ("in 625", "IN25"),
    ("316l", "SS"),
    ("a20x", "AX"), ("rr1000", "RK"), ("scalmalloy", "SC"), ("a286", "S6"),
    ("p91", "P9"), ("tz-8y", "TZ"), ("tosoh", "TZ"),
    ("17-4ph", "174PH"), ("17-4 ph", "174PH"),
    ("ge4822", "GE48"), ("ge 48", "GE48"),
    ("hydroxyapatite", "HAP"), ("spinel", "SPIN"), ("mgal2o4", "SPIN"),
    ("bitese", "BITE"), ("bisbte", "BISB"),
    ("ti2alc", "TI2AC"), ("cocrmow", "CCMW"),
    ("4140", "4140"),
    ("nbsi", "NS"), ("hfc", "HF"), ("mosi2", "MOSI2"),
]


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", str(s).strip().lower())


def match_material(text: Optional[str]) -> Optional[str]:
    """Return an alloy_code (existing or new) for a free-text material, or None."""
    if not text:
        return None
    n = _norm(text)
    if n in _EXACT:
        return _EXACT[n]
    for tok, code in _SUBSTR:
        if tok in n:
            return code
    return None


def material_id(code: str) -> str:
    """Deterministic UUID for a material code (idempotent create)."""
    return str(uuid.uuid5(_NS, f"material:{code}"))


# ── People ───────────────────────────────────────────────────────────────────
# Technician tokens → always the operator, never an owner.
_TECH = {"nigel", "nige", "nja", "nigel martin", "nigel adams"}

# Researcher token → existing Directus user email (owner). Only app users here;
# unmatched researchers get an operator/Machine_Operator entry + raw text, no user.
RESEARCHER_USERS = {
    "nick": "n.weston@sheffield.ac.uk",
    "cameron": "cbarrie1@sheffield.ac.uk",
    "jack": "jack.batty@sheffield.ac.uk",
    "joe": "jrhopkinson1@sheffield.ac.uk", "joe h": "jrhopkinson1@sheffield.ac.uk",
    "joe hopkinson": "jrhopkinson1@sheffield.ac.uk",
    "henry": "hrboyle1@sheffield.ac.uk", "henry b": "hrboyle1@sheffield.ac.uk",
    "dennis": "dpremoli1@sheffield.ac.uk",
    "jozef": "jsmcgowan1@sheffield.ac.uk", "zef": "jsmcgowan1@sheffield.ac.uk",
    "oli": "o.levano@sheffield.ac.uk", "oliver": "o.levano@sheffield.ac.uk",
    "josh": "jtaylor25@sheffield.ac.uk", "joshua": "jtaylor25@sheffield.ac.uk",
    "sam j": "sjackson13@sheffield.ac.uk", "sam jackson": "sjackson13@sheffield.ac.uk",
    "sam james": "sjackson13@sheffield.ac.uk",
    "thomas": "t.m.childerhouse@sheffield.ac.uk", "tom": "t.m.childerhouse@sheffield.ac.uk",
    "lewis": "LDeaney1@sheffield.ac.uk",
    "carolina": "carolina.Guerra@nottingham.ac.uk",
}

# Canonical display name for the operator Machine_Operators row.
_CANON = {
    "nigel": "Nigel Martin", "nja": "Nigel Martin", "nige": "Nigel Martin",
    "nick": "Nick Weston", "cameron": "Cameron Barrie", "jack": "Jack Batty",
    "jack k": "Jack Krohn", "jack krohn": "Jack Krohn",
    "joe": "Joe Hopkinson", "joe h": "Joe Hopkinson", "joe hopkinson": "Joe Hopkinson",
    "henry": "Henry Boyle", "henry b": "Henry Boyle",
    "dennis": "Dennis Premoli", "jozef": "Jozef McGowan", "zef": "Jozef McGowan",
    "oli": "Oliver Levano Blanch", "oliver": "Oliver Levano Blanch",
    "josh": "Joshua Taylor", "joshua": "Joshua Taylor",
    "sam j": "Sam Jackson", "sam jackson": "Sam Jackson", "sam james": "Sam Jackson",
    "sam l": "Sam Lister", "thomas": "Thomas Childerhouse", "tom": "Thomas Childerhouse",
    "simon": "Simon Graham", "sg": "Simon Graham", "james": "James Pepper",
    "natasha": "Natasha", "sully": "Sully Khan", "will": "Will", "will g": "Will",
    "xingjian": "Xingjian", "matt": "Matt", "matt g": "Matt",
    "bea": "Beatrice", "billy": "Billy", "billy c": "Billy", "billy callon": "Billy",
    "idris": "Idris", "seb": "Seb", "innes": "Innes",
}


def _split_names(s: str) -> list[str]:
    s = re.sub(r"\(.*?\)", "", s)          # drop parentheticals (trainees/observers)
    parts = re.split(r"[\/+&,]|\band\b", s, flags=re.IGNORECASE)
    return [p.strip() for p in parts if p.strip()]


def parse_user(raw: Optional[str]) -> tuple[Optional[str], Optional[str], Optional[str]]:
    """Return (operator_name, owner_email_or_None, raw_string).

    operator = the technician (Nigel) if present, else the lead researcher who ran
    it alone. owner = the lead researcher's Directus email if they're an app user.
    """
    raw = (raw or "").strip() or None
    if not raw:
        return None, None, None
    toks = _split_names(raw)
    ntoks = [_norm(t) for t in toks]

    operator = None
    if any(t in _TECH for t in ntoks):
        operator = "Nigel Martin"
    elif toks:
        operator = _CANON.get(ntoks[0], toks[0].title())

    owner_email = None
    for t in ntoks:
        if t in _TECH:
            continue
        if t in RESEARCHER_USERS:
            owner_email = RESEARCHER_USERS[t]
            break
    return operator, owner_email, raw


# ── Run identity ─────────────────────────────────────────────────────────────
def run_uid(machine: str, date_str: str, time_str: str, batch: str) -> str:
    """Deterministic dedup key — a press cycle is unique by machine + timestamp."""
    key = f"{machine}|{date_str}|{time_str}|{batch}"
    return hashlib.sha1(key.encode("utf-8")).hexdigest()[:16]


# ══════════════════════════════════════════════════════════════════════════════
# FAST trace CSV normalisation (the raw per-run machine log → one internal format)
#
# Two machines export different shapes (see FAST Data/ examples):
#   FCT HP D 25  — comma-delimited, US decimals, a header row + a units row.
#   FCT HP D 250 — semicolon-delimited, EU decimals (1.015,8 == 1015.8), 3 preamble
#                  lines (Plant/Recipe/StartTime), "[unit]"-in-header names, cp1252.
# normalize_fast_csv() maps both onto ONE canonical comma/US-decimal CSV whose first
# column is elapsed time_s, mapping the physically-equivalent channels to shared keys
# (so the same series plots across machines) and passing unmapped columns through under
# a slug of their own label (nothing is lost). The d1-fast-dashboard fetches this CSV
# and plots it; the series catalog in meta drives the series picker.
# ══════════════════════════════════════════════════════════════════════════════

# Canonical channels shared across both machines: normalised raw label -> (key, label,
# unit, group). "group" buckets series by physical quantity for unit-grouped plotting.
_CANON: dict[str, tuple[str, str, str, str]] = {
    # 25-machine labels
    "av pyrometer":     ("pyro_top", "Pyrometer (top)", "C", "temp"),
    "av pyro b":        ("pyro_b", "Pyrometer B", "C", "temp"),
    "av tc1":           ("tc1", "TC1", "C", "temp"),
    "av tc2":           ("tc2", "TC2", "C", "temp"),
    "av tc3":           ("tc3", "TC3", "C", "temp"),
    "av tc4":           ("tc4", "TC4", "C", "temp"),
    "av ptc top":       ("ptc_top", "PTC top", "C", "temp"),
    "av ptc bot.":      ("ptc_bot", "PTC bottom", "C", "temp"),
    "av force":         ("force", "Force", "kN", "force"),
    "sv force":         ("force_sv", "Force (setpoint)", "kN", "force"),
    "av speed":         ("speed", "Ram speed", "mm/min", "speed"),
    "av abs. piston t": ("piston_abs", "Piston travel (abs)", "mm", "position"),
    "av rel. piston t": ("piston_rel", "Piston travel (rel)", "mm", "position"),
    "av press. abs. 1": ("pressure_abs", "Pressure (abs)", "mbar", "pressure"),
    "av press. rel.":   ("pressure_rel", "Pressure (rel)", "mbar", "pressure"),
    "av thermovak":     ("vacuum", "Vacuum", "mbar", "pressure"),
    "i rms":            ("sps_current", "SPS current", "kA", "current"),
    "u rms":            ("sps_voltage", "SPS voltage", "V", "voltage"),
    "av heating power":  ("sps_power", "SPS power", "kW", "power"),
    "sv temperature":   ("heating_sp", "Heating setpoint", "C", "temp"),
    # 250-machine labels (unit stripped from the header before lookup)
    "pyro top":                ("pyro_top", "Pyrometer (top)", "C", "temp"),
    "pyro front":              ("pyro_b", "Pyrometer (front)", "C", "temp"),
    "control tc 1":            ("tc1", "Control TC1", "C", "temp"),
    "piston tc upper ram":     ("ptc_top", "Piston TC (upper ram)", "C", "temp"),
    "piston tc contact area":  ("ptc_contact", "Piston TC (contact)", "C", "temp"),
    "piston tc cooling ram":   ("ptc_bot", "Piston TC (cooling ram)", "C", "temp"),
    "av pressing force":       ("force", "Force", "kN", "force"),
    "sv pressing force":       ("force_sv", "Force (setpoint)", "kN", "force"),
    "pressing speed":          ("speed", "Ram speed", "mm/min", "speed"),
    "presinng max. way":       ("piston_abs", "Piston travel (abs)", "mm", "position"),
    "pressing max. way":       ("piston_abs", "Piston travel (abs)", "mm", "position"),
    "pressing relative way":   ("piston_rel", "Piston travel (rel)", "mm", "position"),
    "absolute pressure vessel": ("pressure_abs", "Pressure (abs)", "mbar", "pressure"),
    "relative pressure vessel": ("pressure_rel", "Pressure (rel)", "mbar", "pressure"),
    "vacuum vessel":           ("vacuum", "Vacuum", "mbar", "pressure"),
    "sps power":               ("sps_power", "SPS power", "kW", "power"),
    "sps voltage":             ("sps_voltage", "SPS voltage", "V", "voltage"),
    "sps current":             ("sps_current", "SPS current", "kA", "current"),
    "sv sps heating temp.":    ("heating_sp", "Heating setpoint", "C", "temp"),
    "hydraulic oil temp.":     ("hyd_oil_temp", "Hydraulic oil temp", "C", "temp"),
}

# Unit string -> physical group, for pass-through columns without a canonical entry.
_UNIT_GROUP = {
    "c": "temp", "°c": "temp", "kn": "force", "mm": "position", "mm/min": "speed",
    "mbar": "pressure", "hpa": "pressure", "mbar(a)": "pressure", "mbar(g)": "pressure",
    "kw": "power", "v": "voltage", "ka": "current", "a": "current", "%": "percent",
    "l/min": "flow", "µs/cm": "other", "ms": "other",
}

# Wall-clock columns (not plottable series) by normalised label.
_TIME_COLS = {"no.", "date", "time", "p.time", "cur. time charge", "cur. time",
              "charge", "prozesstime 1", "prozesstime 2"}


def _slug(label: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "_", str(label).strip().lower()).strip("_")
    return s or "col"


def _split_label_unit(header: str) -> tuple[str, str]:
    """'AV pressing force [kN]' -> ('AV pressing force', 'kN'); '' unit if none."""
    m = re.match(r"^(.*?)\s*\[(.*?)\]\s*$", header.strip())
    if m:
        return m.group(1).strip(), m.group(2).strip()
    return header.strip(), ""


def _num_us(s: str):
    s = (s or "").strip()
    if s == "" or s == "-":
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _num_eu(s: str):
    """European decimal: '1.015,8' -> 1015.8 ; '0,0003' -> 0.0003 ; '-29,5' -> -29.5."""
    s = (s or "").strip()
    if s == "" or s == "-":
        return None
    s = s.replace(".", "").replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


def _hms_to_s(s: str):
    """'HH:MM:SS' (or 'H:MM:SS') -> seconds; returns None if not a clock string."""
    m = re.match(r"^\s*(\d+):(\d{1,2}):(\d{1,2})\s*$", str(s))
    if not m:
        return None
    h, mm, ss = (int(x) for x in m.groups())
    return h * 3600 + mm * 60 + ss


def detect_fast_format(raw: bytes) -> str:
    """'250' if the FCT HP D 250 shape, else '25'."""
    head = raw[:4000].decode("cp1252", errors="replace").lower()
    if "used recipe:" in head or "prozesstime" in head or ";" in head.splitlines()[3 if head.count("\n") > 3 else 0]:
        # the 250 export has the Plant/Recipe preamble and semicolon delimiters
        if "used recipe:" in head or "prozesstime" in head:
            return "250"
    return "25"


def _group_for(key: str, unit: str, canon_group: str | None) -> str:
    if canon_group:
        return canon_group
    return _UNIT_GROUP.get(unit.strip().lower(), "other")


def normalize_fast_csv(raw: bytes) -> dict:
    """Parse a raw FAST trace CSV (either machine) into one canonical form.

    Returns a dict: {format, plant, recipe, run_start (iso|None), n_rows, duration_s,
    columns: [{key,label,unit,group,min,max}], csv_text}. csv_text is a comma/US-decimal
    CSV whose first column is 'time_s [s]'. Physically-equivalent channels get a shared
    canonical key; everything else passes through under a slug of its own label.
    """
    fmt = detect_fast_format(raw)
    text = raw.decode("cp1252", errors="replace")
    lines = text.splitlines()
    plant = recipe = run_start = None

    if fmt == "250":
        # preamble: Plant / Used Recipe / StartTime Charge, then header on line 4.
        for ln in lines[:3]:
            low = ln.lower()
            if low.startswith("plant:"):
                plant = ln.split(":", 1)[1].strip()
            elif low.startswith("used recipe:"):
                recipe = ln.split(":", 1)[1].strip()
            elif "starttime" in low:
                run_start = _parse_dt_de(ln.split(":", 1)[1].strip() if ":" in ln else ln)
        header_raw = lines[3].split(";")
        data_lines = lines[4:]
        delim, num = ";", _num_eu
        headers = [_split_label_unit(h) for h in header_raw]
        # 250 time comes from Prozesstime 1 (HH:MM:SS)
        time_idx = next((i for i, (lab, _u) in enumerate(headers) if lab.strip().lower() == "prozesstime 1"), 1)
    else:
        header_raw = lines[0].split(",")
        units_row = lines[1].split(",") if len(lines) > 1 else []
        data_lines = lines[2:]
        delim, num = ",", _num_us
        headers = [(h.strip(), (units_row[i].strip() if i < len(units_row) else "")) for i, h in enumerate(header_raw)]
        time_idx = next((i for i, (lab, _u) in enumerate(headers) if lab.strip().lower() == "p.time"), 3)

    # Build per-column plans (skip wall-clock/index columns as plottable series).
    plans = []  # (idx, key, label, unit, group)
    seen_keys: set[str] = set()
    for i, (lab, unit) in enumerate(headers):
        norm = _norm(lab)
        if i == time_idx or norm in _TIME_COLS:
            continue
        canon = _CANON.get(norm)
        if canon:
            key, clabel, cunit, cgroup = canon
            unit = cunit or unit          # canonical (clean, ASCII) unit wins for cross-machine consistency
            label, group = clabel, cgroup
        else:
            key = _slug(lab)
            label, group = lab, None
        if key in seen_keys:
            key = f"{key}_{i}"
        seen_keys.add(key)
        plans.append((i, key, label, unit, _group_for(key, unit, group)))

    # Parse rows -> time_s + one value list per plan.
    n = len(plans)
    time_vals: list[float] = []
    series_vals: list[list] = [[] for _ in range(n)]
    for raw_line in data_lines:
        if not raw_line.strip():
            continue
        cells = raw_line.split(delim)
        t = _hms_to_s(cells[time_idx]) if time_idx < len(cells) else None
        if t is None:
            continue
        time_vals.append(float(t))
        for j, (idx, *_rest) in enumerate(plans):
            series_vals[j].append(num(cells[idx]) if idx < len(cells) else None)

    n_rows = len(time_vals)
    duration_s = (time_vals[-1] - time_vals[0]) if n_rows > 1 else 0.0

    # Keep only columns that carry numeric data (drop categorical/empty ones like the
    # 250's "Technol. Step" — not a plottable line series).
    columns = []
    keep = []  # (j, key, label, unit, group)
    for j, (idx, key, label, unit, group) in enumerate(plans):
        vals = [v for v in series_vals[j] if v is not None]
        if not vals:
            continue
        columns.append({
            "key": key, "label": label, "unit": unit, "group": group,
            "min": min(vals), "max": max(vals),
        })
        keep.append((j, key, label, unit, group))

    # Emit the canonical CSV (time_s first, then each kept column).
    out_header = ["time_s [s]"] + [f"{c['label']} [{c['unit']}]" if c["unit"] else c["label"] for c in columns]
    out_lines = [",".join(out_header)]
    for r in range(n_rows):
        row = [f"{time_vals[r]:g}"]
        for (j, *_rest) in keep:
            v = series_vals[j][r]
            row.append("" if v is None else f"{v:g}")
        out_lines.append(",".join(row))

    return {
        "format": fmt, "plant": plant, "recipe": recipe, "run_start": run_start,
        "n_rows": n_rows, "duration_s": duration_s, "columns": columns,
        "csv_text": "\n".join(out_lines) + "\n",
    }


def _parse_dt_de(s: str):
    """'13.06.2025 13:21:12' -> ISO 'YYYY-MM-DDTHH:MM:SS' (best effort), else None."""
    m = re.search(r"(\d{2})\.(\d{2})\.(\d{4})\s+(\d{1,2}):(\d{2}):(\d{2})", s)
    if not m:
        return None
    d, mo, y, h, mi, se = m.groups()
    return f"{y}-{mo}-{d}T{int(h):02d}:{mi}:{se}"
