# Hardware Integration Test Plan — Force-App Recording

**Date:** 2026-08-04
**Target PC:** Acquisition workstation (NI-DAQ + Kistler LabAmp + Hall sensor)
**Constraint:** Hall-effect sensor is attached but nothing is rotating — tacho signal will be faked

## Prerequisites

### 1. Spin up the stack (Docker)

The acquisition PC has Docker but no running containers. We need at minimum Postgres + Directus + Caddy (proxy). The heavy-data, analysis, and LLM services are not needed for recording tests.

```powershell
# Clone / pull the repo, then:
copy .env.example .env
# Edit .env: set real passwords, DIRECTUS_ADMIN_PASSWORD, etc.

# Start the minimal stack (skip LLM profile, skip SMB volume):
docker compose up -d postgres directus proxy redis minio filter-service
```

Wait for Directus healthcheck to pass (~60s first boot while it runs its own migrations), then apply our schema migrations:

```powershell
# Install dbmate if not present
dbmate --no-dump-schema up
psql $DATABASE_URL -f db/seeds/001_reference_data.sql
```

### 2. Start the recording backend

```powershell
cd apps/force-app/backend
pip install -e ".[nidaq]"    # includes nidaqmx
uvicorn app.main:app --host 0.0.0.0 --port 8200 --reload
```

Verify: `GET http://localhost:8200/health` returns 200.

### 3. Start the frontend dev server

```powershell
cd apps/force-app/web
npm install
npm run dev    # serves on :5180
```

Verify: browser opens `http://localhost:5180`, login page renders.

### 4. Verify NI-DAQ runtime

```python
python -c "import nidaqmx; print([d.name for d in nidaqmx.system.System.local().devices])"
```

This must list the cDAQ chassis and its modules. If NI-MAX simulated devices are configured, those appear too.

---

## Test Matrix

### Phase A — Smoke (Simulated Source, No Hardware)

These tests work on any PC and validate the full pipeline before touching hardware.

| # | Test | Steps | Expected |
|---|------|-------|----------|
| A1 | Sim recording end-to-end | Select "Simulated" source, set RPM=1200, feed=0.05, diam=80, duration=8s. Click Start. | Live force plot scrolls. RPM gauge shows ~1200. FFT panel shows frequency content. FRM spiral builds. After 8s, state transitions to "done". |
| A2 | Captured artifacts | After A1 completes, check `captures/` dir. | `raw.d1raw`, `capture.mat`, `live_cache.bin`, `summary.json` all present. `.mat` loadable in MATLAB. |
| A3 | FFT modes | During a sim run, switch ForcePanel between Force / FFT / Power / Spectrogram / Waterfall. | Each mode renders without error. FFT shows tooth-passing peak at `RPM*4/60` Hz. |
| A4 | FRM axis selector | During a sim run, switch FRM panel between Fx / Fy / Fz. | Cloud colour updates per axis. Spiral geometry unchanged. |
| A5 | Live panel pop-out | Click pop-out on the Force panel during recording. | New browser tab opens at `/live/force` with the same live plot. |
| A6 | Replay source | Select "Replay", search for a known cut by pass code, pick it, set speed 5×. Start. | Replays the cached data at 5× speed. Live plots render. FRM builds. |
| A7 | Drift compensation | Enable "Drift compensation" checkbox during a sim run. | summary.json shows `drift_comp: true`. `.mat` data has linear baseline removed. |
| A8 | Cut detection | Run with default settings (adaptive threshold). | `cutstart` control message fires ~5% into the run. FRM begins at cut start (not at t=0). summary.json shows cut_start/cut_end times. |

### Phase B — NI-DAQ Hardware (Real Channels, No Cutting)

These tests validate the NI-DAQ source reads real voltage from the chassis. There is no workpiece or cutting, so forces will be near-zero noise + whatever EM pickup the dyno sees.

| # | Test | Steps | Expected |
|---|------|-------|----------|
| B1 | Device enumeration | `GET /nidaq/devices` | Returns the real cDAQ chassis, its slots, and module types. Card catalogue matches the installed C-series modules. |
| B2 | Channel auto-assign | `GET /nidaq/channels/autoassign` | Returns 9 channels (8 force + 1 tacho) mapped to real physical ports (e.g. `cDAQ1Mod1/ai0`). |
| B3 | NI-DAQ recording (noise floor) | Select "NI-DAQ" source, set channels to the real physical strings, duration 5s. Start. | Recording starts and completes. Live force plot shows low-amplitude noise (~LSB noise of the ADC). No errors or overruns. |
| B4 | Sample rate validation | Record at 25 kHz for 5s. Check `summary.json`. | `total_samples` ≈ 125,000 (within 1%). Rate matches configured 25,000 Hz. |
| B5 | Multi-rate test | Record at 10 kHz and 50 kHz. | Both complete without overrun. `summary.json` sample counts scale correctly. |
| B6 | Channel count mismatch | Set `nidaq_channels` to 8 strings (missing tacho). Try to start. | Backend rejects with 422: "expected 9 NI-DAQ channels, got 8". |

### Phase C — LabAmp Integration

| # | Test | Steps | Expected |
|---|------|-------|----------|
| C1 | Mock mode health | `GET /labamp/status` with `LABAMP_MODE=mock`. | Returns connected=true, mode="mock", 8 channels. |
| C2 | Switch to real mode | `PATCH /labamp/config` with `mode: "real"`. Then `GET /labamp/ping`. | If LabAmp is powered on and link-local reachable: ping succeeds. If not: clear error "LabAmp unreachable at 169.254.x.x". |
| C3 | Sensor table | `GET /labamp/sensors` (real mode, amp powered). | Returns 8 channels with real sensitivity values from the Kistler dynamometer's calibration. |
| C4 | Mode roundtrip | `POST /labamp/mode` with `{"mode": "MEASURE"}`, then `{"mode": "RESET"}`. | Mode switches confirmed by read-back. |
| C5 | Auto-range (mock) | `POST /labamp/autorange` with mock signal peaks. | Returns recommended ranges per channel with resolution (N/LSB), bits used, and utilisation %. |
| C6 | Auto-range (real) | With amp in MEASURE mode, `POST /labamp/autorange` using real peak readings. | Ranges computed from actual signal. `apply` endpoint sets them on the amp. |

### Phase D — Tacho / Hall Sensor (Faked Signal)

The Hall-effect sensor is wired to the NI-DAQ but nothing is rotating. We need to inject a known signal to validate the RPM derivation and FRM path.

**Approach: NI-MAX simulated counter output or function generator**

Option 1 — If a function generator or NI counter-output module is available:
- Generate a 20 Hz square wave (= 1200 RPM at 1 PPR) on a BNC cable
- Connect it to the tacho input (cDAQ1Mod3/ai0 or wherever the Hall sensor is wired)
- The NidaqSource reads it as channel 9

Option 2 — Software-only fallback (SimSource with NI-DAQ force channels):
- Use SimSource but override its force channels with the real NI-DAQ readings via a hybrid source
- This tests the full pipeline but not the real tacho→RPM path

Option 3 — Record with real NI-DAQ, post-process inject tacho:
- Record 9 channels with the real NI-DAQ (tacho channel will be noise)
- Use `ReplaySource` to replay the raw file with a synthesised tacho

| # | Test | Steps | Expected |
|---|------|-------|----------|
| D1 | Tacho from function generator | Inject 20 Hz square wave (0-5V) into tacho channel. Record 5s with NI-DAQ source. | RPM gauge reads ~1200 ± jitter. `summary.json` shows `mean_rpm` ≈ 1200. |
| D2 | Variable RPM | Sweep function generator from 10 Hz to 40 Hz (600–2400 RPM). Record 10s. | RPM gauge tracks the sweep. `live_cache.bin` RPM column shows the ramp. |
| D3 | PPR > 1 | Set PPR=4 in config. Inject 80 Hz (= 1200 RPM × 4 PPR). Record. | RPM still reads ~1200 (frequency / PPR). |
| D4 | FRM with faked tacho | Run D1 with the force channels reading real dyno noise. | FRM spiral builds using the injected RPM. Geometry should be a tight cluster (no real cutting force → flat FRM at the noise floor). |
| D5 | RPM fallback (no tacho) | Record with tacho channel disconnected (floating). | `rpm_from_tacho` falls back to 0 RPM. FRM does not accumulate. RPM gauge shows 0. No crash. |

### Phase E — Full Recording Features

These tests exercise every feature in the recording workspace, ideally with NI-DAQ source + faked tacho.

| # | Test | Steps | Expected |
|---|------|-------|----------|
| E1 | Workspace layout persistence | Drag panels to new positions. Close and reopen the browser. | Layout restored from localStorage (v3 key). |
| E2 | Safety alarms | Set force alarm threshold to 10N. Start NI-DAQ recording (noise is ~0.1N). Verify no alarm. Then lower threshold to 0.01N. | Alarm triggers: red overlay, audio tone (if speakers attached), latching state. |
| E3 | Sub-channel selection | In ForcePanel, switch from summed axes (Fx/Fy/Fz) to individual sub-channels (Fx1, Fx2, etc.). | Live plot shows 8 individual traces instead of 3 summed. FFT shows per-sub-channel spectra. |
| E4 | Spectrogram mode | Select single channel (Fz), switch to Spectrogram mode. Record 10s. | Heatmap builds progressively. Frequency axis 0–fs/2. Time axis scrolls. |
| E5 | Waterfall mode | Switch to Waterfall during recording. | Stacked spectra visible, 44 recent frames, newest at front. |
| E6 | New run cycle | Complete a recording, click "New Run", start another. | Second capture writes to a new timestamped directory. Previous capture remains intact. |
| E7 | Metadata panel | Fill in sample, operator, machine, insert, edge, tool, DoC, coolant fields before recording. | All metadata appears in `summary.json` and `.mat` file's metadata struct. |
| E8 | Converging auto-range | Enable "Converging auto-range" checkbox. Run two consecutive cuts. | `summary.json` for cut 2 shows `channels_ranging` updated from cut 1's peak data. |

### Phase F — Directus Write-Back (2-Way Sync)

Requires Directus to be running and accessible. Tests the offline queue and live sync.

| # | Test | Steps | Expected |
|---|------|-------|----------|
| F1 | Online log to Directus | Fill metadata (sample, operator, machine). Complete a sim recording. Click "Log run to database". | New `manufacturing_operations` row created in Directus. Verify via Directus admin UI or `GET /items/manufacturing_operations`. |
| F2 | Offline queue | Stop the Directus container (`docker compose stop directus`). Complete a recording and log it. | Run queued in localStorage. Sync chip shows "1 queued". |
| F3 | Reconnect flush | Restart Directus (`docker compose start directus`). Wait for online event or 15s interval. | Queued run flushed to Directus. Sync chip clears. Row visible in admin UI. |
| F4 | Validation rejection | Log a run with an invalid sample_id (nonexistent UUID). | 4xx error surfaced in UI. Item stays in queue for manual fix. |

### Phase G — Saved File Validation

After completing several recordings (mix of sim, NI-DAQ, replay):

| # | Test | Steps | Expected |
|---|------|-------|----------|
| G1 | .mat MATLAB load | Open `capture.mat` in MATLAB. | `DATA` is [N×10] float64. `VariableNames` matches `{'Time','Fx1','Fx2','Fy1','Fy2','Fz1','Fz2','Fz3','Fz4','Tacho'}`. Metadata struct present with sample_name, rpm, feed, etc. |
| G2 | .mat process_force.m | Run `process_force.m` on the captured .mat. | FRM plot renders. Force/time plots render. No dimension mismatches. |
| G3 | live_cache.bin D1LC | Open in the plotting UI (not recording UI). | Force time-series, FRM cloud all render from the saved live_cache. |
| G4 | raw.d1raw integrity | Read header: magic=`D1RW`, version=1, n_cols=10, rate=25000. Memory-map and verify shape [N, 10]. | Header valid. Data shape matches expected sample count. |
| G5 | summary.json completeness | Inspect the JSON. | Contains: peaks (per-axis), cut_window, channels config, metadata, file paths, duration, total_samples, mean_rpm. |

---

## Environment Checklist

Before starting on the acquisition PC:

- [ ] Docker Desktop running, compose stack up (postgres, directus, proxy, filter-service)
- [ ] `.env` configured with real passwords
- [ ] `dbmate up` + seeds applied
- [ ] NI-DAQmx runtime installed (NI-MAX sees the chassis)
- [ ] Python 3.11+ with `nidaqmx` package
- [ ] Recording backend running on :8200
- [ ] Frontend dev server running on :5180
- [ ] Function generator available (or NI-MAX simulated AO) for tacho faking
- [ ] LabAmp powered on and link-local reachable (if testing Phase C real mode)
- [ ] At least one physical_sample and manufacturing_method seeded in Directus (for write-back tests)

## Execution Order

1. **Phase A** (sim smoke) — validates the full pipeline with no hardware dependencies
2. **Phase B** (NI-DAQ) — validates real channel acquisition
3. **Phase D** (tacho faking) — validates RPM + FRM with injected signal
4. **Phase C** (LabAmp) — validates amplifier communication
5. **Phase E** (features) — exercises all UI features with real data flowing
6. **Phase G** (file validation) — verifies saved artifacts
7. **Phase F** (Directus sync) — validates 2-way write-back

Phases A→B→D are the critical path. C and E–G can run in any order after D.
