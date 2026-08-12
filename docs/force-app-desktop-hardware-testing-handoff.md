# Handoff: force-app desktop — hardware testing on the equipment machine

**Written:** 2026-08-12, from a session on `d1-server`.
**For:** the next Claude session, running on the machine physically wired to the NI-DAQ/LabAmp
hardware.

## Where things stand

`apps/force-app` has been packaged as an Electron desktop app (ADR-0010 steps 3-4). All 14
implementation-plan tasks are done, individually reviewed, and a final whole-branch review found
and fixed 3 Critical + 6 Important cross-task bugs (details in git history — search commit
messages on `main` around `2c2724b`/`6a544f7`/`0199657` if you need the reasoning). Everything is
merged to `main` and pushed to `origin/main`.

What's been verified, and where: on `d1-server` (no DAQ/LabAmp hardware there), sim-mode
recording, the Electron shell mechanics (window, sidecar spawn/health/restart, `app://force`
custom origin serving the real SPA bundle, single-instance lock), and a real Playwright e2e run —
all pass. **Nothing involving actual NI-DAQ/LabAmp hardware has been tested, because d1-server
doesn't have any.** That's the gap this note exists to close.

Also done on `d1-server` as part of this handoff: the live `.env` now has
`FORCE_APP_ORIGIN=http://localhost:5180,app://force`, and Directus + the filter-service were
recreated to pick it up — confirmed via `docker exec` that both containers now see `app://force`
in their CORS allow-list. **Login from the Electron app against the real Directus should work
now.** (The recorder backend's own CORS doesn't need a server-side deploy — `main.ts` passes
`RECORDER_CORS_ORIGINS=app://force` directly to the spawned sidecar process, so that part travels
with the code.)

## Relevant docs (read if you need the "why")

- Plan: `docs/superpowers/plans/2026-08-10-force-app-desktop-packaging.md`
- Design spec: `docs/superpowers/specs/2026-08-10-force-app-desktop-packaging-design.md`
- ADR: `docs/adr/0010-force-app-extraction-and-electron-packaging.md`

The SDD execution ledger was deleted after the final review passed clean (per the
subagent-driven-development skill's own convention — "the git history is the record now"). If you
need the blow-by-blow of every task's review/fix rounds, it's not preserved anywhere except this
conversation's history and the commit messages themselves; the commit messages are reasonably
descriptive.

## What to do here

1. `git pull` — get the latest `main`.
2. `npm install` at the repo root.
3. Confirm `apps/force-app/backend/.venv` still works (`.venv\Scripts\python -m uvicorn app.main:app --host 127.0.0.1 --port 8200` should start cleanly — Ctrl+C after confirming).
4. `npm run build:web:desktop` then `npm run build -w force-app-desktop`.
5. `npm run dev -w force-app-desktop` — the app should launch, show the loading screen, spawn the
   sidecar from the local venv, and load the real login page over `app://force/`.

**If Electron fails to launch with `Cannot read properties of undefined (reading 'whenReady')`:**
that means something is setting `ELECTRON_RUN_AS_NODE=1` in your shell — this was a sandboxing
quirk specific to the agent session that built this feature, not expected on a normal interactive
session, but check `$env:ELECTRON_RUN_AS_NODE` (PowerShell) if you hit it.

## Test checklist — this is the point of this session

- [ ] App launches and reaches the login page over `app://force/`.
- [ ] Log in against the real Directus succeeds (proves the CORS fix actually works end to end —
      this has never been exercised for real until now).
- [ ] NI-DAQ device enumeration on the Settings/NI-DAQ page shows the **real** hardware, not the
      simulated chassis (`apps/force-app/backend/app/nidaq_enum.py` falls back to simulation only
      when the real driver/hardware isn't found — confirm it isn't doing that here).
- [ ] Start a real NI-DAQ recording (not sim), confirm the live force/FRM plot renders from actual
      channel data.
- [ ] Mid-recording, kill the recorder backend process externally (Task Manager or
      `Stop-Process -Name force-app-backend` if testing the frozen exe, or the `python.exe`
      running uvicorn if testing dev mode) — confirm the app's supervisor restarts it and routes
      you back to the Record page, where the recovery banner picks up the interrupted session.
- [ ] Launch a second copy of the app while the first is still running — confirm it just focuses
      the existing window rather than opening two (single-instance lock,
      `apps/force-app/desktop/src/main.ts`).
- [ ] **Specifically verify the NI-DAQ packaging fix**, since it was made without real hardware to
      test against: on this machine (which has the real NI-DAQmx driver),
      `cd apps/force-app/backend; .venv\Scripts\Activate.ps1; pip install -e ".[dev,build,nidaq]"; .\scripts\build_frozen.ps1`,
      then run the frozen exe directly (`.\dist\force-app-backend\force-app-backend.exe --port 8291`)
      and hit `POST http://127.0.0.1:8291/health/doctor` — confirm the `"NI-DAQ runtime"` finding
      now reports `"status":"ok"`, not `"warn"`. If it still says `"warn"` despite the driver being
      installed, the `force-app-backend.spec` hidden-imports fix (`collect_submodules("nidaqmx")` +
      `copy_metadata("nidaqmx", recursive=True)`) needs more work — this is the one fix in the
      whole branch that was made blind, without a machine to verify it against.
- [ ] Optional but recommended: `npm run package -w force-app-desktop` and run the actual NSIS
      installer end to end (unsigned — you'll click through a SmartScreen warning).

## Known non-blockers, don't chase these

- `electron-updater` will check its feed on launch and find nothing (no `force-app-v*` tag has
  been pushed, so no GitHub Release exists, so `publish-release.ps1` hasn't been run against the
  Caddy feed on `d1-server` either). This is expected — auto-update is simply dormant until a real
  release happens.
- The installer is unsigned by design for v1 (see ADR-0010's open decisions) — the SmartScreen
  warning is expected, not a bug.
- If `apps/force-app/backend/.venv` doesn't have the `build` or `nidaq` extras installed yet,
  that's normal — they're optional and only needed for the PyInstaller-freeze checklist item.
