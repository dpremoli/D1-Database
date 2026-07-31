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
    for k in ("base_url", "channels", "mode"):
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
