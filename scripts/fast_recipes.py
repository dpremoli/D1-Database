#!/usr/bin/env python3
"""Pure helpers for FAST recipe import (no I/O) — shared by both machine importers.

FAST 25 recipes live in ECS_Prog.mdb::Rezept keyed by ProgrammNr; a run links to one via
the trailing '/ N' in Versuch.Bezeichnung. FAST 250 recipes are PROGS/*.rcp files keyed by
name (no program number).

IMPORTANT: Rezept's Daten columns are offset by one relative to the Kopfdaten legend —
Rezept.Daten[N+1] corresponds to Kopfdaten.Nr = N (Daten1 is unused). Verified on recipe
1248: Daten3=Temperature '1200', Daten5=Force '44kN', Daten8=Tool size '40mm',
Daten10='20 min holding'. Note this differs from Versuch, whose DataCaption legend maps
Daten1..20 directly.
"""
from __future__ import annotations

import re
import uuid

_NS = uuid.uuid5(uuid.NAMESPACE_DNS, "d1-database.fast-recipe.v1")

REZEPT_OFFSET = 1  # Rezept.Daten[N + REZEPT_OFFSET] <-> Kopfdaten.Nr = N

# Kopfdaten.Nr for the fields we lift into typed columns.
_NR_TEMPERATURE = 2
_NR_FORCE = 4


def first_num(v) -> float | None:
    """First numeric token in a messy string ('13 kN' -> 13.0, '1325C' -> 1325.0)."""
    if v is None:
        return None
    s = str(v).strip()
    if not s:
        return None
    m = re.search(r"-?\d+(?:\.\d+)?", s.replace(",", "."))
    return float(m.group()) if m else None


def program_nr_from_bezeichnung(bez: str | None) -> int | None:
    """Trailing '/ N' in a Versuch title -> the recipe's ProgrammNr."""
    if not bez:
        return None
    m = re.search(r"/\s*(\d+)\s*$", str(bez).strip())
    return int(m.group(1)) if m else None


def _daten(daten: list, nr: int):
    """Value for Kopfdaten.Nr = nr, honouring the one-column offset."""
    i = nr + REZEPT_OFFSET - 1
    return daten[i] if 0 <= i < len(daten) else None


def _hold_minutes(daten: list) -> float | None:
    """Hold time is free text in a trailing 'Other' column ('20 min holding')."""
    for cell in daten:
        s = str(cell or "")
        m = re.search(r"(\d+(?:\.\d+)?)\s*min", s, re.IGNORECASE)
        if m:
            return float(m.group(1))
    return None


def rezept_targets(daten: list) -> dict:
    """Typed targets from a Rezept row's Daten1..20. Absent values are omitted."""
    out = {}
    temp = first_num(_daten(daten, _NR_TEMPERATURE))
    force = first_num(_daten(daten, _NR_FORCE))
    hold = _hold_minutes(daten)
    if temp is not None:
        out["target_temp_c"] = temp
    if force is not None:
        out["target_force_kn"] = force
    if hold is not None:
        out["hold_time_min"] = hold
    return out


def rcp_targets_from_name(name: str) -> dict:
    """Targets parsed from a FAST 250 .rcp filename, e.g.
    'D105_IN718_Briq_1125_35MPa_30mins' -> temp 1125, hold 30. Absent values omitted."""
    out = {}
    s = str(name or "")
    m = re.search(r"_(\d{3,4})\s*(?:°|deg)?C?_", s) or re.search(r"_(\d{3,4})_", s)
    if m:
        out["target_temp_c"] = float(m.group(1))
    m = re.search(r"(\d+(?:\.\d+)?)\s*kN", s, re.IGNORECASE)
    if m:
        out["target_force_kn"] = float(m.group(1))
    m = re.search(r"(\d+(?:\.\d+)?)\s*m(?:in|ins)?\b", s, re.IGNORECASE)
    if m:
        out["hold_time_min"] = float(m.group(1))
    return out


def recipe_id(machine: str, program_nr: int | None, name: str) -> str:
    """Deterministic UUID: FAST 25 keyed by ProgrammNr, FAST 250 by lower(name)."""
    key = f"fast{machine}|{program_nr}" if program_nr is not None \
        else f"fast{machine}|{str(name).strip().lower()}"
    return str(uuid.uuid5(_NS, key))
