# Test data created during development/debugging

Running log of test data left behind by Claude while testing the force-app recorder + plotting
pipeline. Nothing here is auto-deleted — use this list to clean up manually when convenient.
Newest entries at the top of each table.

## Directus database rows

These are real rows in the shared Directus instance (`d1-server.tail54eeb6.ts.net`) and are the
highest-priority items to clean up, since they're visible to everyone, not just on this machine.

| Date | Collection | id / operation_id | Notes |
|---|---|---|---|
| 2026-08-09 | `manufacturing_operations` | `96a53bc9-8f2e-4008-ad84-235380a93f7b` | Sample "120-C45-MO-2025-04-07", sim recording, uploaded while verifying the `series`-envelope fix (post-fix — charts render correctly). Linked `machining_force_analysis` row + 2 Directus files (capture `20260809-012900-c9433a`). |
| 2026-08-09 | `manufacturing_operations` | `3fca1c6d-1900-4936-97fd-cba48b862f0d` | Sample "120-C45-MO-2025-04-07", sim recording, uploaded while first reproducing the "no data" bug (pre-fix — charts showed "no data", now fixed in place; the row itself is still valid/complete). Linked `machining_force_analysis` row `eed74986-8bad-4cf2-bb2a-e423f540a4d8` + 2 Directus files (capture `20260809-012154-c266a9`). |
| 2026-08-09 | `directus_files` | `5b505b22-7086-41e2-b804-9af86022ba2c`, `97cf4078-78f5-4932-ba29-3bf2829864cd` | `.mat` + `live_cache.bin` for operation `3fca1c6d…` above. |
| 2026-08-09 | `directus_files` | (2 files, ids not recorded) | `.mat` + `live_cache.bin` for operation `96a53bc9…` above. |

No new `samples` rows were created — both test uploads reused the existing sample
"120-C45-MO-2025-04-07 · Steel Orthog Test Sample".

## Local recorder captures (`D:\force-app-captures`)

Local disk only, not shared — lower priority, but listed for completeness. `GET /captures` on the
recorder backend (`localhost:8200`) is the live source of truth if this drifts out of date.
As of 2026-08-09 there are 33 capture directories total; the ones below are from this debugging
session (sample rate/source/duration vary a lot — most are short synthetic sim recordings, a few
are longer perf/soak tests from earlier sessions).

| Capture ID | Sample name | Duration (s) | Context |
|---|---|---|---|
| `20260809-020346-2c5d7a` | REPLAY-TEST | 3.0 | Backend-only `/record/start_replay` test (curl), replaying capture `20260809-012154-c266a9`'s uploaded live_cache.bin at 5×, verifying the replay pipeline itself works. Not saved/uploaded — no DB rows created. |
| `20260809-012900-c9433a` | SIM-CUT | 3.0 | Uploaded → operation `96a53bc9…` |
| `20260809-012154-c266a9` | SIM-CUT | 3.0 | Uploaded → operation `3fca1c6d…` |
| `20260809-011933-16adf7` | SIM-CUT | 3.0 | Discarded (not saved) |
| `20260809-011413-9fcf02` | SIM-CUT | 52.9 | Discarded — source-selection race bug reproduction (recorded via `nidaq` instead of `sim`) |
| `20260809-011116-d835c5` | SIM-CUT | 14.7 | Discarded — same source-selection race bug |
| `20260809-010214-ca7b14` | SIM-CUT | 23.5 | Saved locally only (`.mat`); DB upload attempt failed on the `manufacturing_operations_has_sample` constraint (no sample selected) — this is what surfaced the real 500 error |
| `20260809-005054-175e53` | WATCHERTEST | 3.0 | Backend disk-watcher smoke test |
| `20260809-003447-16f6de` | SIM-CUT | 4.1 | FRM white-screen bug repro |
| `20260809-002435-b3018f` | SIM-CUT | 3.4 | FRM white-screen bug repro |
| `20260809-002202-4180d6` | SIM-CUT | 7.0 | FRM white-screen bug repro |
| `20260806-*` (6 captures) | SIM-CUT | 8–72s | Disk-space/backup + LabAmp session work |
| `20260805-*` (14 captures) | SIM-CUT / TEST / PERF* / BIG | 2–1673s | Recorder start/stop latency profiling, save-dialog work |

## Convention going forward

Whenever a test/debugging session creates a recording, DB row, or uploaded file that isn't
obviously transient (i.e. it could confuse someone else looking at real data later), add a row
above at the time it's created, not retroactively.
