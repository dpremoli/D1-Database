"""FastAPI app for the local recording backend (slice 2a).

Single-session model (one acquisition rig per host): /record/start creates a session, /record/stop
finalizes it, WS /record/stream broadcasts D1LF live frames, and /captures/* serves the finished
artifacts (so the plotting UI can render the just-recorded live_cache.bin). CORS mirrors the
filter-service so the standalone SPA can reach it from its own origin.
"""
from __future__ import annotations

import asyncio
import json
import os
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, File, Form, HTTPException, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from starlette.concurrency import run_in_threadpool

from .config import RecordConfig
from .d1lc import read_d1lc_header
from .labamp import LabAmpClient, LabAmpError, MockLabAmp
from .labamp_autorange import effective_bits, recommend_ranges
from .session import RecordingSession
from .sources.replay import ReplaySource
from .sources.sim import SimSource
from .stream.broadcast import Broadcaster

CAPTURES_ROOT = os.environ.get(
    "FORCE_APP_CAPTURES", os.path.join(os.path.dirname(os.path.dirname(__file__)), "captures")
)
os.makedirs(CAPTURES_ROOT, exist_ok=True)

_broadcaster: Optional[Broadcaster] = None
_session: Optional[RecordingSession] = None

# ---- LabAmp (2c) config + instance ----
# The amp is link-local (reachable only from the acquisition PC) so the backend owns the HTTP
# conversation. Defaults to a mock (no hardware here); switch mode=real on the rig.
LABAMP_CONFIG_PATH = os.path.join(CAPTURES_ROOT, "labamp.json")


def _load_labamp_config() -> dict:
    cfg = {
        "base_url": os.environ.get("LABAMP_URL", "http://169.254.143.59"),
        "channels": int(os.environ.get("LABAMP_CHANNELS", "8")),
        "mode": os.environ.get("LABAMP_MODE", "mock"),  # "mock" | "real"
        "autorange_headroom": float(os.environ.get("LABAMP_AUTORANGE_HEADROOM", "1.5")),
        # We digitise the amp's ANALOG OUTPUT with the NI-DAQ, so the auto-range resolution/bits use
        # the NI-DAQ ADC bit depth + the analog full-scale voltage (set these for your rig).
        "nidaq_bits": int(os.environ.get("NIDAQ_BITS", "16")),
        # The amp's analog-output DAC is limited to 12-bit without the recording licence — this is
        # the bottleneck of the chain (effective bits = min(dac, nidaq)).
        "labamp_dac_bits": int(os.environ.get("LABAMP_DAC_BITS", "12")),
        "analog_fullscale_v": float(os.environ.get("ANALOG_FULLSCALE_V", "10.0")),
    }
    try:
        with open(LABAMP_CONFIG_PATH) as f:
            cfg.update(json.load(f))
    except (OSError, ValueError):
        pass
    return cfg


_labamp_cfg = _load_labamp_config()
_labamp = None  # type: ignore[assignment]


def _rebuild_labamp() -> None:
    global _labamp
    _labamp = MockLabAmp() if _labamp_cfg.get("mode") == "mock" else LabAmpClient(_labamp_cfg["base_url"])


_rebuild_labamp()


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _broadcaster
    _broadcaster = Broadcaster(asyncio.get_running_loop())
    yield


app = FastAPI(title="force-app-recorder", lifespan=lifespan)

_cors = [o.strip() for o in os.environ.get(
    "RECORDER_CORS_ORIGINS", "http://localhost:5180,http://localhost:5181").split(",") if o.strip()]
if _cors:
    app.add_middleware(CORSMiddleware, allow_origins=_cors, allow_methods=["*"], allow_headers=["*"])


@app.get("/health")
async def health() -> dict:
    return {"ok": True, "state": _session.state if _session else "idle"}


def _busy() -> bool:
    return bool(_session and _session.state in ("recording", "finalizing"))


@app.post("/record/start")
async def record_start(cfg: RecordConfig) -> dict:
    global _session
    if _busy():
        raise HTTPException(409, "a recording is already in progress")
    if cfg.source == "nidaq":
        from .sources.nidaq import NidaqSource, NidaqUnavailable, nidaq_available
        if not nidaq_available():
            raise HTTPException(503, "NI-DAQmx runtime not available on this host — run on the acquisition PC.")
        try:
            source = NidaqSource(cfg, physical_channels=cfg.nidaq_channels or None)
        except (ValueError, NidaqUnavailable) as e:
            raise HTTPException(400, str(e))
        # Per-channel volts→N gains from the amp's (auto-ranged) ranges: N/V = range / analog_fs.
        if not cfg.dyno_gains:
            try:
                vfs = float(_labamp_cfg.get("analog_fullscale_v", 10.0))
                rows = sorted(_labamp.sensor_table(8), key=lambda x: x["channel"])
                gains = [float(r.get("range") or vfs) / vfs for r in rows][:8]
                if len(gains) == 8:
                    cfg.dyno_gains = gains
            except LabAmpError:
                pass  # amp unreachable — fall back to the scalar gain
    else:
        source = SimSource(cfg, realtime=True)
    _session = RecordingSession(cfg, CAPTURES_ROOT, source, broadcaster=_broadcaster)
    _session.start()
    return _session.status()


@app.post("/record/start_replay")
async def record_start_replay(
    file: UploadFile = File(...),
    sample_name: str = Form("REPLAY"),
    axis: str = Form("Fz"),
    ppr: int = Form(1),
    speed: float = Form(1.0),
    extra_metadata: str = Form("{}"),
) -> dict:
    """Replay a real recorded cut (an uploaded D1LC live_cache.bin) through the live pipeline."""
    global _session
    if _busy():
        raise HTTPException(409, "a recording is already in progress")
    cache_bytes = await file.read()
    try:
        h = read_d1lc_header(cache_bytes)
    except ValueError as e:
        raise HTTPException(422, f"not a D1LC cache: {e}") from e
    try:
        meta = json.loads(extra_metadata) if extra_metadata else {}
    except json.JSONDecodeError:
        meta = {}
    n, fs = h["n"], (h["fs"] or 1000.0)
    cfg = RecordConfig(
        sample_name=sample_name, axis=axis if axis in ("Fx", "Fy", "Fz") else "Fz",
        feed=max(1e-6, h["feed"]), diam=max(1e-6, h["diam"]),
        sample_rate=fs, duration_sec=max(0.1, n / fs), ppr=max(1, ppr),
        extra_metadata=meta,
    )
    source = ReplaySource(cache_bytes, ppr=cfg.ppr, realtime=True, speed=speed)
    _session = RecordingSession(cfg, CAPTURES_ROOT, source, broadcaster=_broadcaster)
    _session.start()
    return _session.status()


@app.post("/record/stop")
async def record_stop() -> dict:
    if not _session or _session.state not in ("recording", "finalizing"):
        raise HTTPException(409, "no recording in progress")
    await run_in_threadpool(_session.stop, True, 60.0)
    return {"id": _session.id, "state": _session.state, "error": _session.error, "summary": _session.summary}


@app.get("/record/status")
async def record_status() -> dict:
    return _session.status() if _session else {"state": "idle"}


@app.get("/captures")
async def list_captures() -> dict:
    ids = sorted((d for d in os.listdir(CAPTURES_ROOT)
                  if os.path.isdir(os.path.join(CAPTURES_ROOT, d))), reverse=True)
    return {"captures": ids}


def _capture_file(cid: str, name: str) -> str:
    # Guard against path traversal: only a bare id + known filename.
    if "/" in cid or "\\" in cid or ".." in cid:
        raise HTTPException(400, "bad id")
    path = os.path.join(CAPTURES_ROOT, cid, name)
    if not os.path.isfile(path):
        raise HTTPException(404, "not found")
    return path


@app.get("/captures/{cid}/summary")
async def capture_summary(cid: str) -> JSONResponse:
    with open(_capture_file(cid, "summary.json")) as f:
        return JSONResponse(json.load(f))


@app.get("/captures/{cid}/live_cache.bin")
async def capture_cache(cid: str) -> FileResponse:
    return FileResponse(_capture_file(cid, "live_cache.bin"), media_type="application/octet-stream")


@app.get("/captures/{cid}/capture.mat")
async def capture_mat(cid: str) -> FileResponse:
    return FileResponse(_capture_file(cid, "capture.mat"), media_type="application/octet-stream",
                        filename=f"{cid}.mat")


@app.get("/labamp/status")
async def labamp_status() -> dict:
    amp = _labamp
    reachable = await run_in_threadpool(amp.ping)
    mode = None
    if reachable:
        try:
            mode = await run_in_threadpool(amp.get_operation_mode)
        except LabAmpError:
            pass
    return {"reachable": reachable, "mode": mode, "base_url": amp.base_url, "mock": amp.mock,
            "channels": _labamp_cfg["channels"], "config_mode": _labamp_cfg["mode"]}


@app.post("/labamp/mode")
async def labamp_set_mode(body: dict) -> dict:
    mode = str(body.get("mode", ""))
    try:
        await run_in_threadpool(_labamp.set_operation_mode, mode)
        current = await run_in_threadpool(_labamp.get_operation_mode)
    except LabAmpError as e:
        raise HTTPException(400, str(e))
    return {"mode": current}


@app.get("/labamp/sensors")
async def labamp_sensors() -> dict:
    try:
        rows = await run_in_threadpool(_labamp.sensor_table, _labamp_cfg["channels"])
    except LabAmpError as e:
        raise HTTPException(502, str(e))
    return {"sensors": rows}


@app.get("/labamp/export")
async def labamp_export() -> JSONResponse:
    try:
        return JSONResponse(await run_in_threadpool(_labamp.export_params))
    except LabAmpError as e:
        raise HTTPException(502, str(e))


# ---- Auto-range: drive the amp's measuring range from the measured signal ----
def _measure_peaks(amp, channels: int) -> list[float]:
    """Per-channel peak magnitude (N) from the amp's live max/min (run a representative cut first)."""
    items = amp.signal_get(list(range(1, channels + 1)))
    by_ch: dict[int, float] = {}
    for it in items:
        ch = int(it.get("channel", 0))
        mx = abs(float((it.get("max") or [0])[0]))
        mn = abs(float((it.get("min") or [0])[0]))
        by_ch[ch] = max(mx, mn)
    return [by_ch.get(i, 0.0) for i in range(1, channels + 1)]


def _current_ranges(amp, channels: int) -> list:
    rows = amp.sensor_table(channels)
    r = {int(x["channel"]): x.get("range") for x in rows}
    return [float(r[i]) if r.get(i) is not None else None for i in range(1, channels + 1)]


def _daq() -> tuple[int, int, int, float]:
    """(nidaq_bits, dac_bits, effective_bits, analog_fullscale_v). Effective = the chain bottleneck."""
    nidaq = int(_labamp_cfg.get("nidaq_bits", 16))
    dac = int(_labamp_cfg.get("labamp_dac_bits", 12))
    vfs = float(_labamp_cfg.get("analog_fullscale_v", 10.0))
    return nidaq, dac, effective_bits(dac, nidaq), vfs


@app.get("/labamp/autorange")
async def labamp_autorange(headroom: Optional[float] = None) -> dict:
    hr = float(headroom) if headroom else float(_labamp_cfg.get("autorange_headroom", 1.5))
    ch = int(_labamp_cfg["channels"])
    nidaq, dac, eff, vfs = _daq()
    try:
        peaks = await run_in_threadpool(_measure_peaks, _labamp, ch)
        currents = await run_in_threadpool(_current_ranges, _labamp, ch)
    except LabAmpError as e:
        raise HTTPException(502, str(e))
    return {"headroom": hr, "nidaq_bits": nidaq, "dac_bits": dac, "effective_bits": eff, "fullscale_v": vfs,
            "recommendations": recommend_ranges(peaks, currents, headroom=hr, bits=eff, fullscale_v=vfs)}


@app.post("/labamp/autorange/apply")
async def labamp_autorange_apply(body: dict) -> dict:
    hr = float(body.get("headroom") or _labamp_cfg.get("autorange_headroom", 1.5))
    ch = int(_labamp_cfg["channels"])
    nidaq, dac, eff, vfs = _daq()
    try:
        peaks = await run_in_threadpool(_measure_peaks, _labamp, ch)
        currents = await run_in_threadpool(_current_ranges, _labamp, ch)
        recs = recommend_ranges(peaks, currents, headroom=hr, bits=eff, fullscale_v=vfs)
        for r in recs:
            await run_in_threadpool(_labamp.set_range, r["channel"], r["recommended"])
        status = await run_in_threadpool(_labamp.channel_status, ch)
    except LabAmpError as e:
        raise HTTPException(502, str(e))
    return {"applied": recs, "status": status}


@app.get("/labamp/config")
async def labamp_get_config() -> dict:
    return _labamp_cfg


from urllib.parse import urlparse

# The amp is legitimately on a link-local/private address, so we can't block those ranges (that IS
# the target). We do reject non-http(s) schemes and the cloud-metadata address — the one dangerous
# SSRF target inside link-local. The recorder is otherwise a loopback-bound, single-user local
# hardware controller (bind 127.0.0.1), which is the mitigation for the lack of endpoint auth.
_BLOCKED_AMP_HOSTS = {"169.254.169.254", "metadata.google.internal", "fd00:ec2::254"}


def _validate_amp_url(url: str) -> str:
    u = urlparse(url)
    if u.scheme not in ("http", "https"):
        raise HTTPException(400, "amp URL must use http or https")
    if not u.hostname:
        raise HTTPException(400, "amp URL must include a host")
    if u.hostname.strip("[]").lower() in _BLOCKED_AMP_HOSTS:
        raise HTTPException(400, "amp URL host is not allowed")
    return url


@app.post("/labamp/config")
async def labamp_post_config(body: dict) -> dict:
    if "base_url" in body:
        body["base_url"] = _validate_amp_url(str(body["base_url"]))
    for k in ("base_url", "channels", "mode", "autorange_headroom", "nidaq_bits", "labamp_dac_bits", "analog_fullscale_v"):
        if k in body:
            _labamp_cfg[k] = body[k]
    try:
        with open(LABAMP_CONFIG_PATH, "w") as f:
            json.dump(_labamp_cfg, f)
    except OSError:
        pass
    _rebuild_labamp()
    return _labamp_cfg


@app.websocket("/record/stream")
async def record_stream(ws: WebSocket) -> None:
    await ws.accept()
    assert _broadcaster is not None
    q = _broadcaster.subscribe()
    try:
        while True:
            msg = await q.get()
            if isinstance(msg, bytes):
                await ws.send_bytes(msg)
            else:
                await ws.send_text(msg)
    except WebSocketDisconnect:
        pass
    finally:
        _broadcaster.unsubscribe(q)
