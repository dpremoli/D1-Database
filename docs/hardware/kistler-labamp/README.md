# Kistler LabAmp (5167A8x / STAR-LabAmp) — REST API reference

Vendor documentation for the Kistler charge amplifier used in the force-capture rig, kept here for
the standalone force app's recording backend (Phase 2 slice 2c: LabAmp control + settings) and any
future hardware work. The lab unit is a **Kistler 5167A81 "STAR-LabAmp"**.

## Files
- **`API_documentation_5167A8x.html`** — the device's full concept/parameter manual: the parameter
  tree (`/sensor/N/…`, charge/sensitivity/range/filters), Signal Event Monitor (per-channel
  threshold-1/threshold-2), DAQ streaming protocol, Data Recorder, clock/network settings.
- **`TCPIP_RESTAPI_Communication_V2.0.pdf`** — how to frame the raw HTTP requests to the REST API
  (headers, `Content-Length`, the `{"result":0,"data":{…}}` response envelope), with a worked
  `/api/$/signal/get` example.
- **`LabAmp_network_configuration_guide.pdf`** — Ethernet/IP setup (direct link-local/static vs
  DHCP). Explains why the amp sits on a link-local address reachable only from the acquisition PC.

## REST at a glance
- Transport: `POST http://<ampIP>/api/…` with a JSON body; response `{"result":0,"data":{…}}`
  (`result == 0` = success). The lab amp IP is link-local (the MATLAB app used `169.254.143.59`;
  the TCP/IP doc example uses `192.168.103.10`) — **reachable only from the acquisition PC**, so the
  force-app *backend* (not the browser) talks to it.
- Endpoints used by the app (mirrors the MATLAB `%% Kistler DAQ API calls` section):
  - `POST /api/$/operationMode/set`  body `{"mode":"MEASURE"|"RESET"}` — set amp mode
    (RESET→MEASURE on record start, RESET on stop).
  - `POST /api/param/export` — full signed configuration blob (saved as `AmpSettings`).
  - `POST /api/param/get`  body `{"params":["/sensor/1/name","/sensor/1/serialNumber",
    "/sensor/1/physicalQuantity","/sensor/1/sensitivity","/sensor/1/range", …×N]}` — read params;
    used to build the per-sensor table.
  - `POST /api/param/set` — set params (sensitivity, range, …).
  - `POST /api/$/signal/get`  body `{"type":"SENSOR","channels":[1,…]}` — live values
    (`ampl`/`max`/`min`/`rms` per channel).
- Alarms: the amp offers a hardware **Signal Event Monitor** (threshold-1/threshold-2 per channel,
  configured via `/api/param`). The app's slice 2e implements **software** force/RPM alarms on the
  live stream (matching the MATLAB app); the hardware monitor is an optional future enhancement.

See `docs/superpowers/specs/2026-07-30-recording-2e-2c-alarms-labamp-design.md` for how the app uses
these.
