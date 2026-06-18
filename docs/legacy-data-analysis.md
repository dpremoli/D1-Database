# Legacy AppSheet/Sheets Data Analysis

Source: `Sample_Data.xlsx` (AppSheet → Google Sheets export), 17 sheets.
This document maps the *current* spreadsheet reality to the target schema
(`../system_requirements_specification.md`, `../plan.md`) and flags the gaps,
quirks, and migration hazards discovered in the real data.

> The export is the **data layer only**. AppSheet's app logic (virtual columns,
> REF relationships, slices, actions, automation bots, security filters) is not
> included — it lives in the AppSheet editor. Foreign keys below are inferred
> from the data.

## Sheet inventory

| Sheet | Rows | Role today | Maps to target entity |
|---|---:|---|---|
| **Inventory** | 141 | Physical items/samples | `physical_samples` (+ self-referential genealogy) |
| **FAST Runs** | 1417 | Sintering (FAST/SPS) runs | `manufacturing_operations` (method = FAST) |
| **Machining Operations** | 116 | Turning/milling passes, with big force files | `manufacturing_operations` (method = Turning/Milling) + file/edge links |
| **Insert Boxes Inventory** | 106 | Boxes of inserts | `tool_boxes` (grandparent) |
| **Inserts** | 1039 | Individual inserts | `cutting_inserts` (parent) |
| **Inserts Edges** | 153 | Discrete cutting edges | `insert_edges` (child) |
| **Insert Types** | 24 | Insert catalogue (Sandvik etc.) | reference: `insert_types` |
| **Tools** | 19 | Tool holders | reference/asset: `tools` |
| **Machines** | 7 | Equipment | reference/asset: `equipment` |
| **Operation** | 4 | Lookup (Turning, Milling…) | reference → `manufacturing_methods` |
| **OP Types** | 9 | Lookup (Roughing/Medium/Finishing + codes) | reference |
| **Manufacturing Codes** | 16 | Method→code (FAST=MF, Forged=MO) | reference |
| **Material Classification ISO** | 8 | P/M/K/N/S/H groups | reference |
| **Alloy Codes** | 1037 | Material catalogue + datasheets + density | reference: `materials`/`alloys` |
| **Alloying Elements** | 119 | Periodic-table reference data | reference (static) |
| **Users** | 15 | People + permissions | `users` / RBAC |
| **OCR Training** | 9 | Image→code OCR training pairs | out of core scope (ML plugin) |

## Key structural findings (these refine the schema)

1. **Samples have self-referential genealogy.** `Inventory` has `Parent`,
   `Contains`, and `Contains_All` columns referencing other `Unique ID`s — i.e.
   a disc is cut into child pieces. The spec emphasised *raw stock → sample*;
   the real data also needs **sample → sample lineage**. Add `parent_sample_id`
   + a `sample_composition` junction (a sample may contain/derive from many).

2. **Two divergent operation types validate the dynamic-template pattern.**
   `FAST Runs` (temperature/force/atmosphere/recipe) and `Machining Operations`
   (RPM/feed/insert-edge/coolant/force-file) share almost no columns. Today
   they're separate hardcoded sheets — exactly the "brittle schema" pain point.
   Target: one `manufacturing_operations` table + `manufacturing_methods` +
   `method_parameters`, with the per-method fields in `recorded_metadata JSONB`.

3. **The 3-level tooling hierarchy is real and exact:**
   `Insert Boxes Inventory` → `Inserts` (via `Insert Box`) → `Inserts Edges`
   (via `Parent Insert`). `Machining Operations` references both a `Tool` and an
   `Insert Edge ID` — matching spec §2D / §2E precisely.

4. **Heavy-data pipeline is already in use, informally.** `Machining Operations`
   carries `Force File Link`, `File Size [GB]`, and `Experiment Sheet` (a linked
   per-experiment Google Sheet). This is the §3 use case in the wild and the
   strongest argument for the MinIO + worker pipeline.

5. **No real Raw Stock Ledger exists yet.** Material provenance is currently a
   free-text `Material` field on `FAST Runs` (e.g. "CP Ti Swarf briquettes and
   powder", "RR1000") plus the `Alloy Codes` catalogue. The spec's `raw_stock_lots`
   ledger is genuinely **new** — provenance is the weakest current link.

6. **Dual identifier — hidden GUID + human-readable code.** Every sample has
   TWO identifiers, and the distinction is deliberate:
   - **`Unique ID`** (8-char hex GUID) — the *hidden, real* unique key AppSheet
     used in the background to guarantee uniqueness. → becomes the internal
     **primary key** (`sample_id`, UUID/GUID); all FKs point here.
   - **Item Code** e.g. `10-AA-MF-2023-06-03` =
     `{Sequential}-{AlloyCode}-{MethodCode}-{ManufacturingDate}` (AA=Ti-64 via
     `Alloy Codes`, MF=FAST via `Manufacturing Codes`). This is a **human-readable
     pseudonym**, sequential by design, whose whole point is to stay legible if a
     physical sample is found years later. → becomes a `sample_code` natural key
     (unique-constrained, **generated deterministically**, never the PK).

## Data-quality / migration hazards (for Phase 8)

- **Dates are Excel serials** (`45008.0`) and some are epoch-zero garbage
  (`1899-12-30: 00:00:00` = empty). Needs normalisation to real timestamps.
- **Free-text everywhere**: materials, locations, users-as-text ("Sam/Nigel/Joe").
  Needs mapping to FK references during migration.
- **Comma artifacts**: e.g. machine "NLX-2500, 700" split across cells.
- **Mixed identifier formats**: mostly 8-char hex GUIDs, but some numeric
  (`8.8881119E7`) — unify on UUID/GUID at migration.
- **Sparse columns**: many attributes blank; schema must allow nullable + JSONB.

## Security findings (raise immediately)

- **`Users` sheet is the login backend for a data-capture app** (the `ABFP
  Password` column, currently plaintext). In the target system this becomes the
  auth layer: the MATLAB/data-capture apps call the server to authenticate
  (API tokens for machine/app nodes; hashed credentials for humans). Passwords
  must be hashed on import — never migrated as plaintext.
- Only **two roles today** (Admin / User); spec wants three
  (Operator / Researcher / Administrator). Map during migration.
- **Export-control flags** exist on items and alloys (`Export Controlled?`) —
  the new RBAC/visibility model must honour these (potential ITAR/ECJU concern).

## Not yet captured from AppSheet (would need editor export)

REF relationships, virtual/computed columns, slices, actions, automation bots,
and security (row-filter) expressions. Most FKs are inferable from the data, so
this is a "nice to have," not a blocker.
