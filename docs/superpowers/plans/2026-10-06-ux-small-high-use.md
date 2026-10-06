# UX small, high-use items — 2026-10-06

Implements the "smaller, high-use" items from the progress checklist in
[`docs/reviews/2026-10-05-ux-utility-review.md`](../../reviews/2026-10-05-ux-utility-review.md):
R6 (alarms), R10 (Record keyboard shortcuts), R11 ("Restart recorder"), R13 (release notes and
Help menu), P2 (chart image export), P11 (gesture help and units) and D12 (saved filters).
Delete this plan once the batch has shipped (see `docs/superpowers/README.md`).

**Process.** Same as the previous two batches: four Sonnet implementation streams in their own
worktrees (each first fast-forwarded to the plan commit), commits after each item, no pushes by
workers. Then an Opus `/simplify` pass, a high-effort Opus review, fixes, an Opus re-review of the
fixes, local CI (`pre-commit` included), PR, CI green, merge.

## Status

| Stream | Items | Worktree / branch | State |
|---|---|---|---|
| I — Record alarms and shortcuts | R6, R10 | — | not started |
| J — Desktop shell | R11, R13 | — | not started |
| K — Plot export and help | P2, P11 | — | not started |
| L — Directus saved filters | D12 | — | not started |
| /simplify (Opus) | all | — | not started |
| /code-review high (Opus) | all | — | not started |

## I. Record alarms and shortcuts — R6, R10

Files: `apps/force-app/web/src/record/**` (`alarms.ts`, `RecordPage.vue`, workspace),
`apps/force-app/web/src/settings/AlarmsSettings.vue`, tests, `docs/wiki/force-app/recording.md`
and the settings wiki page.

- **R6 — Alarms.** `alarms.ts` latches once at a single threshold on the running peak.
  - An early-warning level (default 80 % of the force limit, configurable): an amber, non-modal
    banner, no tone.
  - An optional "Stop the recording when the force alarm trips" setting (off by default).
  - The alarm overlay gets `role="alert"` and `aria-live`; the disk banners `role="status"`.
  - Tone volume is a setting (default unchanged), instead of always forcing the system volume to
    maximum. Keep the tone's existing behaviour when the setting is absent.
  - Alarms stay Record-mode only (never Replay/Playback), as today.
- **R10 — Keyboard shortcuts on Record.** Start (Ctrl/Cmd+Enter), Stop (Ctrl/Cmd+.), acknowledge
  alarm (A while an alarm is showing), New (Ctrl/Cmd+N after a cut is done), Enter confirms the
  save dialog's primary action. Never Space or Esc for Start/Stop. Ignore keys while typing in an
  input/textarea/select (except the save dialog's Enter). A "Keyboard shortcuts" hint (a `?` button
  or a line under Start) lists them. Start via shortcut goes through exactly the same gates as the
  button (pre-flight, "Start anyway", alarm test, disk prompt).

## J. Desktop shell — R11, R13

Files: `apps/force-app/desktop/src/**` (`sidecar.ts`, `menu.ts`, `updater.ts`, `preload.ts`, main
IPC), its tests, `apps/force-app/web/src/electronBridge.d.ts`,
`apps/force-app/web/src/settings/ConnectivitySettings.vue`, docs (`docs/force-app-operations.md`,
`docs/wiki/force-app/` troubleshooting/settings pages).

- **R11 — "Restart recorder".** When `window.forceApp` exists, the Doctor's "recorder down" advice
  shows a "Restart recorder" button that calls a new IPC (`sidecar:restart`) which stops and
  respawns the backend through the existing sidecar supervisor, then the page re-checks health.
  Keep the uvicorn command text for browser/dev builds only. Refuse a restart while a recording is
  in progress (ask the backend first; if it is unreachable, allow it).
- **R13 — Release notes and Help menu.** The "update downloaded" dialog shows the release notes
  `electron-updater` provides (`info.releaseNotes`, string or array; render as plain text, trimmed
  to a sensible length with "full notes in About"). Help menu: Check for updates, Report a bug
  (navigates the window to the Report a Bug screen), Open captures folder (existing `revealPath`),
  plus the existing links. Add keyboard accelerators where conventional.

## K. Plot export and help — P2, P11

Files: `packages/force-plotting/src/**` (`ForceChart.vue`, `ContextMenu.vue`, `frmExport.ts`,
`ForceDashboard.vue`, `InfoTip.vue`), tests, `docs/wiki/force-app/plot-dashboard.md`.

- **P2 — Chart image export.** "Save chart as PNG" and "Save chart as SVG" in the signal charts'
  right-click menu. The export carries a title (operation tag, axis, mode), axis titles with units,
  the crop band and the compare legend, styled for reports (light background), using the framing
  conventions of `frmExport.ts` and the shared `downloadBlob`. Unit-test the SVG builder.
- **P11 — Help and units.** A `?` button on the Plot dashboard opens an overlay listing the
  gestures (right-click menus, drag crop handles, rectangular zoom, map↔chart linking, compare
  chips, Copy link). Every chart has a y-axis title with a unit (no `"amp"` fallback reaching the
  screen; pick the right unit from the series), and the stats tables show units in headers. Keep
  `InfoTip`/`diagHelp` styling.

## L. Directus saved filters — D12

Files: one migration in `db/migrations/` (Directus metadata, use the `db-migration` skill and
then `migration-review`), the config script that already seeds bookmarks
(`scripts/configure_directus.sql`, "Global bookmarks" section ~205) so a re-run keeps them, the
database wiki page.

- Global bookmarks (`directus_presets` with `bookmark` set, `user`/`role` NULL) for:
  - Operations: "My operations" (owner = `$CURRENT_USER`, if the operations collection has an
    owner field; check), "This week's FAST runs", "Missing outcome".
  - Tests: "Failed", "Needs analysis" (whatever status values the schema really has; check the
    CHECK constraints).
  - Samples: "My samples", "No location".
- Use filters that Directus 11 supports (`$CURRENT_USER`, `$NOW(-7 days)`). Idempotent inserts
  (`WHERE NOT EXISTS` on collection + bookmark name), exact-match deletes on down. Keep the script
  and the migration in step (the script must not delete them on re-run).

## Commit trailers

```
Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01XPnGB1Ei8ENvWMdAxmthpu
```
