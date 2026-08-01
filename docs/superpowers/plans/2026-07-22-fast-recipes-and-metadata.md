# FAST Recipes + Machine-Sourced Metadata Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Link every FAST sintering operation to a real recipe record, and surface correct machine-sourced (not Google-sheet) metadata in the FAST dashboard's operation detail.

**Architecture:** A new `fast_recipes` collection is populated from each machine's own recipe store (`ECS_Prog.mdb::Rezept` for FAST 25, `PROGS/*.rcp` for FAST 250) and linked from `manufacturing_operations.fast_recipe_id`. Measured run peaks are computed at import into the existing-but-unused `fast_run_data.summary` JSONB. The dashboard detail panel then prefers *measured* values, falls back to *recorded* machine metadata, and uses the sheet logs only for CoSHH + comments.

**Tech Stack:** PostgreSQL + Directus 11, Python 3.13 (`psycopg2`, `access-parser`, `pytest`), Vue 3 + TypeScript (Directus extensions SDK), Playwright for UI verification.

## Global Constraints

- **Machine data is authoritative for all non-QA metadata.** Only `sintering_coshh_ref` and `outcome_notes` (comments/failures/alarms) may come from the sheet logs.
- **Rezept field offset:** `Rezept.Daten[N+1]` corresponds to `Kopfdaten.Nr = N`. Verified: recipe 1248 → `Daten3`=Temperature `1200`, `Daten5`=Force `44kN`, `Daten7`=Pyro/TC, `Daten8`=Tool size `40mm`, `Daten10`=`20 min holding`. `Daten1` is unused.
- **FAST 25 recipe key:** trailing `/\s*(\d+)\s*$` in `Versuch.Bezeichnung` is the `ProgrammNr`.
- **Recipe identity (deterministic, for idempotency):** `uuid5(NS, "fast25|<ProgrammNr>")` or `uuid5(NS, "fast250|<lower(name)>")`, where `NS = uuid5(NAMESPACE_DNS, "d1-database.fast-recipe.v1")`.
- **Idempotency:** every importer uses `INSERT … ON CONFLICT … DO UPDATE`; re-runs must produce zero net new rows and must not reset `fast_run_data.status='done'`.
- **Do not touch** `core/extensions/d1-force-dashboard/`, `/filter/run`, or the `.mat` pipeline.
- **Run Python with `py`** (Windows Store aliases shadow `python`). DB via `DATABASE_URL=postgres://d1:<POSTGRES_PASSWORD>@localhost:5432/d1_database`.
- **Data root** (stand-in remote PC): `C:\Users\CMBE Admn 3214022001\Downloads\FAST Machines Data`.

---

## File Structure

**Create**
- `db/migrations/20260722000100_fast_recipes.sql` — table, `fast_recipe_id` column, Directus registration.
- `db/migrations/20260722000101_fast_op_form_groups.sql` — operation-form grouping by provenance.
- `scripts/fast_recipes.py` — pure recipe parsing/identity helpers (no I/O).
- `tests/scripts/test_fast_recipes.py` — unit tests for the above.
- `tests/scripts/test_fast_summary.py` — unit tests for trace summarisation.
- `core/extensions/d1-fast-dashboard/src/fastMeta.ts` — pure `buildOpMeta` / `buildStats`.
- `tests/ui/verify_fast_recipe_panel.mjs` — Playwright check of the reshaped panel.

**Modify**
- `scripts/fast_mapping.py` — add `summarize_trace()`; `normalize_fast_csv` returns `summary`.
- `scripts/fast_orchestrator.py` — persist `summary` in the existing UPDATE.
- `scripts/import_fast25.py` — import Rezept recipes, link ops, drop the local `first_num`.
- `scripts/import_fast250.py` — import `PROGS/*.rcp` recipes, link ops by name.
- `scripts/apply_fast_qa_backup.py` — narrow to CoSHH + notes; add `--revert`.
- `core/extensions/d1-fast-dashboard/src/FastDashboard.vue` — consume `fastMeta.ts`, add recipe card, request new fields.

---

## Task 1: Migration — `fast_recipes` table + operation link

**Files:**
- Create: `db/migrations/20260722000100_fast_recipes.sql`

**Interfaces:**
- Consumes: nothing.
- Produces: table `fast_recipes(id, machine, program_nr, name, group_name, source_file, target_temp_c, target_force_kn, hold_time_min, params, date_created, date_changed, created_at, updated_at)`; column `manufacturing_operations.fast_recipe_id UUID`; Directus collection `fast_recipes`, M2O field `fast_recipe_id`, O2M field `fast_recipes.runs`.

- [ ] **Step 1: Write the migration**

```sql
-- migrate:up
-- FAST sintering recipes, imported from each machine's own recipe store:
--   FAST 25  -> ECS_Prog.mdb::Rezept (keyed by ProgrammNr)
--   FAST 250 -> PROGS/*.rcp          (keyed by name; no program number)
-- Operations link via manufacturing_operations.fast_recipe_id.

CREATE TABLE fast_recipes (
    id              UUID        NOT NULL DEFAULT uuid_generate_v4(),
    machine         VARCHAR(8)  NOT NULL,
    program_nr      INTEGER,
    name            TEXT        NOT NULL,
    group_name      TEXT,
    source_file     TEXT,
    target_temp_c   NUMERIC,
    target_force_kn NUMERIC,
    hold_time_min   NUMERIC,
    params          JSONB,
    date_created    TIMESTAMPTZ,
    date_changed    TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT fast_recipes_pkey PRIMARY KEY (id),
    CONSTRAINT fast_recipes_machine_chk CHECK (machine IN ('25', '250'))
);

COMMENT ON TABLE fast_recipes IS
    'FAST sintering recipe definitions (ECS_Prog.mdb::Rezept for 25, PROGS/*.rcp for 250).';

-- Identity differs per machine: FAST 25 is keyed by ProgrammNr (two recipes may legitimately
-- share a ProgrammText), FAST 250 has no program number and is keyed by name. Two partial
-- indexes, NOT one composite — a plain (machine, lower(name)) unique index would wrongly
-- reject duplicate-titled FAST 25 recipes.
CREATE UNIQUE INDEX fast_recipes_prog_uniq ON fast_recipes (machine, program_nr)
    WHERE program_nr IS NOT NULL;
CREATE UNIQUE INDEX fast_recipes_name_uniq ON fast_recipes (machine, lower(name))
    WHERE program_nr IS NULL;

ALTER TABLE manufacturing_operations
    ADD COLUMN IF NOT EXISTS fast_recipe_id UUID REFERENCES fast_recipes(id) ON DELETE SET NULL;
CREATE INDEX manufacturing_operations_fast_recipe_idx
    ON manufacturing_operations (fast_recipe_id);

-- ── Directus registration ──────────────────────────────────────────────────────
INSERT INTO directus_collections (collection, icon, note, display_template, hidden, "group", sort)
VALUES ('fast_recipes', 'science',
        'FAST sintering recipe definitions imported from the machine recipe stores',
        '{{name}}', false, 'manufacturing_methods', 11)
ON CONFLICT (collection) DO NOTHING;

INSERT INTO directus_fields (collection, field, interface, display, options, width, sort, special, readonly, hidden)
SELECT collection, field, interface, display, options::json, width, sort, special, readonly, hidden
FROM (VALUES
    ('fast_recipes', 'name',            'input', 'raw', NULL, 'full', 1, NULL, true, false),
    ('fast_recipes', 'machine',         'input', 'raw', NULL, 'half', 2, NULL, true, false),
    ('fast_recipes', 'program_nr',      'input', 'raw', NULL, 'half', 3, NULL, true, false),
    ('fast_recipes', 'group_name',      'input', 'raw', NULL, 'half', 4, NULL, true, false),
    ('fast_recipes', 'target_temp_c',   'input', 'raw', NULL, 'half', 5, NULL, true, false),
    ('fast_recipes', 'target_force_kn', 'input', 'raw', NULL, 'half', 6, NULL, true, false),
    ('fast_recipes', 'hold_time_min',   'input', 'raw', NULL, 'half', 7, NULL, true, false),
    ('fast_recipes', 'source_file',     'input', 'raw', NULL, 'full', 8, NULL, true, false),
    ('fast_recipes', 'params',          'input-code', 'raw', NULL, 'full', 20, 'cast-json', true, true)
) v(collection, field, interface, display, options, width, sort, special, readonly, hidden)
WHERE NOT EXISTS (
    SELECT 1 FROM directus_fields f WHERE f.collection = v.collection AND f.field = v.field
);

-- M2O on the operation form.
INSERT INTO directus_fields (collection, field, interface, display, options, display_options, width, sort, special, hidden)
SELECT 'manufacturing_operations', 'fast_recipe_id', 'select-dropdown-m2o', 'related-values',
       '{"template":"{{name}}","enableCreate":false}', '{"template":"{{name}}"}', 'half', 50, 'm2o', false
WHERE NOT EXISTS (
    SELECT 1 FROM directus_fields f
    WHERE f.collection = 'manufacturing_operations' AND f.field = 'fast_recipe_id'
);

-- O2M back-reference so a recipe page lists its runs.
INSERT INTO directus_fields (collection, field, interface, special, options, display, width, sort, hidden)
SELECT 'fast_recipes', 'runs', 'list-o2m', 'o2m',
       '{"template":"{{pass_code}}","enableCreate":false,"enableSelect":false}',
       'related-values', 'full', 30, false
WHERE NOT EXISTS (
    SELECT 1 FROM directus_fields f WHERE f.collection = 'fast_recipes' AND f.field = 'runs'
);

INSERT INTO directus_relations (many_collection, many_field, one_collection, one_field, one_deselect_action)
SELECT 'manufacturing_operations', 'fast_recipe_id', 'fast_recipes', 'runs', 'nullify'
WHERE NOT EXISTS (
    SELECT 1 FROM directus_relations r
    WHERE r.many_collection = 'manufacturing_operations' AND r.many_field = 'fast_recipe_id'
);

-- Lab Member: read-only.
INSERT INTO directus_permissions (policy, collection, action, permissions, validation, fields)
SELECT '20000002-0000-0000-0000-000000000002', 'fast_recipes', 'read', '{}', '{}', '*'
WHERE NOT EXISTS (
    SELECT 1 FROM directus_permissions p
    WHERE p.policy = '20000002-0000-0000-0000-000000000002'
      AND p.collection = 'fast_recipes' AND p.action = 'read'
);

-- migrate:down
DELETE FROM directus_permissions WHERE collection = 'fast_recipes';
DELETE FROM directus_relations   WHERE many_collection = 'manufacturing_operations' AND many_field = 'fast_recipe_id';
DELETE FROM directus_fields      WHERE collection = 'fast_recipes';
DELETE FROM directus_fields      WHERE collection = 'manufacturing_operations' AND field = 'fast_recipe_id';
DELETE FROM directus_collections WHERE collection = 'fast_recipes';
ALTER TABLE manufacturing_operations DROP COLUMN IF EXISTS fast_recipe_id;
DROP TABLE IF EXISTS fast_recipes;
```

- [ ] **Step 2: Apply the migration**

Run:
```bash
docker exec -i d1-database-postgres-1 psql -U d1 -d d1_database \
  < db/migrations/20260722000100_fast_recipes.sql
```
Expected: `CREATE TABLE`, `CREATE INDEX` ×3, `ALTER TABLE`, several `INSERT 0 1`. No `ERROR`.

- [ ] **Step 3: Verify schema**

Run:
```bash
docker exec d1-database-postgres-1 psql -U d1 -d d1_database -c "\d fast_recipes" \
 -c "SELECT column_name FROM information_schema.columns WHERE table_name='manufacturing_operations' AND column_name='fast_recipe_id';"
```
Expected: table definition with both partial unique indexes listed, and one row `fast_recipe_id`.

- [ ] **Step 4: Commit**

```bash
git add db/migrations/20260722000100_fast_recipes.sql
git commit -m "feat(fast): add fast_recipes collection and operation link"
```

---

## Task 2: Pure recipe helpers + tests

**Files:**
- Create: `scripts/fast_recipes.py`
- Create: `tests/scripts/test_fast_recipes.py`

**Interfaces:**
- Consumes: nothing (pure module, no I/O).
- Produces:
  - `first_num(v) -> float | None`
  - `recipe_id(machine: str, program_nr: int | None, name: str) -> str` (uuid5 string)
  - `program_nr_from_bezeichnung(bez: str | None) -> int | None`
  - `rezept_targets(daten: list) -> dict` with optional keys `target_temp_c`, `target_force_kn`, `hold_time_min`
  - `rcp_targets_from_name(name: str) -> dict` with the same optional keys
  - `REZEPT_OFFSET: int = 1`

- [ ] **Step 1: Write the failing tests**

```python
# tests/scripts/test_fast_recipes.py
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "scripts"))

import fast_recipes as fr


def test_program_nr_from_bezeichnung():
    assert fr.program_nr_from_bezeichnung("Ti-64 1200C  100/min / 1248") == 1248
    assert fr.program_nr_from_bezeichnung("STAR_CIPFAST_0.5_1325 / 2793") == 2793
    assert fr.program_nr_from_bezeichnung("no trailing number") is None
    assert fr.program_nr_from_bezeichnung(None) is None


def test_rezept_targets_uses_offset_by_one():
    # Rezept.Daten[N+1] <-> Kopfdaten.Nr = N. Real values from recipe 1248.
    daten = ["", "Affaan", "1200", "Ti64-20V", "44kN", "vac", "pyro",
             "40mm", "42 g", "20 min holding"] + [""] * 10
    t = fr.rezept_targets(daten)
    assert t["target_temp_c"] == 1200
    assert t["target_force_kn"] == 44
    assert t["hold_time_min"] == 20


def test_rezept_targets_omits_absent_values():
    daten = [""] * 20
    assert fr.rezept_targets(daten) == {}


def test_rcp_targets_from_name():
    t = fr.rcp_targets_from_name("D105_IN718_Briq_1125_35MPa_30mins")
    assert t["target_temp_c"] == 1125
    assert t["hold_time_min"] == 30


def test_recipe_id_is_deterministic_and_machine_scoped():
    a = fr.recipe_id("25", 1248, "Ti64")
    assert a == fr.recipe_id("25", 1248, "different name")   # 25 keyed by program_nr
    b = fr.recipe_id("250", None, "D105_IN718")
    assert b == fr.recipe_id("250", None, "d105_in718")      # 250 keyed by lower(name)
    assert a != b


def test_first_num():
    assert fr.first_num("13 kN") == 13
    assert fr.first_num("1325C") == 1325
    assert fr.first_num("") is None
    assert fr.first_num(None) is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `py -m pytest tests/scripts/test_fast_recipes.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'fast_recipes'`

- [ ] **Step 3: Write the implementation**

```python
#!/usr/bin/env python3
"""Pure helpers for FAST recipe import (no I/O) — shared by both machine importers.

FAST 25 recipes live in ECS_Prog.mdb::Rezept keyed by ProgrammNr; a run links to one via
the trailing '/ N' in Versuch.Bezeichnung. FAST 250 recipes are PROGS/*.rcp files keyed by
name (no program number).

IMPORTANT: Rezept's Daten columns are offset by one relative to the Kopfdaten legend —
Rezept.Daten[N+1] corresponds to Kopfdaten.Nr = N (Daten1 is unused). Verified on recipe
1248: Daten3=Temperature '1200', Daten5=Force '44kN', Daten8=Tool size '40mm',
Daten10='20 min holding'.
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `py -m pytest tests/scripts/test_fast_recipes.py -v`
Expected: PASS — 6 passed.

- [ ] **Step 5: Commit**

```bash
git add scripts/fast_recipes.py tests/scripts/test_fast_recipes.py
git commit -m "feat(fast): pure recipe parsing helpers with Rezept offset handling"
```

---

## Task 3: FAST 25 recipe import + linking

**Files:**
- Modify: `scripts/import_fast25.py`

**Interfaces:**
- Consumes: `fast_recipes.first_num`, `.program_nr_from_bezeichnung`, `.rezept_targets`, `.recipe_id`.
- Produces: `fast_recipes` rows for machine `'25'`; `manufacturing_operations.fast_recipe_id` set on ~9,600 ops.

- [ ] **Step 1: Import the shared helpers and drop the local duplicate**

In `scripts/import_fast25.py`, add below the existing `import fast_mapping as fm`:

```python
import fast_recipes as frx
```

Delete the local `first_num` function (it now lives in `fast_recipes`) and add an alias so existing call sites keep working:

```python
first_num = frx.first_num
```

- [ ] **Step 2: Read Rezept and build recipe rows**

Add this function above `read_versuch`:

```python
def read_recipes(data_root: str) -> list[dict]:
    """ECS_Prog.mdb::Rezept -> fast_recipes rows for machine '25'."""
    from access_parser import AccessParser
    db = AccessParser(os.path.join(data_root, PROG_REL))
    r = db.parse_table("Rezept")
    out = []
    for i, pn in enumerate(r["ProgrammNr"]):
        if pn is None:
            continue
        pn = int(pn)
        name = _s(r["ProgrammText"][i]) or f"Recipe {pn}"
        daten = [r[f"Daten{n}"][i] for n in range(1, 21)]
        row = {
            "id": frx.recipe_id("25", pn, name),
            "machine": "25",
            "program_nr": pn,
            "name": name,
            "group_name": _s(r["GroupName"][i]),
            "source_file": _s(r["FileName"][i]),
            "params": {f"Daten{n}": _s(daten[n - 1]) for n in range(1, 21)},
            "date_created": parse_dt(r["DateCreate"][i], None),
            "date_changed": parse_dt(r["DateChange"][i], None),
        }
        row.update(frx.rezept_targets(daten))
        out.append(row)
    return out
```

Add the path constant next to `MDB_REL`:

```python
PROG_REL = os.path.join("FAST 25", "ECS2000", "Recipes", "1001", "ECS_Prog.mdb")
```

- [ ] **Step 3: Capture the recipe key on each run**

In `read_versuch`, inside the per-row dict, add:

```python
            "program_nr": frx.program_nr_from_bezeichnung(_s(v["Bezeichnung"][i])),
```

- [ ] **Step 4: Upsert recipes and link operations**

In `main()`, after the `materials` upsert and before the operations upsert, insert:

```python
    recipes = read_recipes(args.data_root)
    psycopg2.extras.execute_values(
        cur,
        "INSERT INTO fast_recipes (id, machine, program_nr, name, group_name, source_file, "
        "target_temp_c, target_force_kn, hold_time_min, params, date_created, date_changed) "
        "VALUES %s ON CONFLICT (id) DO UPDATE SET "
        "  name=EXCLUDED.name, group_name=EXCLUDED.group_name, source_file=EXCLUDED.source_file, "
        "  target_temp_c=EXCLUDED.target_temp_c, target_force_kn=EXCLUDED.target_force_kn, "
        "  hold_time_min=EXCLUDED.hold_time_min, params=EXCLUDED.params, "
        "  date_changed=EXCLUDED.date_changed, updated_at=now()",
        [(r["id"], r["machine"], r["program_nr"], r["name"], r["group_name"], r["source_file"],
          r.get("target_temp_c"), r.get("target_force_kn"), r.get("hold_time_min"),
          psycopg2.extras.Json(r["params"]), r["date_created"], r["date_changed"])
         for r in recipes],
        page_size=500,
    )
    print(f"upserted {len(recipes)} FAST 25 recipes")
    by_prog = {r["program_nr"]: r["id"] for r in recipes}
```

Add `fast_recipe_id` to the `cols` list (after `"sintering_recipe_number"`):

```python
        "fast_recipe_id",
```

and to each tuple in `values`, immediately after `o["recipe_title"]`:

```python
        by_prog.get(o["program_nr"]),
```

- [ ] **Step 5: Dry-run to check link rate**

Run:
```bash
DATABASE_URL="postgres://d1:$(grep POSTGRES_PASSWORD .env | cut -d= -f2)@localhost:5432/d1_database" \
  py scripts/import_fast25.py "C:/Users/CMBE Admn 3214022001/Downloads/FAST Machines Data" --dry-run
```
Expected: `FAST 25: 9735 operations …` and no traceback.

- [ ] **Step 6: Run for real and verify linkage**

Run:
```bash
DATABASE_URL="postgres://d1:$(grep POSTGRES_PASSWORD .env | cut -d= -f2)@localhost:5432/d1_database" \
  py scripts/import_fast25.py "C:/Users/CMBE Admn 3214022001/Downloads/FAST Machines Data"
docker exec d1-database-postgres-1 psql -U d1 -d d1_database -c \
 "SELECT count(*) FROM fast_recipes WHERE machine='25';" -c \
 "SELECT count(*) FILTER (WHERE fast_recipe_id IS NOT NULL) AS linked, count(*) AS total
    FROM manufacturing_operations WHERE source_system='fast_25';"
```
Expected: ~2,761 recipes; `linked` ≈ 9,600 of `total` 9,735.

- [ ] **Step 7: Verify a link is semantically correct**

Run:
```bash
docker exec d1-database-postgres-1 psql -U d1 -d d1_database -c \
 "SELECT o.sintering_recipe_number, r.program_nr, r.name, r.target_temp_c, r.target_force_kn
    FROM manufacturing_operations o JOIN fast_recipes r ON r.id=o.fast_recipe_id
   WHERE o.source_run_uid='fast25|4926';"
```
Expected: `program_nr` 1248, name `Ti64 -20V-1200°C  100/min`, `target_temp_c` 1200, `target_force_kn` 44.

- [ ] **Step 8: Commit**

```bash
git add scripts/import_fast25.py
git commit -m "feat(fast): import FAST 25 recipes and link runs via ProgrammNr"
```

---

## Task 4: FAST 250 recipe import + linking

**Files:**
- Modify: `scripts/import_fast250.py`

**Interfaces:**
- Consumes: `fast_recipes.recipe_id`, `.rcp_targets_from_name`.
- Produces: `fast_recipes` rows for machine `'250'`; `fast_recipe_id` set on FAST 250 ops.

- [ ] **Step 1: Import helpers**

Below `import fast_mapping as fm` in `scripts/import_fast250.py`:

```python
import fast_recipes as frx
```

- [ ] **Step 2: Read PROGS/*.rcp into recipe rows**

Add above `build_ops`:

```python
def read_recipes(data_root: str) -> dict[str, dict]:
    """PROGS/*.rcp -> {lower(name): recipe row} for machine '250'."""
    out: dict[str, dict] = {}
    for path in glob.glob(os.path.join(data_root, REL_ROOT, "PROGS", "*.rcp")):
        name = os.path.splitext(os.path.basename(path))[0]
        try:
            text = open(path, "rb").read().decode("cp1252", errors="replace")
        except OSError:
            text = ""
        segments = [ln.split(";") for ln in text.splitlines() if ln.strip()]
        row = {
            "id": frx.recipe_id("250", None, name),
            "machine": "250", "program_nr": None, "name": name,
            "group_name": None,
            "source_file": os.path.relpath(path, data_root).replace("\\", "/"),
            "params": {"segments": segments[:40]},
        }
        row.update(frx.rcp_targets_from_name(name))
        out[name.strip().lower()] = row
    return out
```

- [ ] **Step 3: Create name-only recipes for runs whose recipe has no .rcp file**

The export list truncates recipe names, so a run's recipe may not match any `PROGS/*.rcp`. Never drop the link — synthesise a name-only recipe. In `main()`, after `ops, traces = build_ops(...)`:

```python
    recipes = read_recipes(args.data_root)
    for o in ops:
        nm = (o["recipe"] or "").strip()
        if not nm:
            continue
        key = nm.lower()
        if key not in recipes:
            recipes[key] = {
                "id": frx.recipe_id("250", None, nm), "machine": "250", "program_nr": None,
                "name": nm, "group_name": None, "source_file": None, "params": None,
                **frx.rcp_targets_from_name(nm),
            }
        o["fast_recipe_id"] = recipes[key]["id"]
```

- [ ] **Step 4: Upsert recipes and add the column**

In `main()`, before the operations upsert:

```python
    psycopg2.extras.execute_values(
        cur,
        "INSERT INTO fast_recipes (id, machine, program_nr, name, group_name, source_file, "
        "target_temp_c, target_force_kn, hold_time_min, params) VALUES %s "
        "ON CONFLICT (id) DO UPDATE SET name=EXCLUDED.name, source_file=EXCLUDED.source_file, "
        "  target_temp_c=EXCLUDED.target_temp_c, target_force_kn=EXCLUDED.target_force_kn, "
        "  hold_time_min=EXCLUDED.hold_time_min, params=EXCLUDED.params, updated_at=now()",
        [(r["id"], r["machine"], r["program_nr"], r["name"], r["group_name"], r["source_file"],
          r.get("target_temp_c"), r.get("target_force_kn"), r.get("hold_time_min"),
          psycopg2.extras.Json(r["params"]) if r.get("params") else None)
         for r in recipes.values()],
        page_size=500,
    )
    print(f"upserted {len(recipes)} FAST 250 recipes")
```

Add `"fast_recipe_id"` to `cols` after `"sintering_recipe_number"`, and to each `values` tuple after `o["recipe"]`:

```python
        o.get("fast_recipe_id"),
```

- [ ] **Step 5: Run and verify**

Run:
```bash
DATABASE_URL="postgres://d1:$(grep POSTGRES_PASSWORD .env | cut -d= -f2)@localhost:5432/d1_database" \
  py scripts/import_fast250.py "C:/Users/CMBE Admn 3214022001/Downloads/FAST Machines Data"
docker exec d1-database-postgres-1 psql -U d1 -d d1_database -c \
 "SELECT count(*) FROM fast_recipes WHERE machine='250';" -c \
 "SELECT count(*) FILTER (WHERE fast_recipe_id IS NOT NULL) AS linked, count(*) AS total
    FROM manufacturing_operations WHERE source_system='fast_250';"
```
Expected: recipes ≥ 100; `linked` equals `total` minus only those runs with an empty recipe string.

- [ ] **Step 6: Verify idempotency**

Run the same import command a second time, then:
```bash
docker exec d1-database-postgres-1 psql -U d1 -d d1_database -c \
 "SELECT count(*) FROM fast_recipes;" -c "SELECT status,count(*) FROM fast_run_data GROUP BY status;"
```
Expected: recipe count unchanged; all `fast_run_data` still `done` (no rows reset to `pending`).

- [ ] **Step 7: Commit**

```bash
git add scripts/import_fast250.py
git commit -m "feat(fast): import FAST 250 recipes from PROGS and link runs by name"
```

---

## Task 5: Measured run summary into `fast_run_data.summary`

**Files:**
- Modify: `scripts/fast_mapping.py`
- Modify: `scripts/fast_orchestrator.py:194-205`
- Create: `tests/scripts/test_fast_summary.py`

**Interfaces:**
- Consumes: canonical channel keys already in `fast_mapping._CANON` (`pyro_top`, `force`, `sps_power`, `sps_voltage`, `ptc_top`, `ptc_bot`).
- Produces: `fast_mapping.summarize_trace(series: dict[str, list], time_s: list[float]) -> dict`; `normalize_fast_csv(...)["summary"]`; `fast_run_data.summary` populated.

- [ ] **Step 1: Write the failing tests**

```python
# tests/scripts/test_fast_summary.py
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "scripts"))

import fast_mapping as fm


def test_summarize_trace_peaks_and_shape():
    # 0..100..100..0 degC ramp/hold/cool over 40 s at 1 Hz
    t = list(range(40))
    temp = list(range(0, 100, 5)) + [100] * 10 + list(range(100, 50, -5))
    series = {"pyro_top": temp, "force": [0] * 20 + [63.1] * 20}
    s = fm.summarize_trace(series, t)
    assert s["peak_temp_c"] == 100
    assert s["peak_force_kn"] == 63.1
    assert s["dwell_s"] > 0
    assert s["ramp_c_per_min"] > 0


def test_summarize_trace_omits_absent_channels():
    s = fm.summarize_trace({"pyro_top": [1, 2, 3]}, [0, 1, 2])
    assert "peak_temp_c" in s
    assert "peak_force_kn" not in s
    assert "peak_power_kw" not in s


def test_summarize_trace_handles_nones_and_empty():
    assert fm.summarize_trace({}, []) == {}
    s = fm.summarize_trace({"pyro_top": [None, 5, None]}, [0, 1, 2])
    assert s["peak_temp_c"] == 5


def test_normalize_fast_csv_returns_summary():
    raw = (
        b"P.time,AV Pyrometer,AV Force\n"
        b"s,C,kN\n"
        b"0:00:01,100,10\n0:00:02,200,20\n0:00:03,150,15\n"
    )
    res = fm.normalize_fast_csv(raw)
    assert res["summary"]["peak_temp_c"] == 200
    assert res["summary"]["peak_force_kn"] == 20
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `py -m pytest tests/scripts/test_fast_summary.py -v`
Expected: FAIL — `AttributeError: module 'fast_mapping' has no attribute 'summarize_trace'`

- [ ] **Step 3: Implement `summarize_trace`**

Append to `scripts/fast_mapping.py`:

```python
# Canonical channel key -> summary key for simple peak (max) metrics.
_PEAK_KEYS = {
    "pyro_top": "peak_temp_c",
    "force": "peak_force_kn",
    "sps_power": "peak_power_kw",
    "sps_voltage": "peak_voltage_v",
    "ptc_top": "ptc_top_max_c",
    "ptc_bot": "ptc_bot_max_c",
}


def summarize_trace(series: dict, time_s: list) -> dict:
    """Measured run summary from decoded channels.

    `series` maps canonical channel keys (see _CANON) to value lists aligned with `time_s`.
    Absent channels simply omit their key — every consumer must treat all keys as optional.
    dwell_s = time spent within 2 % of peak temperature; ramp_c_per_min = mean slope between
    the first crossings of 10 % and 90 % of peak temperature.
    """
    out: dict = {}
    for chan, key in _PEAK_KEYS.items():
        vals = [v for v in (series.get(chan) or []) if v is not None]
        if vals:
            out[key] = max(vals)

    temps = series.get("pyro_top") or []
    pairs = [(t, v) for t, v in zip(time_s, temps) if v is not None]
    if len(pairs) < 2:
        return out
    peak = max(v for _t, v in pairs)
    if peak <= 0:
        return out

    hot = [t for t, v in pairs if v >= peak * 0.98]
    if hot:
        out["dwell_s"] = round(hot[-1] - hot[0], 1)

    lo = next((t for t, v in pairs if v >= peak * 0.10), None)
    hi = next((t for t, v in pairs if v >= peak * 0.90), None)
    if lo is not None and hi is not None and hi > lo:
        out["ramp_c_per_min"] = round((peak * 0.80) / ((hi - lo) / 60.0), 1)
    return out
```

- [ ] **Step 4: Return the summary from `normalize_fast_csv`**

In `normalize_fast_csv`, immediately before the final `return {`, add:

```python
    by_key = {key: series_vals[j] for (j, key, *_rest) in keep}
    summary = summarize_trace(by_key, time_vals)
```

and add `"summary": summary,` to the returned dict.

- [ ] **Step 5: Run tests to verify they pass**

Run: `py -m pytest tests/scripts/test_fast_summary.py -v`
Expected: PASS — 4 passed.

- [ ] **Step 6: Persist the summary in the orchestrator**

In `scripts/fast_orchestrator.py`, in `process_row`'s UPDATE, change the `series=%s::jsonb,` line to:

```python
                    n_rows=%s, duration_s=%s, series=%s::jsonb, summary=%s::jsonb,
```

and add `json.dumps(res.get("summary") or {})` to the parameter list immediately after `json.dumps(res["columns"])`.

- [ ] **Step 7: Backfill the 305 existing traces**

Because the importer's guard skips `done` rows, reset them explicitly, then drain:

```bash
docker exec d1-database-postgres-1 psql -U d1 -d d1_database -c \
 "UPDATE fast_run_data SET status='pending' WHERE status='done';"
DATABASE_URL="postgres://d1:$(grep POSTGRES_PASSWORD .env | cut -d= -f2)@localhost:5432/d1_database" \
  py scripts/import_fast250.py "C:/Users/CMBE Admn 3214022001/Downloads/FAST Machines Data"
```
Then run the orchestrator (takes ~10 min):
```powershell
$env:ARCHIVE_UNC = "C:\Users\CMBE Admn 3214022001\Downloads\FAST Machines Data"
$env:DIRECTUS_URL = "http://localhost:8055"
& "C:\Program Files\Python313\python.exe" scripts/fast_orchestrator.py --run
```
Expected: `run: processed 305 row(s)`.

- [ ] **Step 8: Verify summaries landed**

Run:
```bash
docker exec d1-database-postgres-1 psql -U d1 -d d1_database -c \
 "SELECT count(*) FILTER (WHERE summary ? 'peak_temp_c') AS with_peak, count(*) FROM fast_run_data;" -c \
 "SELECT summary FROM fast_run_data WHERE status='done' LIMIT 1;"
```
Expected: `with_peak` = 305 of 305; the sample shows `peak_temp_c`, `peak_force_kn`, `dwell_s`.

- [ ] **Step 9: Commit**

```bash
git add scripts/fast_mapping.py scripts/fast_orchestrator.py tests/scripts/test_fast_summary.py
git commit -m "feat(fast): compute measured run summary into fast_run_data.summary"
```

---

## Task 6: Narrow the QA carryover and revert the over-reach

**Files:**
- Modify: `scripts/apply_fast_qa_backup.py`

**Interfaces:**
- Consumes: `fast_log_qa_backup` (already populated, 1,895 rows).
- Produces: a `--revert` mode; the normal mode writes only `sintering_coshh_ref` and `outcome_notes`.

- [ ] **Step 1: Narrow the UPDATE to QA-only columns**

Replace the `UPDATE` constant in `scripts/apply_fast_qa_backup.py` with:

```python
# Machine data is authoritative for everything except true QA fields. Only CoSHH and the
# free-text observations come from the sheet logs; mass/mould/PTC/V/P are recoverable as
# measured values from the trace summary, so they are deliberately NOT written here.
UPDATE = """
UPDATE manufacturing_operations SET
    sintering_coshh_ref = COALESCE(sintering_coshh_ref, %(coshh)s),
    outcome_notes = CASE WHEN NULLIF(btrim(COALESCE(outcome_notes,'')),'') IS NULL
                         THEN %(notes)s ELSE outcome_notes END,
    updated_at = now()
WHERE operation_id = %(oid)s
"""
```

Remove `ptc_top`, `ptc_bot`, `mass`, `mould` from the `updates.append({...})` dict so only `oid`, `coshh`, and `notes` are passed.

- [ ] **Step 2: Add the revert mode**

Add this constant and wire it into `main()`:

```python
# One-off correction: the first run of this script filled ANY null machine field from the
# sheets. Only these four can ONLY have come from the sheets — no machine importer writes
# them — so nulling them across machine-sourced sintering ops is safe and precise.
#
# Deliberately NOT nulled here: sintering_mass_grams and sintering_mould_diameter_mm. Both
# ARE machine-sourced (FAST 25 Daten9/Daten7, FAST 250 Load), so blanket-nulling them would
# destroy real MDB data. Re-running the importers restores them from machine truth instead
# (their upserts already set both columns from EXCLUDED) — see Step 3b.
REVERT = """
UPDATE manufacturing_operations SET
    sintering_ptc_top_celsius    = NULL,
    sintering_ptc_bot_celsius    = NULL,
    sintering_voltage_at_max_t_v = NULL,
    sintering_power_at_max_t_kw  = NULL,
    updated_at = now()
WHERE process_category='sintering' AND source_system IN ('fast_25','fast_250')
"""
```

In `main()`, immediately after the connection is opened:

```python
    if "--revert" in sys.argv:
        cur.execute(REVERT)
        print(f"reverted sheet-written non-QA columns on {cur.rowcount} operations")
        conn.commit()
        cur.close(); conn.close(); return
```

- [ ] **Step 3: Run the revert**

Run:
```bash
DATABASE_URL="postgres://d1:$(grep POSTGRES_PASSWORD .env | cut -d= -f2)@localhost:5432/d1_database" \
  py scripts/apply_fast_qa_backup.py --revert
```
Expected: `reverted sheet-written non-QA columns on N operations` (N > 0).

- [ ] **Step 3b: Restore mass / mould Ø from machine truth**

The revert deliberately leaves `sintering_mass_grams` and `sintering_mould_diameter_mm` alone
because both are genuinely machine-sourced. Re-running the importers overwrites whatever the
sheets wrote with the machine value (or NULL where the machine has none), because both upserts
already set these columns from `EXCLUDED`:

```bash
DB="postgres://d1:$(grep POSTGRES_PASSWORD .env | cut -d= -f2)@localhost:5432/d1_database"
DATABASE_URL="$DB" py scripts/import_fast25.py  "C:/Users/CMBE Admn 3214022001/Downloads/FAST Machines Data"
DATABASE_URL="$DB" py scripts/import_fast250.py "C:/Users/CMBE Admn 3214022001/Downloads/FAST Machines Data"
```
Expected: `upserted 9735 …` and `upserted 313 …`; `fast_run_data` rows stay `done`.

- [ ] **Step 4: Re-apply the narrowed QA and verify the backup is intact**

Run:
```bash
DATABASE_URL="postgres://d1:$(grep POSTGRES_PASSWORD .env | cut -d= -f2)@localhost:5432/d1_database" \
  py scripts/apply_fast_qa_backup.py
docker exec d1-database-postgres-1 psql -U d1 -d d1_database -c \
 "SELECT count(*) FROM fast_log_qa_backup;" -c \
 "SELECT count(*) FILTER (WHERE sintering_ptc_top_celsius IS NOT NULL) AS ptc_left,
         count(*) FILTER (WHERE sintering_coshh_ref IS NOT NULL) AS coshh
    FROM manufacturing_operations WHERE process_category='sintering';"
```
Expected: backup still 1,895; `ptc_left` = 0; `coshh` > 0.

- [ ] **Step 5: Re-run pass-code finalisation**

Mould Ø changes alter the `{params}` tail of the codes, so regenerate them:

```bash
DATABASE_URL="postgres://d1:$(grep POSTGRES_PASSWORD .env | cut -d= -f2)@localhost:5432/d1_database" \
  py scripts/finalize_fast_codes.py
```
Expected: `assigned pass_code to 10048 sintering operations`.

- [ ] **Step 6: Commit**

```bash
git add scripts/apply_fast_qa_backup.py
git commit -m "fix(fast): restrict sheet QA carryover to CoSHH and comments only"
```

---

## Task 7: Reshape the dashboard detail panel

**Files:**
- Create: `core/extensions/d1-fast-dashboard/src/fastMeta.ts`
- Modify: `core/extensions/d1-fast-dashboard/src/FastDashboard.vue`
- Create: `tests/ui/verify_fast_recipe_panel.mjs`

**Interfaces:**
- Consumes: `fast_run_data.summary` (Task 5), `fast_recipe_id` (Tasks 3–4).
- Produces: `buildOpMeta(detail) -> MetaRow[]`, `buildStats(detail, fastRun) -> Stat[]`, `type Stat = { label: string; value: string; unit: string; source: 'measured' | 'recorded' | 'QA log' }`.

- [ ] **Step 1: Write `fastMeta.ts`**

```ts
// Pure metadata/stat derivation for the FAST detail panel, kept out of FastDashboard.vue
// so it stays readable and these rules are testable on their own.
//
// Provenance rule (project-wide): machine data and the measured trace are authoritative for
// every non-QA field. The sheet logs supply ONLY CoSHH ref and comments.

export type Source = 'measured' | 'recorded' | 'QA log';
export interface Stat { label: string; value: string; unit: string; source: Source; }
export type MetaRow = [string, string];

function num(v: any, dp = 1): string | null {
	if (v === null || v === undefined || v === '') return null;
	const n = Number(v);
	return Number.isFinite(n) ? n.toFixed(dp).replace(/\.0+$/, '') : null;
}

export function buildOpMeta(detail: any): MetaRow[] {
	if (!detail) return [];
	const rows: Array<[string, any]> = [
		['Sample', detail.sample_id?.sample_code],
		['Date', detail.operation_date ? new Date(detail.operation_date).toLocaleString() : null],
		['Operator', detail.operator_name],
		['Machine', detail.equipment_id?.equipment_name],
		['Material', detail.material_id?.common_name || detail.sintering_material_type_note],
		['Recipe', detail.fast_recipe_id?.name || detail.sintering_recipe_number],
		['Batch', detail.sintering_batch_number],
		['Atmosphere', detail.sintering_atmosphere],
		['TC/Pyro', detail.sintering_tc_pyro_control],
		['CoSHH', detail.sintering_coshh_ref],
	];
	return rows
		.filter(([, v]) => v !== null && v !== undefined && String(v).trim() !== '')
		.map(([k, v]) => [k, String(v)] as MetaRow);
}

// Each stat: prefer the measured trace summary, else the recorded machine metadata.
// A stat with neither source is omitted entirely rather than rendered empty.
const STAT_DEFS: Array<{ label: string; unit: string; sum?: string; rec?: string; dp?: number }> = [
	{ label: 'Peak temp',  unit: '°C', sum: 'peak_temp_c',    rec: 'sintering_max_temp_celsius' },
	{ label: 'Peak force', unit: 'kN', sum: 'peak_force_kn',  rec: 'sintering_max_force_kn' },
	{ label: 'Peak power', unit: 'kW', sum: 'peak_power_kw' },
	{ label: 'Peak volts', unit: 'V',  sum: 'peak_voltage_v' },
	{ label: 'PTC top',    unit: '°C', sum: 'ptc_top_max_c' },
	{ label: 'PTC bot',    unit: '°C', sum: 'ptc_bot_max_c' },
	{ label: 'Dwell',      unit: 's',  sum: 'dwell_s',        dp: 0 },
	{ label: 'Ramp',       unit: '°C/min', sum: 'ramp_c_per_min' },
	{ label: 'Mould Ø',    unit: 'mm', rec: 'sintering_mould_diameter_mm' },
	{ label: 'Mass',       unit: 'g',  rec: 'sintering_mass_grams', dp: 2 },
];

export function buildStats(detail: any, fastRun: any): Stat[] {
	const summary = fastRun?.summary || {};
	const out: Stat[] = [];
	for (const d of STAT_DEFS) {
		const measured = d.sum ? num(summary[d.sum], d.dp ?? 1) : null;
		if (measured !== null) { out.push({ label: d.label, value: measured, unit: d.unit, source: 'measured' }); continue; }
		const recorded = d.rec && detail ? num(detail[d.rec], d.dp ?? 1) : null;
		if (recorded !== null) out.push({ label: d.label, value: recorded, unit: d.unit, source: 'recorded' });
	}
	return out;
}

export function buildRecipe(detail: any) {
	const r = detail?.fast_recipe_id;
	if (!r || typeof r !== 'object') return null;
	return {
		id: r.id, name: r.name, programNr: r.program_nr,
		targets: [
			r.target_temp_c ? `${num(r.target_temp_c, 0)} °C` : null,
			r.target_force_kn ? `${num(r.target_force_kn, 1)} kN` : null,
			r.hold_time_min ? `${num(r.hold_time_min, 0)} min` : null,
		].filter(Boolean).join(' · '),
	};
}
```

- [ ] **Step 2: Wire it into the view**

In `FastDashboard.vue`, add to the imports:

```ts
import { buildOpMeta, buildRecipe, buildStats } from './fastMeta';
```

Replace the whole `const opMeta = computed(...)` and `const stats = computed(...)` blocks with:

```ts
const opMeta = computed(() => buildOpMeta(detail.value));
const stats = computed(() => buildStats(detail.value, fastRun.value));
const recipe = computed(() => buildRecipe(detail.value));
```

- [ ] **Step 3: Request the new fields**

In `selectOp`, change the detail `fields` array to include the recipe:

```ts
					fields: ['*', 'equipment_id.equipment_name', 'method_id.method_name',
						'material_id.common_name', 'sample_id.sample_code', 'sample_id.nickname', 'sample_id.sample_id',
						'fast_recipe_id.id', 'fast_recipe_id.name', 'fast_recipe_id.program_nr',
						'fast_recipe_id.target_temp_c', 'fast_recipe_id.target_force_kn', 'fast_recipe_id.hold_time_min'],
```

In `loadFastRun`, add `'summary'` to its `fields` array.

- [ ] **Step 4: Render the recipe card and stat provenance**

In the template, find the line `<div class="stat-sep">Sinter cycle</div>` and insert this block on the line **directly above** it:

```html
							<template v-if="recipe">
								<div class="stat-sep">Recipe</div>
								<div class="kv">
									<span>Name</span><span>{{ recipe.name }}</span>
									<template v-if="recipe.programNr"><span>Program</span><span>{{ recipe.programNr }}</span></template>
									<template v-if="recipe.targets"><span>Targets</span><span>{{ recipe.targets }}</span></template>
								</div>
							</template>
```

Change the stat tile to show provenance — replace the `<span class="s-lab">{{ st.label }}</span>` line with:

```html
									<span class="s-lab">{{ st.label }}<em class="s-src">{{ st.source }}</em></span>
```

Add to the `<style>` block:

```css
.s-src { display:block; font-style:normal; font-size:9px; opacity:.55; text-transform:uppercase; letter-spacing:.03em; }
```

- [ ] **Step 5: Build to typecheck**

Run:
```bash
cd core/extensions/d1-fast-dashboard && npm run build
```
Expected: build succeeds, no TypeScript errors. Then restart Directus so the extension reloads:
```bash
cd ../../.. && docker restart d1-database-directus-1
```

- [ ] **Step 6: Write the Playwright verification**

```js
// tests/ui/verify_fast_recipe_panel.mjs
// Verifies the reshaped FAST detail panel: recipe card + provenance-tagged stats.
import { chromium } from 'playwright';

const BASE = process.env.DIRECTUS_URL || 'http://localhost:8055';
const EMAIL = process.env.DIRECTUS_ADMIN_EMAIL;
const PASSWORD = process.env.DIRECTUS_ADMIN_PASSWORD;

const browser = await chromium.launch();
const page = await browser.newPage();
await page.goto(`${BASE}/admin/login`);
await page.fill('input[type="email"]', EMAIL);
await page.fill('input[type="password"]', PASSWORD);
await page.click('button[type="submit"]');
await page.waitForURL('**/admin/**', { timeout: 30000 });

await page.goto(`${BASE}/admin/d1-fast-dashboard`);
await page.waitForSelector('.rowcard', { timeout: 30000 });
// Pick a run that has a trace (badge reads "trace").
const withTrace = page.locator('.rowcard', { hasText: 'trace' }).first();
await withTrace.click();
await page.waitForSelector('.statgrid', { timeout: 30000 });

const text = await page.locator('.col-stack').innerText();
const okRecipe = /Recipe/.test(text);
const okMeasured = /measured/i.test(text);
console.log('recipe card present:', okRecipe);
console.log('measured provenance present:', okMeasured);
await page.screenshot({ path: 'tests/ui/fast_recipe_panel.png', fullPage: true });
await browser.close();
if (!okRecipe || !okMeasured) { console.error('FAIL'); process.exit(1); }
console.log('PASS');
```

- [ ] **Step 7: Run the verification**

Run:
```bash
set -a && source .env && set +a && node tests/ui/verify_fast_recipe_panel.mjs
```
Expected: `recipe card present: true`, `measured provenance present: true`, `PASS`.

- [ ] **Step 8: Commit**

```bash
git add core/extensions/d1-fast-dashboard/src/fastMeta.ts \
        core/extensions/d1-fast-dashboard/src/FastDashboard.vue \
        tests/ui/verify_fast_recipe_panel.mjs
git commit -m "feat(fast): recipe card and provenance-tagged machine-sourced stats"
```

---

## Task 8: Directus operation form grouping

**Files:**
- Create: `db/migrations/20260722000101_fast_op_form_groups.sql`

**Interfaces:**
- Consumes: `manufacturing_operations.fast_recipe_id` (Task 1).
- Produces: two `group-detail` alias fields on `manufacturing_operations` —
  `sintering_machine_group`, `sintering_qa_group` — with the sintering fields assigned to them.

> **Convention (important):** group-detail accordions in this project must be created with base
> `hidden = false` plus a "hide unless" condition. Creating them with `hidden = true` and showing
> them conditionally makes Directus throw "Unexpected Error" on the record page.

- [ ] **Step 1: Write the migration**

```sql
-- migrate:up
-- Split the sintering fields on the operation form by provenance so it's obvious which values
-- come from the machine and which are hand-entered QA. Both groups are created hidden=false
-- with a "hide unless sintering" condition — the inverse (hidden=true + show-conditions) makes
-- Directus error on the record page.

INSERT INTO directus_fields (collection, field, special, interface, options, conditions, sort, width, hidden)
SELECT 'manufacturing_operations', v.field, 'alias,no-data,group', 'group-detail',
       v.options::json, v.conditions::json, v.sort, 'full', false
FROM (VALUES
    ('sintering_machine_group',
     '{"start":"open"}',
     '[{"name":"Hide unless sintering","rule":{"_and":[{"process_category":{"_neq":"sintering"}}]},"hidden":true}]',
     60),
    ('sintering_qa_group',
     '{"start":"closed"}',
     '[{"name":"Hide unless sintering","rule":{"_and":[{"process_category":{"_neq":"sintering"}}]},"hidden":true}]',
     61)
) v(field, options, conditions, sort)
WHERE NOT EXISTS (
    SELECT 1 FROM directus_fields f
    WHERE f.collection = 'manufacturing_operations' AND f.field = v.field
);

-- Machine-sourced fields (MDB / export list / measured trace).
UPDATE directus_fields SET "group" = 'sintering_machine_group'
 WHERE collection = 'manufacturing_operations'
   AND field IN ('fast_recipe_id', 'sintering_recipe_number', 'sintering_batch_number',
                 'sintering_max_temp_celsius', 'sintering_max_force_kn',
                 'sintering_mould_diameter_mm', 'sintering_mass_grams',
                 'sintering_atmosphere', 'sintering_tc_pyro_control',
                 'sintering_material_type_note');

-- QA-log fields (hand-entered; the only values still sourced from the sheets).
UPDATE directus_fields SET "group" = 'sintering_qa_group'
 WHERE collection = 'manufacturing_operations'
   AND field IN ('sintering_coshh_ref', 'sintering_ptc_top_celsius', 'sintering_ptc_bot_celsius',
                 'sintering_voltage_at_max_t_v', 'sintering_power_at_max_t_kw');

-- migrate:down
UPDATE directus_fields SET "group" = NULL
 WHERE collection = 'manufacturing_operations'
   AND "group" IN ('sintering_machine_group', 'sintering_qa_group');
DELETE FROM directus_fields
 WHERE collection = 'manufacturing_operations'
   AND field IN ('sintering_machine_group', 'sintering_qa_group');
```

- [ ] **Step 2: Apply the migration**

Run:
```bash
docker exec -i d1-database-postgres-1 psql -U d1 -d d1_database \
  < db/migrations/20260722000101_fast_op_form_groups.sql
```
Expected: `INSERT 0 2`, two `UPDATE n`. No `ERROR`.

- [ ] **Step 3: Verify the grouping**

Run:
```bash
docker exec d1-database-postgres-1 psql -U d1 -d d1_database -c \
 "SELECT field, \"group\" FROM directus_fields
   WHERE collection='manufacturing_operations' AND (\"group\" LIKE 'sintering%' OR field LIKE 'sintering%group')
   ORDER BY \"group\" NULLS FIRST, field;"
```
Expected: both group rows present with `group` NULL, and every sintering field assigned to one of the two groups.

- [ ] **Step 4: Confirm the record page renders**

Open a FAST operation in Directus (`/admin/content/manufacturing_operations`) and confirm the two
accordions render with no "Unexpected Error", and that a non-sintering operation hides both.

- [ ] **Step 5: Commit**

```bash
git add db/migrations/20260722000101_fast_op_form_groups.sql
git commit -m "feat(fast): group operation form fields by machine vs QA provenance"
```

---

## Final verification

- [ ] **Run the full check**

```bash
py -m pytest tests/scripts -v
docker exec d1-database-postgres-1 psql -U d1 -d d1_database -c \
 "SELECT machine, count(*) FROM fast_recipes GROUP BY machine;" -c \
 "SELECT source_system, count(*) FILTER (WHERE fast_recipe_id IS NOT NULL) AS linked, count(*) AS total
    FROM manufacturing_operations WHERE process_category='sintering' GROUP BY source_system;" -c \
 "SELECT count(*) FILTER (WHERE summary ? 'peak_temp_c') AS with_summary, count(*) FROM fast_run_data;"
git status --short core/extensions/d1-force-dashboard/ | grep -v '^??' || echo "FRM untouched"
```

Expected:
- pytest: all tests pass.
- `fast_recipes`: ~2,761 for machine `25`, ≥100 for `250`.
- linked: ~9,600/9,735 (fast_25), ~all (fast_250).
- `with_summary` = 305 of 305.
- `FRM untouched`.
