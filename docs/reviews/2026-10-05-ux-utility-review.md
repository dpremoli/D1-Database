# UX and utility review — 2026-10-05

A read-only review of `main` at `1b6424d`, looking for features and tweaks that would make the
force app and the Directus side easier and more useful to work with. Three Sonnet reviewers
surveyed the operator workflow (Record, Settings, recovery, upload), the analysis side (Plot
dashboard, Diagnostics Workbench, filter and diag services) and the Directus side (extensions,
roles and permissions, schema). The coordinator re-checked the headline claims against the code.
Items already tracked as open issues (#108, #100, #97, #90, #86, #81, #80, #67, #64, #31, #30,
#20, #10) are left out.

Items marked *(idea)* are judgement calls the reviewers did not confirm in code. Sizes are S, M
or L. Paths are relative to the repo root.

**Status:** the "Fix first" items and the "Small, high-value" batch shipped in PR #123 (merged
2026-10-05); its description lists what changed. The "Next" tier (P3, P4, R4, R5, D4, D3) is in
[`docs/superpowers/plans/2026-10-06-ux-next-tier.md`](../superpowers/plans/2026-10-06-ux-next-tier.md).
Everything else is backlog.

## Fix first — broken or risky, not new features

| # | Finding | Evidence |
|---|---|---|
| X1 | Lite 3D "Z = Fx/Fy/Fz" renders flat | `packages/force-plotting/src/FrmCloud.vue` never reads `Cloud.zv` (since `5e3876a`); the wiki still advertises the mode with a screenshot. Noted in the "Pre-existing" section of `docs/superpowers/specs/2026-10-04-frm-signal-linking-design.md`. |
| X2 | Lab Member cannot save a cut | `known-issues.md` (Open): no create on `directus_files` and `machining_force_analysis`. `core/permissions.json` and `core/apply.sh` still describe the pre-Directus-11 role model (Operators get only `sample_code`, `current_status`, `notes`, and the old `operator_name`). |
| X3 | ~~Ask-DB bypasses Directus permissions~~ — **mostly already fixed** | The survey quoted the comment in `core/extensions/d1-ask-endpoint/index.js:3-12`, but migration `20261003000132_llm_readonly_allow_list.sql` already took `audit_logs`, `people`, `Machine_Operators` and every `directus_*` table away from the LLM role, and the endpoint already refuses users without app access. What remains is the export-control row filter (`docs/adr/0005`), deferred to Phase 9 as an owner decision. Not in this batch. |
| X4 | Stale wiki paragraph | `docs/wiki/force-app/recording.md` "Leaving the page mid-cut" says the save dialog opens only if the page sees the end of the cut; the 0.1.34 changelog says the Record page now offers to save on return. |

## Force app — recording

| # | Suggestion | Evidence | Size |
|---|---|---|---|
| R1 | Remember the setup across launches | `apps/force-app/web/src/record/workspace.ts:85-96` keeps `cfg`, `meta`, `machining`, `link` as plain `reactive` objects; only source, channels, plot prefs and recording prefs reach localStorage. `meta.sample_name` defaults to `'SIM-CUT-001'`. | M |
| R2 | Named setup presets, "repeat last cut" *(idea)* | Builds on R1. `MetadataPanel.vue` is imported nowhere (only `MachineOperatorPanel.vue` is used). | M |
| R3 | "New" leaves the last cut's per-cut fields | `newRun()` (`workspace.ts:480`) clears only transient state; pass code, `operation_sequence`, `chips_ref` stay, so the Cut ID repeats. TODO at `record/panels/RecordingOptions.vue:295` (auto-generate chips ref). | S |
| R4 | Pre-flight check before Start | Start gates are alarm-test, disk and sample-rate only (`workspace.ts:286-341`); "no Sample" first appears in `SaveCutDialog.vue:305`. | M |
| R5 | Live clipping / rail warning | Clipping is computed only at finalize (`backend/app/finalize.py:215-221`) and used by Converge after the cut. | M |
| R6 | Alarms: early warning, auto-stop, accessibility | `record/alarms.ts:48-62` latches at one threshold; the overlay (`RecordPage.vue:540`) has no `role="alert"`; the tone forces system volume to max. | S–M |
| R7 | Disk runway and ETA for hardware runs | ETA only for the simulator (`OverviewPanel.vue:30-35`); the pre-Start disk estimate always uses the removed 8 s duration (`RecordingOptions.vue:202-210`). | S |
| R8 | Fix metadata inside the save dialog | `SaveCutDialog.vue` has no sample, notes or operation fields. | M |
| R9 | Captures list: search, filter, bulk actions | `settings/CapturesSettings.vue:91,107` is a plain list capped silently at 500; `uploadAllUnsynced` has no progress or cancel. | M |
| R10 | Keyboard shortcuts on Record | No handlers for Start/Stop/acknowledge/New. | S |
| R11 | "Restart recorder" in the packaged app | `settings/ConnectivitySettings.vue:80-90` tells operators to run `python -m uvicorn`. | S |
| R12 | Bug report attaches capture summary/manifest | `settings/ReportBugSettings.vue`, `backend/app/bug_report.py` send no capture context. | M |
| R13 | Release notes in the update prompt; Help menu items | `desktop/src/updater.ts:55-68`; `desktop/src/menu.ts` has only two links. | S |
| R14 | First-run checklist (drive, alarm limits, amp) *(idea)* | No first-run flow in `web/src`. | S–M |

## Force app — Plot dashboard and Diagnostics

| # | Suggestion | Evidence | Size |
|---|---|---|---|
| P1 | CSV export (signal stats, wear trend, cluster table, series) | Only export is the FRM PNG (`frmExport.ts`, `ForceDashboard.vue:2191`). | M |
| P2 | SVG/PNG export of signal charts | `ForceChart.vue` has no export; reuse `frmExport.ts` framing. | M |
| P3 | Shareable deep link to a view | `?operation=` is read (`ForceDashboard.vue:1064`) but never written; mode, axes, zoom, compare set, map view are not in the URL. | M |
| P4 | Pass-to-pass difference | `alignAndDiff` (`compare.ts:44`) is exported but no `.vue` calls it. | M |
| P5 | Wider Compare (align by rev/radius, delta readout, FFT) | Force mode only, time-aligned (`ForceDashboard.vue:1795-1830`). | M |
| P6 | Cutting metrics (resultant, Fc/Ff/Fp, power, specific energy) | Nothing in force-plotting; feed, depth, speed already fetched (`ForceDashboard.vue:1044-1052`). | M |
| P7 | Wear trend beyond peak force | `WearTrend.vue:64,100` fetches only `peak_f*`. | S–M |
| P8 | Saved, named markers per operation | Marker clears on Escape; persistence deferred in the 2026-10-04 spec. | M |
| P9 | Polar Plot on the dashboard | `PolarPlot.vue` exists; `ForceDashboard.vue` doesn't import it. Spec follow-ups put tooth-pass lines on FFT first. | M |
| P10 | Diagnostics across a campaign | `RecipeLibrary.vue` uses `window.prompt`/`confirm`; no batch apply; `DiagnosticsPage.vue:143` is a flat `<select>` with `limit: -1`. | M–L |
| P11 | Help overlay for gestures; units everywhere | Right-click/drag interactions undocumented in-app; `ForceChart.vue:472,502` falls back to `"amp"`. | S |
| P12 | Scale the campaign list | `limit: -1` plus a client-side Metadata Doctor over every row (`ForceDashboard.vue:1035-1060`); 2D pick ~0.3–0.5 s at 5M points. | M |
| P13 | Filter/diag service batch endpoints *(idea)* | Only `/run`, `/fft`, `/spectrogram`, `/preview`, `/viewport`. | S–M |

## Directus

| # | Suggestion | Evidence | Size |
|---|---|---|---|
| D1 | Ask-DB example question chips | `d1-ask-db/src/chat.vue:88-95` has one hint paragraph; 62 curated questions sit in `plugins/llm-text-to-sql/eval/questions.json`. | S |
| D2 | Ask-DB: say when rows were truncated; clearer errors | `plugins/llm-text-to-sql/api.py:145-164` applies `row_limit` with no `truncated` flag; guard rejections say only "Try rephrasing"; 502/504 show raw strings. | S |
| D3 | Ask-DB: CSV download, copy SQL, saved questions, feedback | `chat.vue` keeps turns in memory only. | M |
| D4 | Sample label / QR printing and scan-to-open | QR exists only inside A4 reports (`d1-report/src/index.js:287,372,414`). | M |
| D5 | Sample timeline view | SRS §5; `f_sample_timeline`, `f_trace_*` exist; `plan.md:368` "visual timeline UI deferred". | M–L |
| D6 | Reverse traceability breadcrumbs on tests/operations | `d1-archive-links` lists UNC paths only. | S–M |
| D7 | Dashboard click-through to records | `d1-lab-dashboard/src/views/*.vue` have no links to `/content/...`. | S |
| D8 | Clone / bulk create / copy-from-last | `register-sample.vue` creates one sample per submit; no clone anywhere. | M |
| D9 | Next sample number without fetching every code | `d1-home/src/register-sample.vue:81-92`, `d1-sample-code` `SampleCode.vue` fetch all `sample_code` (`limit:-1`); undercounts when permissions hide rows (2026-10-03 review 4.5). | S |
| D10 | Per-user home page and "needs attention" tiles | `d1-home` `home.vue` shows global counts and recents only. | S–M |
| D11 | Campaign overview (samples → tests → force status) | `d1-campaign-ops` `CampaignOps.vue:68-80` queries operations only. | M |
| D12 | Saved filters / bookmarks | `scripts/.../configure_directus.sql:205-235` seeds one global bookmark. | S |
| D13 | Notifications on processing finish/fail *(idea)* | No Flows beyond the `directus_flows` stub (migration 030). | M |
| D14 | Note search UI | pgvector `/api/search` has no UI consumer. | S–M |
| D15 | Phone/tablet layouts *(idea)* | Only four extensions have media queries. | S–M |

## Suggested order

1. **Fix first:** X1, X2, X4 (X3 is already fixed apart from the Phase 9 export-control filter).
2. **Small, high-value:** R1 + R3 (setup persistence and "New"), D1 + D2 (Ask-DB examples and
   truncation), P1 (CSV export), D7 (dashboard click-through), D9 (next sample number).
3. **Next:** P3 (deep links), R4 + R5 (pre-flight and live clipping), P4 (pass-to-pass
   difference), D4 (QR labels), D3.
4. **Larger:** D5, P10, D11, P6, R9.
