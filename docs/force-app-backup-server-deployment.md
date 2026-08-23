# Deploying the force-app live-backup server on d1-server

**Written:** 2026-08-23, from a session on the acquisition PC.
**For:** whoever brings the backup service up on `d1-server`.

The acquisition PC has no running Docker daemon, so the service was built and wired but never
started against the real stack. Everything below is the remaining work, plus what was verified
here so you know what you can trust.

## What live backup is for

During a recording the acquisition backend tails `raw.d1raw` and streams it to this server in
~4 MB chunks. If the acquisition machine loses its disk, its power, or the recording process, the
raw capture can be pulled back from the server and finalized into a normal `.mat` + `live_cache`.
It is a crash safety net with hours-scale retention, **not** an archive — the archive path is
still the Directus upload.

## Deploy

```bash
# on d1-server, in the repo root
docker compose up -d backup-server proxy
curl https://d1-server.tail54eeb6.ts.net/backup-ingest/health
```

Expect `{"ok": true, "storage_path": "/data", ...}`.

Then in the app: **Settings > Live Backup**, tick Enable, set the server URL to
`https://d1-server.tail54eeb6.ts.net/backup-ingest`, Test connection, Save.

Retention defaults to 12 h and is set by `BACKUP_RETENTION_HOURS` in `.env`. Raw captures are
multi-GB; the named `backup-raw` volume is what keeps them across a container recreate, so do not
replace it with a bind mount into the container's own filesystem.

### Validate the proxy config

The Caddyfile change could not be checked with a real Caddy binary here:

```bash
docker run --rm -v "$PWD/infra/caddy/Caddyfile:/etc/caddy/Caddyfile:ro" \
  caddy:2-alpine caddy validate --config /etc/caddy/Caddyfile
```

## End-to-end check on the rig

1. Enable backup, start a recording, and watch the topbar backup chip reach 100 %.
2. `GET /backup-ingest/sessions` should list the session while it is still recording.
3. Stop the recording as normal.
4. **Settings > Live Backup > Restore** that session, then open it from **Settings > Local
   Captures** or the Plot tab and confirm the trace matches what was recorded.

A worthwhile extra: pull the network cable (or stop the container) mid-recording and plug it back
in. The recording must continue unaffected locally, the chip should show `paused` then resume, and
the restored file must still be byte-identical. That path is covered by automated tests but has
never been exercised against real hardware and a real network.

## Security posture — read before exposing anything

The backup server has **no authentication at all**: anyone who can reach it can list, download or
delete any stored capture. That is deliberate and consistent with `/recorder` and `/octrees`, which
are equally unauthenticated — the whole Caddy instance is reachable only over Tailscale, and
ADR-0010 already makes tailnet privacy load-bearing (the Electron installer is unsigned, and its
update feed is trusted purely because the transport is private).

Two consequences:

- The service is intentionally **not** published on a host port in `docker-compose.yml`. Reaching
  it only through Caddy keeps it behind the single tailnet-only TLS entry point. Do not add a
  `ports:` mapping for 8210.
- If this host ever becomes publicly reachable, this route needs real auth before that happens.

## What was verified here (and what wasn't)

Verified on the acquisition PC:

- The full round trip — real recorder streaming to the real server, then download + finalize —
  produces a **byte-identical** raw file and the same sample count, rate and per-axis peaks
  (`apps/force-app/backend/tests/test_backup_e2e.py`).
- Resume after a mid-stream outage, and the dropped-acknowledgement case that the `X-Offset`
  dedup exists for. That one was checked by disabling the server's offset handling and confirming
  the restored file comes back corrupted (616032 bytes against 480032), so the test genuinely
  fails when the protection is removed.
- An unreachable backup server leaves the local recording completely unaffected.
- The `/backup-ingest` prefix-stripping matches the client's URL construction, checked with a
  `handle_path` stand-in in front of the real server.
- `docker compose config` parses.

Not verified — this is the gap:

- The container has never been built or run (`docker build` needs a daemon).
- The Caddyfile has never been parsed by Caddy.
- No real recording has ever been streamed over Tailscale to a real server.

## Where the backend keeps its settings

`storage_config.json` (which drive recordings go to) and `backup_config.json` live in
`%LOCALAPPDATA%\force-app` — a per-user writable location, overridable with `FORCE_APP_CONFIG_DIR`.
Logs are in `logs/` beside them, overridable with `FORCE_APP_LOG_DIR`, which the Electron main
process points at its own `userData`.

They used to sit inside the package. In an installed build that resolves under the install
directory (Program Files by default), which a standard user cannot write to, and
`POST /storage/config` swallowed the resulting `OSError` — so choosing a capture drive appeared to
work, applied to the running process, and silently reverted on the next launch. Both files are now
read with a fallback to the old location, so an existing install keeps its configured drive and the
next save migrates it. If the settings genuinely cannot be written, the response now says so
(`persisted: false` plus a warning the Settings page displays) instead of reporting success.

Covered by `apps/force-app/backend/tests/test_config_location.py`.
