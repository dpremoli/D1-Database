# force-app — operations

Running, deploying and troubleshooting the machining force-capture app: the Electron desktop
shell, its recorder backend, and the live-backup server that protects a recording in flight.

Design rationale lives elsewhere and is not repeated here — see
[ADR-0010](adr/0010-force-app-extraction-and-electron-packaging.md) for the extraction and
packaging decisions, and `superpowers/specs/` for the per-feature design documents.

## The pieces

| Piece | Where it runs | What it is |
|---|---|---|
| Desktop shell | acquisition PC | Electron app, `apps/force-app/desktop` |
| Recorder backend | acquisition PC | FastAPI sidecar spawned by the shell, `apps/force-app/backend`. Needs the NI-DAQ hardware, so it is never containerised |
| Web UI | served by the shell | Vue SPA, `apps/force-app/web`. Also served by Caddy at `/app/` for browser use |
| Backup server | `d1-server` | Receives streamed raw captures, `apps/force-app/backup-server` |
| Directus + Postgres | `d1-server` | The archive the finished captures upload into |

## Running it in development

```powershell
npm install                              # repo root
npm run build:web:desktop
npm run build -w force-app-desktop
npm run dev -w force-app-desktop
```

The app should show a loading screen, spawn the sidecar from
`apps/force-app/backend/.venv`, and load the login page over `app://force/`.

To run the backend alone: `.venv\Scripts\python -m uvicorn app.main:app --host 127.0.0.1 --port 8200`.

## Where things are kept

| What | Where | Override |
|---|---|---|
| Recordings | the configured capture drive (Settings > General) | `FORCE_APP_CAPTURES` |
| `storage_config.json`, `backup_config.json` | `%LOCALAPPDATA%\force-app` | `FORCE_APP_CONFIG_DIR` |
| `backend.log` (+ 3 rotated) | `%LOCALAPPDATA%\force-app\logs`, or Electron's `userData\logs` when launched by the shell | `FORCE_APP_LOG_DIR` |
| LabAmp / NI-DAQ channel config | under the capture drive | — |

Settings must **not** live inside the package: under PyInstaller that resolves into the install
directory (Program Files by default), which a standard user cannot write to. That used to be the
case, and the write failure was swallowed — choosing a capture drive appeared to work and silently
reverted on restart. Both files are now read with a fallback to the old location, so an existing
install keeps its configured drive and the next save migrates it. If they genuinely cannot be
written the app says so rather than reporting success. Logging degrades to stderr-only in the same
situation; it never blocks startup.

Logs are readable in-app at **Settings > Logs** (also **Help > View Logs**), with level filtering,
search and download. Local recordings are listed at **Settings > Local Captures**, which is also
the only way to delete a finished capture — nothing else in the app can, so they otherwise
accumulate forever.

## Deploying the live-backup server

During a recording the backend tails `raw.d1raw` and streams it to this server in ~4 MB chunks. If
the acquisition machine loses its disk, its power, or the recording process, the raw can be pulled
back and finalized into a normal `.mat` + `live_cache`. It is a crash safety net with hours-scale
retention, **not** an archive — the archive path is the Directus upload.

```bash
# on d1-server, in the repo root
docker compose up -d backup-server proxy
curl https://d1-server.tail54eeb6.ts.net/backup-ingest/health
```

Expect `{"ok": true, "storage_path": "/data", ...}`. Then in the app: **Settings > Live Backup**,
tick Enable, set the URL to `https://d1-server.tail54eeb6.ts.net/backup-ingest`, Test connection,
Save.

Retention defaults to 12 h (`BACKUP_RETENTION_HOURS` in `.env`). Raw captures are multi-GB; the
named `backup-raw` volume is what keeps them across a container recreate, so do not replace it with
a path inside the container's own filesystem.

Validate the proxy config after touching it:

```bash
docker run --rm -v "$PWD/infra/caddy/Caddyfile:/etc/caddy/Caddyfile:ro" \
  caddy:2-alpine caddy validate --config /etc/caddy/Caddyfile
```

### Security posture — read before exposing anything

The backup server has **no authentication at all**: anyone who can reach it can list, download or
delete any stored capture. That is deliberate and consistent with `/recorder` and `/octrees`, which
are equally unauthenticated — the whole Caddy instance is reachable only over Tailscale, and
ADR-0010 already makes tailnet privacy load-bearing (the installer is unsigned, and its update feed
is trusted purely because the transport is private).

So the service is intentionally **not** published on a host port in `docker-compose.yml`; reaching
it only through Caddy keeps it behind the single tailnet-only TLS entry point. Do not add a
`ports:` mapping for 8210. If this host ever becomes publicly reachable, this route needs real auth
first.

## Hardware checklist

Automated tests cover most of this (`apps/force-app/desktop/tests/`, and the backend suite), but
these need the rig and a human:

- [ ] NI-DAQ enumeration on Settings > NI-DAQ shows the **real** hardware, not the simulated
      chassis. `app/nidaq_enum.py` falls back to simulation when the driver or hardware is missing,
      so confirm it isn't doing that.
- [ ] A real NI-DAQ recording renders live force/FRM from actual channel data.
- [ ] Kill the backend mid-recording (`Stop-Process -Name force-app-backend`, or the `python.exe`
      running uvicorn in dev). The supervisor should restart it and route back to Record, where the
      recovery banner picks up the interrupted session.
- [ ] A second copy of the app focuses the running window instead of opening a second one.
- [ ] **Live backup end to end:** enable it, record, watch the topbar chip reach 100 %, stop, then
      restore that session from Settings > Live Backup and confirm the trace matches. Worth also
      pulling the network mid-recording: the recording must continue locally, the chip should show
      `paused` then resume, and the restored file must still be byte-identical.
- [ ] **A packaged install as a standard user.** `npm run package -w force-app-desktop`, install to
      the default Program Files location, then confirm the capture drive choice survives a restart
      and that logs still appear in Settings > Logs. This is the one scenario the config-location
      fix targets and it has not been exercised on a real install.
- [ ] Frozen backend picks up NI-DAQmx: `.\scripts\build_frozen.ps1`, run
      `.\dist\force-app-backend\force-app-backend.exe --port 8291`, then `POST /health/doctor` and
      confirm the `"NI-DAQ runtime"` finding is `"ok"`, not `"warn"`.

## Known quirks — don't chase these

- **Four backend tests fail on the acquisition PC** (`test_autorange.py` ×2, `test_labamp.py`,
  `test_nidaq_config.py`). They expect the simulated NI-DAQ/LabAmp fallback, and this machine has
  the real hardware. Pre-existing and unrelated to any change.
- **`electron-updater` finds nothing on launch** until a `force-app-v*` tag produces a Release and
  `publish-release.ps1` runs against the Caddy feed. Auto-update is dormant, not broken.
- **The installer is unsigned** by design for v1 (ADR-0010's open decisions), so SmartScreen warns.
- **`Cannot read properties of undefined (reading 'whenReady')`** on launch means something set
  `ELECTRON_RUN_AS_NODE=1` in the shell. Check `$env:ELECTRON_RUN_AS_NODE`.
- **The `build` and `nidaq` extras are optional** and only needed for the PyInstaller freeze.

## Testing

```powershell
cd apps\force-app\backend;      .venv\Scripts\pytest          # backend
cd apps\force-app\backup-server; ..\backend\.venv\Scripts\pytest   # backup server (own directory)
cd apps\force-app\web;          npm test                      # web unit
cd apps\force-app\desktop;      npm test                      # shell unit
cd apps\force-app\desktop;      npx playwright test           # e2e, drives the real app
```

The Playwright suite launches the real Electron app against the real backend and, for the
save-flow test, the real NI-DAQ source. It is self-cleaning: dev-mode launches share one `userData`
profile, so each test removes the fake auth token it seeds, and the save-flow test deletes the
capture it creates — otherwise every run litters the operator's capture drive.
