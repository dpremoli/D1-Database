"""diag-service: interactive diagnostics-recipe previews.

The browser POSTs a recipe + an analysis-row id. We forward the caller's own Directus
credentials to resolve that row (403 if they may not see it — an IDOR guard identical to
filter-service's, see its commit 32fb4b7), read the row's published base.d1an off the octree
bind mount, and re-run the recipe from the angular-domain state using the SAME run_recipe the
orchestrator's bake calls. No MATLAB, no archive. The result is D1AN column bytes.

Preview is an APPROXIMATION: base.d1an is float32, so the pipeline resumes at lower precision
than a float64 bake. On real process_force.m geometry the divergence is negligible (validated
against operation ffe1286d: resid_z within 1.6e-4, gi_sig / cluster_id byte-identical), but
the bake remains authoritative — every response carries `X-Diag-Preview: approximate`.

Served same-origin by Caddy at /diag/*; Caddy strips the /diag prefix, so the in-container
routes are /health and /preview.
"""

from __future__ import annotations

import os
import sys
import tempfile
import time
from collections import OrderedDict

import httpx
import numpy as np
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware

# scripts/diag is copied to /app/diag in the image; on a dev host it is reachable one level
# up from the repo. Import the SAME modules the orchestrator uses — never reimplement them.
_HERE = os.path.dirname(__file__)
for _p in (
    os.path.join(_HERE, ".."),
    os.path.join(_HERE, "..", "..", "..", "scripts"),
):
    _abs = os.path.abspath(_p)
    if os.path.isdir(_abs) and _abs not in sys.path:
        sys.path.insert(0, _abs)

from diag.d1an import read_d1an, write_d1an  # noqa: E402
from diag.recipe import recipe_hash  # noqa: E402
from diag.registry import STEPS  # noqa: E402
from diag.runner import run_recipe  # noqa: E402

DIRECTUS_URL = os.environ.get("DIRECTUS_URL", "http://directus:8055").rstrip("/")
BASE_LRU_CAP = int(os.environ.get("BASE_LRU", "6"))
RESULT_LRU_CAP = int(os.environ.get("RESULT_LRU", "24"))


def _octree_root() -> str:
    # Read at call time, not import time, so tests can point it at a tmp dir.
    return os.environ.get("OCTREE_ROOT", "/srv/octrees")


app = FastAPI(title="d1-diag-service")

_cors = [o.strip() for o in os.environ.get("DIAG_CORS_ORIGINS", "").split(",") if o.strip()]
if _cors:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_cors,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type"],
        expose_headers=["X-Diag-Cache", "X-Diag-Ms", "X-Diag-Preview"],
    )

# base.d1an parsed columns, keyed by diag_path (~18k rows x 5 float64 ~= 730 KB each).
_base_lru: OrderedDict[str, dict] = OrderedDict()
# Computed D1AN bytes, keyed by (diag_path, recipe_hash, layers_key). The common interaction —
# viewing several steps of one unchanged recipe — is then served from a single compute.
_result_lru: OrderedDict[tuple, bytes] = OrderedDict()


def _auth_headers(req: Request) -> dict:
    h: dict[str, str] = {}
    if "authorization" in req.headers:
        h["Authorization"] = req.headers["authorization"]
    if "cookie" in req.headers:
        h["Cookie"] = req.headers["cookie"]
    return h


async def _resolve_and_authorize(analysis_id: str, req: Request) -> dict:
    """Fetch diag_path + diag_status for `analysis_id` with the CALLER's credentials.

    Doubles as the authorization check: Directus applies the same row permissions it would
    for any read, so a caller who may not see the row gets its 401/403 here. Runs on every
    request — there is no cached bypass, matching filter-service's post-32fb4b7 behaviour.
    """
    async with httpx.AsyncClient(timeout=30) as cl:
        r = await cl.get(
            f"{DIRECTUS_URL}/items/machining_force_analysis/{analysis_id}",
            params={"fields": "diag_path,diag_status"},
            headers=_auth_headers(req),
        )
    if r.status_code in (401, 403):
        raise HTTPException(r.status_code, "not permitted")
    if r.status_code == 404:
        raise HTTPException(404, "analysis row not found")
    if r.status_code != 200:
        raise HTTPException(502, f"directus {r.status_code}")
    return (r.json() or {}).get("data") or {}


def _load_base(diag_path: str) -> dict:
    hit = _base_lru.get(diag_path)
    if hit is not None:
        _base_lru.move_to_end(diag_path)
        return hit
    path = os.path.join(_octree_root(), "diag", diag_path, "base.d1an")
    if not os.path.isfile(path):
        raise HTTPException(409, "no base.d1an for this analysis — a rebake is needed")
    cols = {k: np.asarray(v, dtype=np.float64) for k, v in read_d1an(path).items()}
    _base_lru[diag_path] = cols
    while len(_base_lru) > BASE_LRU_CAP:
        _base_lru.popitem(last=False)
    return cols


def _first_derived_index(recipe: dict) -> int:
    """The step to resume from: the first whose registry tier is 'derived'. Everything
    before it (frame_transform, angular_resample) is already baked into base.d1an."""
    for i, s in enumerate(recipe.get("steps", [])):
        spec = STEPS.get(s.get("op"))
        if spec is not None and spec.tier == "derived":
            return i
    raise HTTPException(422, "recipe has no derived step to preview")


@app.get("/health")
async def health():
    return {"ok": True, "base_lru": len(_base_lru), "result_lru": len(_result_lru)}


@app.post("/preview")
async def preview(req: Request):
    body = await req.json()
    analysis_id = body.get("analysis_id")
    recipe = body.get("recipe")
    layers = body.get("layers") or None
    if not analysis_id or not isinstance(recipe, dict):
        raise HTTPException(422, "analysis_id and recipe are required")

    row = await _resolve_and_authorize(str(analysis_id), req)
    if row.get("diag_status") != "done" or not row.get("diag_path"):
        raise HTTPException(409, "analysis has no completed bake to preview from")
    diag_path = str(row["diag_path"])

    layers_key = repr(sorted((layers or {}).items())) if layers else ""
    key = (diag_path, recipe_hash(recipe), layers_key)
    cached = _result_lru.get(key)
    if cached is not None:
        _result_lru.move_to_end(key)
        return Response(
            cached,
            media_type="application/octet-stream",
            headers={
                "Cache-Control": "no-store",
                "X-Diag-Cache": "hit",
                "X-Diag-Preview": "approximate",
            },
        )

    base = _load_base(diag_path)
    t0 = time.perf_counter()
    try:
        cols, _metrics = run_recipe(
            recipe, dict(base), layers=layers, from_step=_first_derived_index(recipe)
        )
    except HTTPException:
        raise
    except (KeyError, ValueError) as e:
        raise HTTPException(422, f"recipe failed: {e}") from e

    with tempfile.NamedTemporaryFile(suffix=".d1an", delete=False) as f:
        tmp = f.name
    try:
        write_d1an(tmp, cols)
        with open(tmp, "rb") as fh:
            out = fh.read()
    finally:
        os.unlink(tmp)

    _result_lru[key] = out
    while len(_result_lru) > RESULT_LRU_CAP:
        _result_lru.popitem(last=False)
    return Response(
        out,
        media_type="application/octet-stream",
        headers={
            "Cache-Control": "no-store",
            "X-Diag-Cache": "miss",
            "X-Diag-Preview": "approximate",
            "X-Diag-Ms": f"{(time.perf_counter() - t0) * 1000:.0f}",
        },
    )
