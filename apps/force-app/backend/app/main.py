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

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from starlette.concurrency import run_in_threadpool

from .config import RecordConfig
from .session import RecordingSession
from .stream.broadcast import Broadcaster

CAPTURES_ROOT = os.environ.get(
    "FORCE_APP_CAPTURES", os.path.join(os.path.dirname(os.path.dirname(__file__)), "captures")
)
os.makedirs(CAPTURES_ROOT, exist_ok=True)

_broadcaster: Optional[Broadcaster] = None
_session: Optional[RecordingSession] = None


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


@app.post("/record/start")
async def record_start(cfg: RecordConfig) -> dict:
    global _session
    if _session and _session.state in ("recording", "finalizing"):
        raise HTTPException(409, "a recording is already in progress")
    _session = RecordingSession(cfg, CAPTURES_ROOT, broadcaster=_broadcaster)
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
