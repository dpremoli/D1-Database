"""FRM filter-service: interactive signal-filter previews for the force dashboard.

The browser POSTs a filter chain + a live-cache file id; we fetch the cache from Directus
FORWARDING THE CALLER'S OWN credentials (cookie / Authorization header) — so access control
stays Directus's and an unauthenticated caller simply gets Directus's 403. Parsed caches are
LRU-kept in memory so repeated tweaks only pay the filter maths. Filtering runs at the
cache's real sample rate; preview decimation (target_points) happens AFTER filtering.
Served same-origin by Caddy at /filter/*.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
from collections import OrderedDict

import httpx
import numpy as np
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from scipy import signal as ssig

from .d1lc import Cache, parse, serialise
from .filters import ChainError, apply_chain

DIRECTUS_URL = os.environ.get("DIRECTUS_URL", "http://directus:8055").rstrip("/")
LRU_CAP = int(os.environ.get("CACHE_LRU", "4"))

app = FastAPI(title="d1-filter-service")

# CORS for the standalone Force App (apps/force-app/web), which calls this service from its
# own origin. `expose_headers` is essential: the browser reads X-Filter-Skipped / X-Filter-
# Stride off the response, and cross-origin those are hidden unless explicitly exposed.
# (Same-origin embedding in Directus needed none of this.)
_cors_origins = [o.strip() for o in os.environ.get("FILTER_CORS_ORIGINS", "").split(",") if o.strip()]
if _cors_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_cors_origins,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type"],
        expose_headers=["X-Filter-Skipped", "X-Filter-Ms", "X-Filter-Stride"],
    )

_lru: OrderedDict[str, Cache] = OrderedDict()


def _auth_headers(req: Request) -> dict:
    h: dict[str, str] = {}
    if "authorization" in req.headers:
        h["Authorization"] = req.headers["authorization"]
    if "cookie" in req.headers:
        h["Cookie"] = req.headers["cookie"]
    return h


async def _authorize(file_id: str, req: Request) -> None:
    """Re-check that THIS caller may read the asset, with their own credentials — a cheap
    HEAD to the same /assets route the real fetch uses (Directus applies the identical file
    permissions). Guards LRU HITS: without this, an entry warmed by one user's credentials
    would be served to any other caller who knows the id (IDOR). The MISS path authorizes
    inherently, because it fetches the bytes with the caller's own credentials."""
    async with httpx.AsyncClient(timeout=30) as cl:
        r = await cl.head(f"{DIRECTUS_URL}/assets/{file_id}", headers=_auth_headers(req))
    if r.status_code not in (200, 206):
        raise HTTPException(r.status_code if r.status_code >= 400 else 403, "not permitted")


async def _get_cache(file_id: str, req: Request) -> Cache:
    c = _lru.get(file_id)
    if c is not None:
        await _authorize(file_id, req)          # per-request authz on the shared LRU (IDOR guard)
        _lru.move_to_end(file_id)
        return c
    async with httpx.AsyncClient(timeout=120) as cl:
        r = await cl.get(f"{DIRECTUS_URL}/assets/{file_id}", headers=_auth_headers(req))
    if r.status_code != 200:
        raise HTTPException(r.status_code, f"cache fetch failed ({r.status_code})")
    try:
        c = parse(r.content)
    except ValueError as e:
        raise HTTPException(422, str(e)) from e
    _lru[file_id] = c
    while len(_lru) > LRU_CAP:
        _lru.popitem(last=False)
    return c


def _effective_fs(c: Cache) -> float:
    """The cache's REAL sample rate (it may already be decimated vs the header Fs)."""
    if c.n > 1 and c.t[-1] > c.t[0]:
        return float((c.n - 1) / (c.t[-1] - c.t[0]))
    return float(c.fs)


def _filtered(c: Cache, chain: dict) -> tuple[Cache, list[str]]:
    fs = _effective_fs(c)
    mean_rpm = float(np.mean(c.rpm)) if c.n else 0.0
    axes, skipped = apply_chain({"Fx": c.fx, "Fy": c.fy, "Fz": c.fz}, fs, mean_rpm, chain)
    fc = Cache(c.fs, c.feed, c.diam, c.cs_sec, c.ce_sec, c.t,
               axes["Fx"].astype(np.float32), axes["Fy"].astype(np.float32),
               axes["Fz"].astype(np.float32), c.rpm, c.revs)
    return fc, skipped


@app.get("/health")
async def health():
    return {"ok": True, "lru": len(_lru)}


@app.post("/run")
async def filter_cache(req: Request):
    body = await req.json()
    file_id = body.get("cache_file_id")
    chain = body.get("chain") or {}
    target = int(body.get("target_points") or 1_500_000)
    if not file_id:
        raise HTTPException(422, "cache_file_id required")
    c = await _get_cache(str(file_id), req)
    t0 = time.perf_counter()
    try:
        fc, skipped = _filtered(c, chain)
    except ChainError as e:
        raise HTTPException(422, str(e)) from e
    stride = max(1, -(-c.n // max(1, target)))          # ceil-div: decimate AFTER filtering
    buf = serialise(fc, stride)
    return Response(content=buf, media_type="application/octet-stream", headers={
        "X-Filter-Skipped": "; ".join(skipped),
        "X-Filter-Ms": f"{(time.perf_counter() - t0) * 1000:.0f}",
        "X-Filter-Stride": str(stride),
        "Cache-Control": "no-store",
    })


@app.post("/fft")
async def filter_fft(req: Request):
    """Amplitude spectrum of ONE filtered axis (for the dashed FFT-chart overlay)."""
    body = await req.json()
    file_id = body.get("cache_file_id")
    axis = str(body.get("axis") or "Fz")
    chain = body.get("chain") or {}
    if not file_id:
        raise HTTPException(422, "cache_file_id required")
    if axis not in ("Fx", "Fy", "Fz"):
        raise HTTPException(422, "axis must be Fx|Fy|Fz")
    c = await _get_cache(str(file_id), req)
    try:
        fc, _ = _filtered(c, chain)
    except ChainError as e:
        raise HTTPException(422, str(e)) from e
    fs = _effective_fs(c)
    y = {"Fx": fc.fx, "Fy": fc.fy, "Fz": fc.fz}[axis].astype(np.float64)
    nper = min(y.size, 1 << 14)
    f, p = ssig.welch(y, fs=fs, nperseg=nper)
    amp = np.sqrt(p)
    step = max(1, f.size // 3000)                      # ~3k points, full Nyquist span
    return {"f": f[::step].tolist(), "amp": amp[::step].tolist()}


def _chain_hash(chain: dict) -> str:
    return hashlib.sha1(json.dumps(chain, sort_keys=True).encode()).hexdigest()[:12]
