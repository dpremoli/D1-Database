# Experiment Sheets & Deterministic Naming Conventions

Source: `Experiment_Sheet_AI4340AMRCES23032301.xlsx` — one example of the
per-experiment Google Sheet linked from each `Machining Operations` row.
Companion to [`legacy-data-analysis.md`](./legacy-data-analysis.md).

> Note: the *internal* binary format of the force-data files is intentionally
> out of scope for now (per maintainer). What matters here is how experiments,
> passes, and files are **structured and named**.

## What an "Experiment Sheet" actually is

A controlled document (AMRC GESS template, Rev 2) describing one machining
**campaign** against one or more workpieces. Four tabs:

1. **Document control** — formal metadata: project reference
   (`AI4340 – FAST ROLLED PLATE DETECTION`), document number
   (`AI4340-AMRC-ES-230323-01`), author, revision (`V01`), status (`Released`).
2. **Experiment Sheet** — the data: one row per **machining pass**, with cutting
   parameters, tool/insert/edge, capture settings, and the force-file ID.
3. **GCode (NC.xxxx)** — the annotated NC/G-code program for the passes
   (e.g. `Maximum_RPM=4500`, `T0909`, `G96 S30`).
4. **Sheet1** — helper lookups (Vc↔cut-time table; sample code↔description).

**Implication:** an experiment sheet ≈ a *batch of machining-pass records* that
today live in a separate Google Sheet. In the target system these passes become
first-class `manufacturing_operations` rows; the "experiment sheet" becomes a
**generated report**, not a separate hand-maintained file.

## The naming hierarchy (all deterministic, all human-readable)

Codes are built up compositionally — each level extends the one above:

| Level | Example | Pattern |
|---|---|---|
| Sample / workpiece | `9-AA-MR-2023-03-23` | `{seq}-{alloy}-{method}-{YYYY-MM-DD}` |
| Pass | `9-AA-MR-2023-03-23-F9` | `{sample_code}-{passtype}{n}` (`F`=facing, `R`=roughing) |
| Force file ID | `9-AA-MR-2023-03-23-F9-20MPM_0.05feed_0.1DoC` | `{pass_code}-{Vc}MPM_{feed}feed_{DoC}DoC` |

- `Vc` = cutting speed [m/min] ("MPM" = metres/min), `feed` = Fz [mm/rev],
  `DoC` = depth of cut / Ap [mm].
- Sentinels in the data: `N/S` (not specified), `N/R` (not recorded/run),
  `N/A` (not applicable), stray `` ` `` = missing.

**Design rule (same principle as `sample_code`):** these human-readable IDs are
*projections of real FK + parameter data*, never the primary key. The MinIO
object holding the file gets the real key; the force-file ID is the legible
label, regenerable from the operation record. → a shared **code-generation
service** produces sample codes, pass codes, and force-file IDs from one place.

## Machining-pass fields worth capturing (Experiment Sheet tab)

`Facing Pass ID`, `Pass #`, `Workpiece ID` (→ sample), `Workpiece Information`
(FAST recipe context), `Program (G96/G97)`, **`Force Data File ID`**, `Vc`,
`Max RPM`, `Fz [mm/rev]`, `Axial/DoC [mm]`, `Diameter [mm]`, `Tool ID`,
`Insert ID` (e.g. `H13A-#2-fC`, `PCD20-#1`, `1150-#1-fA`), `New Edge`,
`Tacho`, `Coolant` + pressure, `Chips Collected`, `SEM Captured`, `Cut Time`,
**`Captured With`** (e.g. `MATLAB ABFP 0.16/0.18` — capture app + version),
**`Freq. [kHz]`** (e.g. `25.6` — sampling rate), `Notes`.

## New / refined entities this reveals

- **Projects / Campaigns** (e.g. `AI4340`) — a grouping above operations, with
  controlled-document numbering. Experiments/sessions roll up to a project. NEW.
- **Machining passes** as the granular operation unit (each = one force file).
- **Capture provenance** on each pass: capture software + version (`ABFP`) and
  sampling frequency [kHz] — needed to interpret the force file later.
- **NC programs (G-code)** as text/file artifacts linked to passes.
- **Dual identity extends to inserts/edges too**: human code `H13A-#2-fC`
  (type-insert#-edge/face) alongside the GUID edge IDs from `Inserts Edges`.

## Glossary clarified

- **ABFP** = the in-house MATLAB data-capture app (does force capture at
  25.6 kHz, names files per the convention above, and authenticates users
  against the `Users` backend — see `legacy-data-analysis.md`).
- **Method codes:** `MF`=FAST, `MO`=Forged, `MR`=Rolled (per `Manufacturing
  Codes` + observed data).
