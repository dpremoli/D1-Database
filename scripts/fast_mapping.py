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
