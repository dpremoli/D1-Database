# UX next tier — 2026-10-06

Implements the "Next" tier of
[`docs/reviews/2026-10-05-ux-utility-review.md`](../../reviews/2026-10-05-ux-utility-review.md):
P3 (shareable Plot links), P4 (pass-to-pass difference), R4 (pre-flight before Start), R5 (live
clipping warning), D4 (sample labels / QR and scan-to-open) and D3 (Ask-DB export, copy SQL and
history). Delete this plan once the batch has shipped (see `docs/superpowers/README.md`).

**Process.** As for the previous batch: four Sonnet implementation streams in their own
worktrees, then an Opus `/simplify` pass and a high-effort Opus review over the merged result,
fixes, re-review. Workers commit after each item and never push, merge or rebase. The
coordinator fast-forwards every new worktree to the plan commit before the worker starts (the
harness has created worktrees on a stale base before).

## Status

| Stream | Items | Worktree / branch | State |
|---|---|---|---|
| E — Plot links and difference | P3, P4 | — | not started |
| F — Record pre-flight and clipping | R4, R5 | — | not started |
| G — Sample labels and QR | D4 | — | not started |
| H — Ask-DB export and history | D3 | — | not started |
| /simplify (Opus) | all | — | not started |
| /code-review high (Opus) | all | — | not started |

## E. Plot links and pass-to-pass difference — P3, P4

Files: `packages/force-plotting/src/**` (mainly `ForceDashboard.vue`, `compare.ts`, a new
`viewState.ts`), its tests, the Plot-dashboard wiki page, and the Directus and web hosts only
where the route has to accept the query (`core/extensions/d1-force-dashboard`,
`apps/force-app/web/src` plot route).

- **P3 — Shareable view link.** Serialise a compact view state into the route query: operation,
  mode, axes, zoom window, crop preview, compare set, FRM view (2D/3D, Z series), colour-scale
  lock. Parse defensively (unknown or bad values fall back to defaults; never throw). Write it
  back with `router.replace` debounced, so the address bar is always shareable without spamming
  history. Add a "Copy link" button. Works in both hosts (standalone `/plot/...` and the Directus
  module). Unit-test the serialiser round trip and the bad-input fallbacks.
- **P4 — Difference vs reference pass.** `alignAndDiff` (`compare.ts:44`) is exported but unused.
  Add a "Difference vs reference" option to Compare: the user marks one compare chip as reference
  and the chart shows (current − reference) per revolution for the selected axis, with a
  mean/RMS delta readout. Use the per-revolution data the working set already holds; no new
  fetches if avoidable. Unit-test the alignment on synthetic passes of different length.

## F. Record pre-flight and live clipping — R4, R5

Files: `apps/force-app/web/src/record/**` (workspace, RecordPage, panels), and
`apps/force-app/backend/app/**` for the live clipping flag (acquisition loop and the live frame
schema), their tests, `docs/wiki/force-app/recording.md`. Load `force-app-conventions` and use
the `force-scaffold` skill for the backend-to-web live field.

- **R4 — Pre-flight before Start.** A compact checklist row above Start: Sample set, signed in
  or offline session noted, amp connected and in MEASURE (when a LabAmp is configured), tacho
  seen (hardware source), disk runway, channel config valid. Each failing item has a "Show me"
  using the existing `spotlight`. Missing Sample is a warning with "Start anyway" (offline cuts
  can be linked later), not a hard block; existing hard blocks stay as they are.
- **R5 — Live clipping / rail warning.** The backend marks a channel as near full scale during
  acquisition (same threshold logic `finalize.py` uses for `channels_ranging`, applied per live
  block) and streams the flag with the live frame. The Record page shows a red badge on that
  channel's tile and a one-time banner per cut ("Ch3 railed: re-range before the next cut").
  Backend unit test with a synthetic railed block; web test for the banner once per cut.
- Validate with the `force-app-verify` skill (sim NI-DAQ, mock amp) if feasible.

## G. Sample labels and QR — D4

Files: `core/extensions/d1-report/**` (label route next to the existing PDF/QR code), a bulk
action from the samples list (a small extension or a `d1-home` link), a scan-to-open route, the
database wiki page. No schema change expected.

- Printable label sheet for one or many samples (`/d1-report/label?ids=...`): sample code, QR
  linking to the record, material, date. A4 sheet of standard label sizes (e.g. 63.5 × 38.1 mm,
  21 per sheet) and a single 50 × 25 mm label option.
- "Print labels for selected" from the samples list.
- The QR opens a phone-friendly record view (scan-to-open). Reuse the report's auth model; do not
  make sample data public.

## H. Ask-DB export and history — D3

Files: `core/extensions/d1-ask-db/**`, its docs. No plugin change expected.

- Per answer: Download CSV, Copy SQL.
- History: the last N questions per browser (localStorage), shown on the empty chat under the
  example chips, with "Run again". "Save question" pins one.
- Feedback (thumbs up/down) is out of scope until there is a place to store it (owner decision);
  note it in the doc.

## Commit trailers

```
Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01XPnGB1Ei8ENvWMdAxmthpu
```
