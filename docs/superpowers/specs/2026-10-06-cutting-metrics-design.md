# Cutting metrics card (P6)

**Status:** Implemented. Implementation: `packages/force-plotting/src/cuttingMetrics.ts`, the "Cutting
metrics" card in `ForceDashboard.vue` and the extra columns in `statsCsv.ts`.

## Problem

Signal statistics gives per-axis mean/RMS/min/max over the crop window. Machinists and materials
people ask different questions: how big is the cutting force, how much power does the cut take,
what is the specific cutting energy of this material. Today they copy numbers into a spreadsheet
and redo the arithmetic with the operation sheet beside them. The dashboard already holds every
input (forces, RPM, feed, depth of cut, diameter), so it should show the numbers, with units and
the formula, and say plainly when an input is missing.

## Metrics, formulas, units

All over the crop window (the same window as Signal statistics). Forces in N, lengths in mm.

| Metric | Formula | Unit |
|---|---|---|
| Resultant mean / peak | per sample `\|F\| = sqrt(Fx² + Fy² + Fz²)`; mean and max over the window | N |
| Fc, Ff, Fp (mean) | `\|mean\|` of the mapped axis | N |
| Fc, Ff, Fp (peak) | `max \|x\|` of the mapped axis | N |
| Cutting speed vc | `π · D · n / 1000` (D in mm, n in rpm) | m/min (divide by 60 for m/s) |
| Cutting power Pc | `Fc · vc / 60`, i.e. `Fc · vc[m/s]` | W |
| Specific cutting energy kc | `Fc / (ap · f)` | N/mm² (= MPa) |

Fc is the **mean** tangential force, so Pc and kc are mean values. Feed-force power is neglected
in Pc (the feed velocity is orders of magnitude below vc), the standard approximation. kc is the
apparent value for this one cut, not a material constant (it depends on chip thickness, tool
geometry and wear).

## Axis mapping (an assumption, shown in the UI)

The repo does not define it. `process_force.m` and `docs/force-file-standards.md` only say Fx and
Fy are the two horizontal plate axes and Fz the sum of the four vertical corners. `angle.ts` /
`toFixedFrame` is the milling (RCD, rotating-frame) transform and says nothing about turning
directions. The mapping depends on how the plate is mounted under the tool post.

Default: **Fc (tangential, main cutting) = Fz, Ff (feed) = Fx, Fp (passive/radial) = Fy.**
Reasoning: the tool post sits on the plate, the tool tip is above the workpiece centre line, and
the main cutting force pushes the tool vertically, which is the plate's z. Confidence: medium for
Fc = Fz, low for the Fx/Fy split. The card therefore carries a select ("Axis mapping") with all six
assignments, the choice is remembered in localStorage, and every tooltip and the CSV (`axis_map`
column) name the mapping used. Operators confirm it once on a real cut (physical test backlog).

For face turning the feed and passive roles swap relative to longitudinal turning (feed is radial,
passive is along the spindle). Labels follow ISO 3002 (Fc, Ff, Fp); the select exists because the
physical orientation is not recorded anywhere.

## Inputs and where they come from

| Input | Source (fields the dashboard already fetches) | Notes |
|---|---|---|
| Fx, Fy, Fz | live cache, crop window | as Signal statistics |
| n (rpm) | **measured mean over the window** (`SignalStats.rpm.mean`) | not the target `machining_spindle_speed_rpm`; zero or non-finite is "unavailable", no silent fallback |
| D (mm) | the Diameter control (`editDiam`: per-op `outer_diameter` override, else cache header `CutDiameter`) | the spiral model's `D/2` is at the crop start |
| f (mm/rev) | operation `machining_feed_mm_per_rev`, else capture `feed` | |
| ap (mm) | operation `machining_axial_depth_of_cut_mm`, else capture `depth_of_cut` | |
| operation type | `machining_operation_subtype` prefix: `MT` turning, `MM` milling (same rule as `opTypeCategory` in force-app-web) | |

**Face turning.** The diameter shrinks as the tool spirals inward at `f` per rev, so vc is not
constant. vc uses the diameter at the window midpoint:
`D_mid = D - 2 · f · n · (t_mid - t_crop) / 60`, where `t_crop` is the cache crop start (where the
spiral model puts D), `t_mid` the window midpoint and `n` the window's mean rpm. If `D_mid <= 0`,
vc is unavailable. With no recorded feed the shrinkage cannot be computed, so vc uses the
crop-start diameter. The inner diameter is not used.

**Missing inputs.** Each metric is computed independently and is either a value or
`unavailable: <reason>` ("feed not recorded", "RPM is zero in this window", "diameter missing",
"depth of cut not recorded", "milling operation"). The UI shows "—" with the reason as tooltip;
the CSV leaves the cell empty.

**Milling.** Fc/Ff/Fp, vc, Pc and kc assume a turning geometry (one edge, one chip thickness).
For `MM*` operations they are unavailable (reason "milling operation: turning geometry assumed")
while the resultant stays available since it needs no geometry. Unknown or empty subtype: same,
reason "operation type unknown".

## Data flow

`computeSignalStats` additionally returns the window's resultant mean and peak (one extra term in
the pass that already iterates the window). The dashboard calls the pure
`computeCuttingMetrics({ stats, axisMap, opKind, diameterMm, feedMmPerRev, apMm, tMidMinusCropSec })`
and renders the result; it recomputes when stats, an input or the mapping change. The CSV gets one
set of columns repeated on every row, like the RPM columns.

## Out of scope

Milling metrics (average chip thickness, per-tooth force), feed/passive power, a target-RPM
fallback, rotating force into a tool frame, temperature or wear corrections, a schema change to
store the mounting orientation (worth doing once the real mapping is known), per-revolution
metrics.
