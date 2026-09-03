# Diagnostics Phase G — Interactive Full-Resolution Workbench Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Make the Diagnostics Workbench render the full ~7M-point spiral (not the 256/rev analysis grid), and let the analyst frame a region and run HDBSCAN / Gi\* / seeded segmentation on just those points at full resolution — Gi\* auto on pan/zoom, HDBSCAN and segmentation on a button.

**Architecture:** The bake gains one `np.interp` broadcast of `resid_z` onto the strided spiral coords `process_diag_row` already has, and publishes `full.d1an` (flat `{x,y,resid_z}`, ~7M rows) plus a `full/` Potree octree. Everything Phase F produces is untouched — the bake is purely additive, so the golden fixtures need no change. A new `POST /diag/viewport` endpoint crops `full.d1an` to a bbox, strides down if over a cap, runs exactly one registry step's function on the crop, and returns `{x, y, value}` as D1AN bytes. In the workbench, `DiagOctreeView` (currently dead code) becomes the Spatial panel's base layer coloured by `resid_z`; a new flat `DiagAnalysisOverlay` renders the last viewport result on top. `DiagScatter` is retired from the workbench.

**Tech Stack:** Python 3.12 / numpy / scikit-learn (worker + service), FastAPI (service), laspy + PotreeConverter (bake), Vue 3 + TypeScript + Three.js + potree-core (`@d1/force-plotting`).

**Spec:** `docs/superpowers/specs/2026-09-03-diagnostics-phase-g-interactive-fullres-design.md`

## Global Constraints

- **The bake is additive. `DEFAULT_RECIPE`, `run_recipe`, `attrs.d1an`, `base.d1an`, the 256/rev diag octree, and every existing test are untouched.** The only server change to the bake is adding artifacts under `full/`. If a golden/equivalence test needs editing, the change is wrong — stop.
- **`resid_z` broadcast uses `np.interp`** (linear), not nearest — `resid_z` is a continuous residual. `columns["rev"]` is the monotone angular grid; `cache["revs"]` is the per-point rev of the strided spiral. NaN in `resid_z` (a Phase-E mask) propagates through `np.interp` — keep it in `full.d1an` (masked points must be excluded from a viewport recompute) but `nan_to_num` it before the `full/` LAS write (or PotreeConverter's per-attr min/max goes NaN and the octree renders blank — same rule as the 256/rev octree).
- **`full.d1an` coordinate space** is MATLAB's own spiral geometry (`_read_octree_bin` output), the SAME x/y mm space `diag_layer` polygons and `columns["x"]/["y"]` live in. A polygon drawn on the octree view selects the same physical region at 7M as at 256/rev.
- **`/diag/viewport` authorizes on every call including LRU hits** — the `32fb4b7` IDOR guard. Reuse `_resolve_and_authorize` verbatim.
- **`DIAG_VERSION` 6 → 7.** `claim_diag` requeues every cut to generate `full/`. Base analysis output is identical; only the published set grew.
- **Viewport recompute is a preview, never authoritative.** Cap at `max_points` (default 1_000_000); stride down over that. The 256/rev `attrs.d1an` stays the global baked truth.
- Migrations: none in this phase. Service rebuild: `docker compose build diag-service`.
- Python: `py -3 -m pytest` via the PowerShell tool. Package: `npm test -w @d1/force-plotting`. Types: `npm run typecheck -w @d1/force-plotting` and `-w force-app-web`, both 0 errors.
- The orchestrator daemon runs on this host; `.env` supplies `DATABASE_URL` (host DSN `@localhost:5432`). Directus DB user `d1` / db `d1_database`.

---

## File Structure

**Create:**
- `tests/scripts/test_resid_broadcast.py` — `np.interp` broadcast fidelity (module-level helper extracted from `process_diag_row`).
- `scripts/diag/broadcast.py` — `broadcast_to_spiral(rev_grid, value_grid, revs_full) -> np.ndarray`. One tiny pure function, unit-testable without MATLAB.
- `plugins/diag-service/tests/test_viewport.py` — crop, stride, per-step, authz, LRU.
- `packages/force-plotting/src/diagViewport.ts` — `fetchViewportCompute(analysisId, bbox, step, opts) -> {x, y, value, n, ms}`.
- `packages/force-plotting/src/diagViewport.test.ts`.
- ~~`DiagAnalysisOverlay.vue`~~ — **dropped in Task 3 Step 1.** A second `<canvas>` would need its own WebGL context, camera sync, and z-fight management; the overlay instead renders as a second `THREE.Points` inside `DiagOctreeView`'s own scene (Task 4).

**Modify:**
- `scripts/force_orchestrator.py` — `process_diag_row`: `resid_z` broadcast + `full.d1an` + `full/` octree publish; `DIAG_VERSION = 7`.
- `plugins/diag-service/app/main.py` — `POST /viewport`; a `_full_lru` for parsed `full.d1an`.
- `plugins/diag-service/tests/test_preview.py` — unchanged (regression check it still passes).
- `packages/force-plotting/src/DiagOctreeView.vue` — paint machinery port (draw `<div>`, `canvasToWorld`, layer `LineLoop` overlay, draft ring); new props `layers`, `activeLayerName`, `paintMode`; new emit `polygon`. `currentBounds()` is already exposed — add a `boundsChanged` emit, debounced.
- `packages/force-plotting/src/DiagnosticsWorkbench.vue` — retire `DiagScatter`; `DiagOctreeView` + `DiagAnalysisOverlay` as the Spatial panel; viewport tracking; Gi\* auto / HDBSCAN+segmentation buttons; layout rework (Spatial hero, Recipe collapsible); state strip with viewport point count.
- `packages/force-plotting/src/RecipePanel.vue` — per spatial step: "runs on the current view" note + trigger button for HDBSCAN / segmentation; `collapsed` prop.
- `packages/force-plotting/src/index.ts` — export `fetchViewportCompute`, `ViewportStep`, `ViewportResult`.
- `apps/force-app/web/src/force/DiagnosticsPage.vue` — pass through any new props (likely none; the workbench owns viewport state).

**Retire (keep exported, remove from the workbench):** `DiagScatter.vue` — still in `index.ts`, no longer imported by `DiagnosticsWorkbench.vue`.

---

## Task 1: bake broadcasts `resid_z` to full resolution

**Files:**
- Create: `scripts/diag/broadcast.py`, `tests/scripts/test_resid_broadcast.py`
- Modify: `scripts/force_orchestrator.py`

**Interfaces:**
- Produces:
  - `broadcast.broadcast_to_spiral(rev_grid: np.ndarray, value_grid: np.ndarray, revs_full: np.ndarray) -> np.ndarray` — `np.interp(revs_full, rev_grid, value_grid)`, float64, length `revs_full.size`. `rev_grid` must be sorted ascending (it is — the angular grid); a NaN in `value_grid` propagates to every `revs_full` point that interpolates across it.
  - `process_diag_row` publishes `OCTREE_DIR/diag/<op>/full/full.d1an` (`{x, y, resid_z}` float32, spiral length) and `OCTREE_DIR/diag/<op>/full/{metadata.json,hierarchy.bin,octree.bin}`.
  - `DIAG_VERSION = 7`.

- [ ] **Step 1: Write the failing test**

```python
# tests/scripts/test_resid_broadcast.py
import os
import sys

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "scripts"))

from diag.broadcast import broadcast_to_spiral


def test_interpolates_between_phase_bins():
    grid = np.array([0.0, 1.0, 2.0, 3.0])
    vals = np.array([0.0, 10.0, 20.0, 30.0])
    full = np.array([0.0, 0.5, 1.0, 2.5, 3.0])
    out = broadcast_to_spiral(grid, vals, full)
    np.testing.assert_allclose(out, [0.0, 5.0, 10.0, 25.0, 30.0])


def test_a_point_on_a_bin_centre_equals_that_bin():
    grid = np.arange(10.0)
    vals = np.sin(grid)
    out = broadcast_to_spiral(grid, vals, grid.copy())
    np.testing.assert_array_equal(out, vals)


def test_clamps_outside_the_grid():
    grid = np.array([1.0, 2.0, 3.0])
    vals = np.array([10.0, 20.0, 30.0])
    out = broadcast_to_spiral(grid, vals, np.array([0.0, 5.0]))
    np.testing.assert_array_equal(out, [10.0, 30.0])   # np.interp clamps to endpoints


def test_nan_in_the_grid_propagates_locally():
    grid = np.array([0.0, 1.0, 2.0])
    vals = np.array([0.0, np.nan, 4.0])
    out = broadcast_to_spiral(grid, vals, np.array([0.5, 1.5]))
    assert np.all(np.isnan(out))            # both interpolate across the NaN bin
```

- [ ] **Step 2: Run, verify fail** — `py -3 -m pytest tests/scripts/test_resid_broadcast.py -q` → `ModuleNotFoundError: diag.broadcast`.

- [ ] **Step 3: Implement `broadcast.py`**

```python
# scripts/diag/broadcast.py
"""Broadcast a per-revolution-phase analysis column back onto the full-resolution spiral.

The pipeline computes resid_z on the 256/rev angular grid; the Phase G full-resolution
octree and the viewport-recompute source need it per raw spiral point. Linear interpolation
in revolution-phase is the honest broadcast for a continuous residual -- nearest-neighbour
would band at the phase-bin boundaries.
"""
from __future__ import annotations

import numpy as np


def broadcast_to_spiral(
    rev_grid: np.ndarray, value_grid: np.ndarray, revs_full: np.ndarray
) -> np.ndarray:
    """np.interp(revs_full, rev_grid, value_grid). rev_grid must be ascending (the angular
    grid is). Points of revs_full outside rev_grid clamp to the endpoints. A NaN in
    value_grid propagates to every revs_full point whose interval touches it."""
    rev_grid = np.asarray(rev_grid, dtype=np.float64)
    value_grid = np.asarray(value_grid, dtype=np.float64)
    revs_full = np.asarray(revs_full, dtype=np.float64)
    # np.interp returns silent garbage for a non-monotone xp -- and _truncate slices rev_grid,
    # so guard rather than trust the comment (cf. the samples_per_rev bug in the recipe engine).
    if rev_grid.size > 1 and not np.all(np.diff(rev_grid) > 0):
        raise ValueError("rev_grid must be strictly ascending")
    return np.interp(revs_full, rev_grid, value_grid)
```

- [ ] **Step 4: Run tests** — `py -3 -m pytest tests/scripts/test_resid_broadcast.py -q` → 4 passed.

- [ ] **Step 5: Wire the broadcast + `full/` publish into `process_diag_row`**

In `scripts/force_orchestrator.py`, add the import near the other diag imports:

```python
    from diag.broadcast import broadcast_to_spiral
```

After the existing `las.write(las_path)` + PotreeConverter + `dst` copy block for the 256/rev octree (right before or after the `attrs.d1an` / `base.d1an` copies), add:

```python
        # --- Phase G: full-resolution resid_z octree + flat viewport source -----------------
        # x / y / revs here are the STRIDED spiral (cache_target points, index-aligned with
        # the cache) -- the same arrays the 256/rev octree's fza resample used. Broadcast the
        # 256/rev resid_z onto every spiral point by revolution-phase.
        resid_full = broadcast_to_spiral(
            columns["rev"].astype(np.float64),
            columns["resid_z"].astype(np.float64),
            np.asarray(cache["revs"], dtype=np.float64),
        )
        # write_d1an raises a generic ValueError on a length mismatch, which would land in the
        # daemon's except and write a useless diag_error. Fail loudly with the real numbers.
        if resid_full.size != x.size:
            raise RuntimeError(
                f"resid_z broadcast length {resid_full.size} != strided spiral {x.size}"
            )
        full_dir = dst / "full"
        full_dir.mkdir(parents=True, exist_ok=True)

        # full.d1an: the flat {x, y, resid_z} the /diag/viewport endpoint crops. Keep NaN
        # (masked points must be excluded from a viewport recompute).
        write_d1an(str(Path(outdir) / "full.d1an"), {
            "x": x.astype(np.float32),
            "y": y.astype(np.float32),
            "resid_z": resid_full.astype(np.float32),
        })
        shutil.copy2(Path(outdir) / "full.d1an", full_dir / "full.d1an")

        # full/ octree: LAS with resid_z as the one extra dim; nan_to_num so PotreeConverter's
        # per-attribute min/max stays finite (else DiagOctreeView's colour range goes NaN).
        fh = laspy.LasHeader(point_format=3)
        fh.offsets = [float(x.min()), float(y.min()), 0.0]
        fh.scales = [0.001, 0.001, 0.001]
        fh.add_extra_dim(laspy.ExtraBytesParams(name="resid_z", type=np.float32))
        fl = laspy.LasData(fh)
        fl.x = x.astype(np.float64)
        fl.y = y.astype(np.float64)
        fl.z = np.zeros(x.size)
        fl.resid_z = np.nan_to_num(resid_full, nan=0.0).astype(np.float32)
        rlo, rhi = float(np.nanmin(resid_full)), float(np.nanmax(resid_full))
        fl.intensity = np.clip(
            (np.nan_to_num(resid_full, nan=rlo) - rlo) / ((rhi - rlo) or 1.0) * 65535, 0, 65535
        ).astype(np.uint16)
        full_las = str(Path(outdir) / "full.las")
        fl.write(full_las)

        full_octmp = str(Path(outdir) / "full_octree")
        fpc = subprocess.run(
            [potree_exe, full_las, "-o", full_octmp],
            capture_output=True, text=True, timeout=timeout,
        )
        if fpc.returncode != 0 or not (Path(full_octmp) / "metadata.json").exists():
            tail = (fpc.stderr or fpc.stdout or "").strip().splitlines()[-5:]
            raise RuntimeError("PotreeConverter (full) failed: " + " | ".join(tail))
        for fn in ("metadata.json", "hierarchy.bin", "octree.bin"):
            shutil.copy2(Path(full_octmp) / fn, full_dir / fn)
```

(Place it inside the `try`, after `dst` exists and `x`/`y`/`cache`/`columns`/`potree_exe` are in scope — i.e. after the 256/rev octree `dst` copy block, before the `UPDATE ... SET diag_status='done'`.)

- [ ] **Step 6: `DIAG_VERSION = 7`**

- [ ] **Step 7: Full diag suite + orchestrator parse check**

```bash
py -3 -m pytest tests/scripts/ -q
py -3 -c "import ast; ast.parse(open('scripts/force_orchestrator.py').read()); print('ok')"
```
Expected: every existing test green (nothing in the bake's analysis path changed), new broadcast tests green.

- [ ] **Step 8: Commit**

```bash
git add scripts/diag/broadcast.py tests/scripts/test_resid_broadcast.py scripts/force_orchestrator.py
git commit -m "feat(diag): bake publishes a full-resolution resid_z octree + flat viewport source"
```

---

## Task 2: `POST /diag/viewport`

**Files:**
- Modify: `plugins/diag-service/app/main.py`
- Test: `plugins/diag-service/tests/test_viewport.py` (create)

**Interfaces:**
- Consumes: `STEPS` (registry), `resolve_inputs` (Phase F list mode), `validate_geometry`, `_resolve_and_authorize`, `read_d1an`, `write_d1an`.
- Produces:
  ```
  POST /viewport   (Caddy: /diag/viewport)
    { analysis_id: str,
      bbox: [x0, y0, x1, y1],
      step: { "op": str, "params": {...}, "inputs"?: {...} },
      layers?: { name: { geometry, role, value, version } },
      max_points?: int  = 1_000_000,
      output?: str }                     # getis_ord: "gi_star" (default) | "gi_sig"
    -> D1AN bytes: columns {x, y, value}, float32, length = cropped (strided) point count
       headers: X-Diag-Viewport-N, X-Diag-Ms, X-Diag-Cache
  ```
  - `step.op` must be one of `{"getis_ord", "hdbscan", "grow_segmentation"}` → else `HTTPException(422)`.
  - Loads `full.d1an` via a new `_load_full(diag_path)` (own `_full_lru`, cap `FULL_LRU=3` — 84 MB each).
  - Crop: `m = (x>=x0)&(x<=x1)&(y>=y0)&(y<=y1)`; if `m.sum()==0` → `HTTPException(422, "empty viewport")`; if `m.sum() > max_points` → even stride `k = ceil(m.sum()/max_points)`, take every k-th of the cropped indices.
  - Build `cols = {"x": xc, "y": yc, "resid_z": rc}` (float64). For `grow_segmentation`, `resolve_inputs({"op": op, "inputs": step.get("inputs")}, layers, xc, yc)` gives the seed dict; validate each `layers[*].geometry` first.
  - `produced, _ = STEPS[op].fn(cols, step.get("params") or {}, resolved_inputs)`.
  - `value` = `produced["gi_star"]` / `produced["gi_sig"]` (per `output`) / `produced["cluster_id"]` / `produced["segment_id"]`.
  - `write_d1an` a temp file with `{x: xc, y: yc, value}` → return bytes.
  - Result LRU keyed `(diag_path, op, tuple(round(b, 3) for b in bbox), recipe_hash({"steps":[step]}), layers_key, output, max_points)`.

- [ ] **Step 1: Write the failing test**

```python
# plugins/diag-service/tests/test_viewport.py
from __future__ import annotations

import os
import sys
import tempfile

import numpy as np
import pytest

_REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
for _p in (os.path.join(_REPO, "scripts"), os.path.join(_REPO, "plugins", "diag-service"),
           os.path.join(_REPO, "tests", "scripts", "diag")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from diag.d1an import read_d1an, write_d1an  # noqa: E402


def _read(buf: bytes) -> dict:
    with tempfile.NamedTemporaryFile(suffix=".d1an", delete=False) as f:
        f.write(buf); path = f.name
    try:
        return read_d1an(path)
    finally:
        os.unlink(path)


@pytest.fixture
def client(tmp_path, monkeypatch):
    full = tmp_path / "octrees" / "diag" / "op-under-test" / "full"
    full.mkdir(parents=True)
    rng = np.random.default_rng(0)
    n = 40_000
    x = rng.uniform(-40, 40, n).astype(np.float32)
    y = rng.uniform(-40, 40, n).astype(np.float32)
    rz = rng.normal(0, 1, n).astype(np.float32)
    rz[(x > 10) & (x < 20)] += 6.0
    write_d1an(str(full / "full.d1an"), {"x": x, "y": y, "resid_z": rz})
    monkeypatch.setenv("OCTREE_ROOT", str(tmp_path / "octrees"))

    import app.main as m
    m._base_lru.clear(); m._result_lru.clear()
    if hasattr(m, "_full_lru"):
        m._full_lru.clear()

    async def _allow(analysis_id, req):
        return {"diag_path": "op-under-test", "diag_status": "done"}
    monkeypatch.setattr(m, "_resolve_and_authorize", _allow)

    from fastapi.testclient import TestClient
    return TestClient(m.app)


def test_viewport_crops_to_the_bbox(client):
    r = client.post("/viewport", json={
        "analysis_id": "a1", "bbox": [0, -40, 40, 40],
        "step": {"op": "getis_ord", "params": {"k": 20}},
    })
    assert r.status_code == 200, r.text
    got = _read(r.content)
    assert np.all(got["x"] >= 0) and np.all(got["x"] <= 40)
    assert "value" in got
    assert int(r.headers["x-diag-viewport-n"]) == got["x"].size


def test_viewport_strides_over_max_points(client):
    r = client.post("/viewport", json={
        "analysis_id": "a1", "bbox": [-40, -40, 40, 40],
        "step": {"op": "getis_ord", "params": {"k": 10}}, "max_points": 5000,
    })
    assert r.status_code == 200
    assert _read(r.content)["x"].size <= 5000


def test_viewport_hdbscan_returns_cluster_id(client):
    r = client.post("/viewport", json={
        "analysis_id": "a1", "bbox": [-40, -40, 40, 40],
        "step": {"op": "hdbscan", "params": {"min_cluster_size": 20}},
    })
    assert r.status_code == 200
    v = _read(r.content)["value"]
    assert set(np.unique(v)) - {-1.0}          # at least one real cluster


def test_viewport_segmentation_two_seed_polys(client):
    left = [[[-1e6, -1e6], [-5, -1e6], [-5, 1e6], [-1e6, 1e6]]]
    right = [[[5, -1e6], [1e6, -1e6], [1e6, 1e6], [5, 1e6]]]
    r = client.post("/viewport", json={
        "analysis_id": "a1", "bbox": [-40, -40, 40, 40],
        "step": {"op": "grow_segmentation", "params": {"features": ["resid_z"]},
                 "inputs": {"seeds": {"layers": ["L", "R"]}}},
        "layers": {
            "L": {"role": "seed", "geometry": {"polygons": left}, "value": None, "version": 1},
            "R": {"role": "seed", "geometry": {"polygons": right}, "value": None, "version": 1},
        },
    })
    assert r.status_code == 200, r.text
    assert set(np.unique(_read(r.content)["value"])) <= {0.0, 1.0}


def test_viewport_rejects_a_non_spatial_step(client):
    r = client.post("/viewport", json={
        "analysis_id": "a1", "bbox": [-40, -40, 40, 40], "step": {"op": "tsa", "params": {}},
    })
    assert r.status_code == 422


def test_viewport_empty_bbox_is_422(client):
    r = client.post("/viewport", json={
        "analysis_id": "a1", "bbox": [1000, 1000, 1001, 1001],
        "step": {"op": "getis_ord", "params": {}},
    })
    assert r.status_code == 422


def test_viewport_authorizes_on_lru_hit(client, monkeypatch):
    body = {"analysis_id": "a1", "bbox": [-40, -40, 40, 40],
            "step": {"op": "getis_ord", "params": {"k": 10}}}
    assert client.post("/viewport", json=body).status_code == 200   # populates LRU
    import app.main as m

    async def _deny(analysis_id, req):
        from fastapi import HTTPException
        raise HTTPException(403, "nope")
    monkeypatch.setattr(m, "_resolve_and_authorize", _deny)
    assert client.post("/viewport", json=body).status_code == 403   # hit still re-checks
```

- [ ] **Step 2: Run, verify fail** — `py -3 -m pytest plugins/diag-service/tests/test_viewport.py -q` → 404 on `/viewport`.

- [ ] **Step 3: Implement**

Add to `main.py` after the `_load_base` block:

```python
FULL_LRU_CAP = int(os.environ.get("FULL_LRU", "3"))
_full_lru: OrderedDict[str, dict] = OrderedDict()
_viewport_lru: OrderedDict[tuple, tuple[bytes, int]] = OrderedDict()   # key -> (d1an bytes, n)

_VIEWPORT_STEPS = {"getis_ord", "hdbscan", "grow_segmentation"}


def _load_full(diag_path: str) -> dict:
    if not _DIAG_PATH_RE.fullmatch(diag_path):
        raise HTTPException(400, "invalid diag_path")
    hit = _full_lru.get(diag_path)
    if hit is not None:
        _full_lru.move_to_end(diag_path)
        return hit
    path = os.path.join(_octree_root(), "diag", diag_path, "full", "full.d1an")
    if not os.path.isfile(path):
        raise HTTPException(409, "no full.d1an — rebake at DIAG_VERSION 7 needed")
    cols = {k: np.asarray(v, dtype=np.float64) for k, v in read_d1an(path).items()}
    _full_lru[diag_path] = cols
    while len(_full_lru) > FULL_LRU_CAP:
        _full_lru.popitem(last=False)
    return cols
```

And the route:

```python
@app.post("/viewport")
async def viewport(req: Request):
    body = await req.json()
    analysis_id = body.get("analysis_id")
    bbox = body.get("bbox")
    step = body.get("step") or {}
    layers = body.get("layers") or None
    max_points = int(body.get("max_points") or 1_000_000)
    output = body.get("output") or "gi_star"
    op = step.get("op")

    if not analysis_id or not isinstance(bbox, list) or len(bbox) != 4:
        raise HTTPException(422, "analysis_id and bbox [x0,y0,x1,y1] are required")
    if op not in _VIEWPORT_STEPS:
        raise HTTPException(422, f"step.op must be one of {sorted(_VIEWPORT_STEPS)}")
    if layers is not None:
        if not isinstance(layers, dict):
            raise HTTPException(422, "layers must be an object")
        for lname, layer in layers.items():
            try:
                validate_geometry((layer or {}).get("geometry") or {})
            except (ValueError, AttributeError, TypeError) as e:
                raise HTTPException(422, f"layer '{lname}': {e}") from e

    row = await _resolve_and_authorize(str(analysis_id), req)
    if row.get("diag_status") != "done" or not row.get("diag_path"):
        raise HTTPException(409, "analysis has no completed bake")
    diag_path = str(row["diag_path"])

    x0, y0, x1, y1 = (float(v) for v in bbox)
    if x1 < x0:
        x0, x1 = x1, x0
    if y1 < y0:
        y0, y1 = y1, y0
    layers_key = repr(sorted((layers or {}).items())) if layers else ""
    key = (diag_path, op, (round(x0, 3), round(y0, 3), round(x1, 3), round(y1, 3)),
           recipe_hash({"steps": [step]}), layers_key, output, max_points)
    cached = _viewport_lru.get(key)
    if cached is not None:
        _viewport_lru.move_to_end(key)
        cbytes, cn = cached
        return Response(cbytes, media_type="application/octet-stream",
                        headers={"Cache-Control": "no-store", "X-Diag-Cache": "hit",
                                 "X-Diag-Viewport-N": str(cn)})

    full = _load_full(diag_path)
    fx, fy, frz = full["x"], full["y"], full["resid_z"]
    m = (fx >= x0) & (fx <= x1) & (fy >= y0) & (fy <= y1)
    idx = np.where(m)[0]
    if idx.size == 0:
        raise HTTPException(422, "empty viewport")
    if idx.size > max_points:
        idx = idx[:: int(np.ceil(idx.size / max_points))]
    xc, yc, rc = fx[idx].copy(), fy[idx].copy(), frz[idx].copy()

    resolved: dict = {}
    if op == "grow_segmentation":
        from diag.registry import resolve_inputs
        resolved = resolve_inputs({"op": op, "inputs": step.get("inputs")}, layers, xc, yc)

    t0 = time.perf_counter()
    try:
        produced, _metrics = STEPS[op].fn(
            {"x": xc, "y": yc, "resid_z": rc}, step.get("params") or {}, resolved
        )
    except (KeyError, ValueError) as e:
        raise HTTPException(422, f"step failed: {e}") from e
    ms = int((time.perf_counter() - t0) * 1000)

    col = {"getis_ord": output if output in ("gi_star", "gi_sig") else "gi_star",
           "hdbscan": "cluster_id", "grow_segmentation": "segment_id"}[op]
    value = np.nan_to_num(produced[col], nan=-1.0 if col in ("cluster_id", "segment_id") else np.nan)

    with tempfile.NamedTemporaryFile(suffix=".d1an", delete=False) as f:
        tmp = f.name
    try:
        write_d1an(tmp, {"x": xc.astype(np.float32), "y": yc.astype(np.float32),
                         "value": value.astype(np.float32)})
        out = open(tmp, "rb").read()
    finally:
        os.unlink(tmp)

    _viewport_lru[key] = (out, int(xc.size))
    while len(_viewport_lru) > RESULT_LRU_CAP:
        _viewport_lru.popitem(last=False)
    return Response(out, media_type="application/octet-stream",
                    headers={"Cache-Control": "no-store", "X-Diag-Cache": "miss",
                             "X-Diag-Ms": str(ms), "X-Diag-Viewport-N": str(xc.size)})
```

The LRU stores `(bytes, n)` so the hit path reports `X-Diag-Viewport-N` without re-parsing the D1AN header.

- [ ] **Step 4: Run the viewport suite + the existing preview suite** — `py -3 -m pytest plugins/diag-service/tests/ -q` → all green (preview tests untouched).

- [ ] **Step 5: Rebuild + smoke**

```bash
docker compose build diag-service && docker compose up -d diag-service
# after Task 1's rebake produces full.d1an:
curl -s -X POST http://localhost/diag/viewport -H "Authorization: Bearer $TOK" -H 'content-type: application/json' \
  -d '{"analysis_id":"<id>","bbox":[-40,-40,40,40],"step":{"op":"getis_ord","params":{"k":30}}}' -o /tmp/vp.d1an -w "%{http_code}\n"
```

- [ ] **Step 6: Commit**

```bash
git add plugins/diag-service/app/main.py plugins/diag-service/tests/test_viewport.py
git commit -m "feat(diag-service): POST /viewport — run one spatial step on a framed region at full res"
```

---

## Task 3: `diagViewport.ts` client + `DiagAnalysisOverlay.vue`

**Files:**
- Create: `packages/force-plotting/src/diagViewport.ts`, `diagViewport.test.ts`, `DiagAnalysisOverlay.vue`
- Modify: `packages/force-plotting/src/index.ts`

**Interfaces:**
- Consumes: `useForceHost().diagUrl`, `parseD1an`.
- Produces:
  ```ts
  export interface ViewportStep { op: 'getis_ord' | 'hdbscan' | 'grow_segmentation'; params: Record<string, unknown>; inputs?: Record<string, unknown>; }
  export interface ViewportResult { x: Float32Array; y: Float32Array; value: Float32Array; n: number; ms: number | null; }
  export function fetchViewportCompute(
    analysisId: string, bbox: [number, number, number, number], step: ViewportStep,
    opts?: { layers?: Record<string, unknown>; maxPoints?: number; output?: string; signal?: AbortSignal },
  ): Promise<ViewportResult>;
  ```
  - `DiagAnalysisOverlay.vue` props: `{ result: ViewportResult | null; mode: 'continuous' | 'categorical'; colormap?: string; pointSize?: number; camera: THREE.Camera | null }` — actually it shares the parent's scene/camera. Simpler: it is a child that the workbench mounts *inside* the same canvas as `DiagOctreeView`. **Decision:** `DiagAnalysisOverlay` is NOT its own canvas — it renders into a `<slot>`-provided THREE scene. To avoid a second WebGL context, the overlay is a method on `DiagOctreeView` instead (see Task 4). So `DiagAnalysisOverlay.vue` is dropped; the overlay lives in `DiagOctreeView`.

- [ ] **Step 1: Reconcile the overlay location**

The overlay MUST share `DiagOctreeView`'s WebGL context (a second `<canvas>` overlaid would need its own context, its own camera sync, and z-fighting management). So: `DiagOctreeView` gains an `analysisResult` prop (`ViewportResult | null`) and renders it as a second `THREE.Points` in its own scene, above the octree (`renderOrder = 1`, `z = 1`). **No `DiagAnalysisOverlay.vue` file.** Update this plan's File Structure accordingly; the overlay code goes in Task 4.

- [ ] **Step 2: Write the failing test** (`diagViewport.test.ts`)

```ts
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { setForceHost, resetForceHost, type ForceHost } from './host';
import { fetchViewportCompute } from './diagViewport';

const enc = () => {
  // minimal D1AN: magic, version, n=2, ncols=3, names x/y/value, then columns
  const n = 2, ncols = 3;
  const head = new ArrayBuffer(16 + ncols * 16 + ncols * n * 4);
  const dv = new DataView(head);
  dv.setUint32(0, 0x4431414e, true); dv.setUint32(4, 1, true);
  dv.setUint32(8, n, true); dv.setUint32(12, ncols, true);
  const names = ['x', 'y', 'value'];
  let off = 16;
  for (const nm of names) { for (let i = 0; i < nm.length; i++) dv.setUint8(off + i, nm.charCodeAt(i)); off += 16; }
  for (let c = 0; c < ncols; c++) for (let i = 0; i < n; i++) { dv.setFloat32(off, c * 10 + i, true); off += 4; }
  return head;
};

beforeEach(() => {
  resetForceHost();
  setForceHost({ diagUrl: '/diag', fetchCredentials: 'omit', authHeaders: () => ({}) } as ForceHost);
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
    ok: true, arrayBuffer: async () => enc(),
    headers: new Map([['X-Diag-Ms', '42'], ['X-Diag-Viewport-N', '2']]),
  }));
});

describe('fetchViewportCompute', () => {
  it('POSTs bbox + step and parses the D1AN response', async () => {
    const res = await fetchViewportCompute('a1', [0, 0, 10, 10],
      { op: 'getis_ord', params: { k: 30 } });
    expect(res.n).toBe(2);
    expect(Array.from(res.x)).toEqual([0, 1]);
    expect(Array.from(res.value)).toEqual([20, 21]);
    expect(res.ms).toBe(42);
    const body = JSON.parse((fetch as any).mock.calls[0][1].body);
    expect(body.bbox).toEqual([0, 0, 10, 10]);
    expect(body.step.op).toBe('getis_ord');
  });
});
```

(`headers` as a `Map` works for `.get`; if the real code uses `res.headers.get`, a `Map` satisfies it.)

- [ ] **Step 3: Implement `diagViewport.ts`**

```ts
import { parseD1an } from './diagAttrs';
import { useForceHost } from './host';

export interface ViewportStep {
	op: 'getis_ord' | 'hdbscan' | 'grow_segmentation';
	params: Record<string, unknown>;
	inputs?: Record<string, unknown>;
}
export interface ViewportResult {
	x: Float32Array;
	y: Float32Array;
	value: Float32Array;
	n: number;
	ms: number | null;
}

export async function fetchViewportCompute(
	analysisId: string,
	bbox: [number, number, number, number],
	step: ViewportStep,
	opts: { layers?: Record<string, unknown>; maxPoints?: number; output?: string; signal?: AbortSignal } = {},
): Promise<ViewportResult> {
	const host = useForceHost();
	const res = await fetch(`${host.diagUrl}/viewport`, {
		method: 'POST',
		signal: opts.signal,
		credentials: host.fetchCredentials,
		headers: { 'Content-Type': 'application/json', ...host.authHeaders() },
		body: JSON.stringify({
			analysis_id: analysisId,
			bbox,
			step,
			layers: opts.layers ?? null,
			max_points: opts.maxPoints ?? 1_000_000,
			output: opts.output ?? 'gi_star',
		}),
	});
	if (!res.ok) throw new Error(`diag viewport: ${res.status} ${(await res.text()).slice(0, 200)}`);
	const attrs = parseD1an(await res.arrayBuffer());
	const ms = res.headers.get('X-Diag-Ms');
	return {
		x: attrs.columns.x,
		y: attrs.columns.y,
		value: attrs.columns.value,
		n: attrs.n,
		ms: ms ? Number(ms) : null,
	};
}
```

- [ ] **Step 4: Export + test + typecheck**

```ts
// index.ts
export { fetchViewportCompute } from './diagViewport';
export type { ViewportStep, ViewportResult } from './diagViewport';
```
`npm test -w @d1/force-plotting -- diagViewport` (1 passed); `npm run typecheck -w @d1/force-plotting` (0).

- [ ] **Step 5: Commit**

```bash
git add packages/force-plotting/src/diagViewport.ts packages/force-plotting/src/diagViewport.test.ts packages/force-plotting/src/index.ts
git commit -m "feat(diag-ui): diagViewport client for POST /diag/viewport"
```

---

## Task 4: `DiagOctreeView.vue` — analysis overlay + paint port

**Files:**
- Modify: `packages/force-plotting/src/DiagOctreeView.vue`
- Test: headless (Task 6); typecheck must pass.

**Interfaces:**
- Consumes: `ViewportResult` (Task 3), `DiagLayer` (Phase E), `CLUSTER_PALETTE` / `clusterColorCss`.
- Produces:
  - new props: `analysisResult?: ViewportResult | null`, `analysisMode?: 'continuous' | 'categorical'`, `layers?: DiagLayer[]`, `activeLayerName?: string | null`, `paintMode?: 'off' | 'draw'`.
  - new emits: `(e: 'polygon', ring: [number, number][])`, `(e: 'bounds', b: [number, number, number, number])` — the x/y mm rectangle currently shown (`currentBounds()` already computes it). **Emitted undebounced** on every `controls` `change` and after `frameCamera()`; the workbench owns the single settle debounce (Task 5). The view must not own timing policy — two stacked debounces (here + workbench) compound latency and both restart on every zoom tick.
  - The octree base render (viridis `resid_z`) is unchanged. Above it:
    - `analysisPoints: THREE.Points` — flat geometry from `analysisResult.{x,y,value}`, `z = 1`, `renderOrder = 1`. `analysisMode === 'categorical'` → the `CLUSTER_PALETTE` shader path (id `< 0` grey), else viridis with a 1/99 range over `value`. Rebuilt on `analysisResult` change; hidden when null.
    - Paint overlay + draw `<div>` + `canvasToWorld` + draft `LineLoop` + per-layer `LineLoop` rings — **ported verbatim from `DiagScatter.vue`** (Phase E), which uses the identical top-down ortho unproject.
  - `controls.enabled = paintMode !== 'draw'` while drawing (OrbitControls contention — same fix as `DiagScatter`).

- [ ] **Step 1: Port the paint machinery**

Copy from `DiagScatter.vue` into `DiagOctreeView.vue`: `draft` ref, `ROLE_COLOR`, `canvasToWorld` (unproject via the existing `camera`), `redrawDraft`, `onPaintClick`, `finishRing`, `cancelRing`, `rebuildOverlay`, the `overlayGroup`/`draftLine` locals, the `watch([() => props.layers, () => props.activeLayerName], rebuildOverlay)`, the `watch(() => props.paintMode, ...)`, and the template `<div class="ds-paint" v-if="paintMode==='draw'" ...>` block + its CSS. Call `rebuildOverlay()` at the end of `load()` (after `scene.add(pco)`). Dispose in `onBeforeUnmount`.

- [ ] **Step 2: Add the analysis overlay**

```ts
let analysisPoints: THREE.Points | null = null;
function rebuildAnalysis() {
	if (analysisPoints) { scene?.remove(analysisPoints); analysisPoints.geometry.dispose(); (analysisPoints.material as THREE.Material).dispose(); analysisPoints = null; }
	const r = props.analysisResult;
	if (!r || r.n === 0 || !scene) { invalidate(); return; }
	const g = new THREE.BufferGeometry();
	const pos = new Float32Array(r.n * 3);
	for (let i = 0; i < r.n; i++) { pos[i*3] = r.x[i]; pos[i*3+1] = r.y[i]; pos[i*3+2] = 1; }
	g.setAttribute('position', new THREE.BufferAttribute(pos, 3));
	g.setAttribute('aValue', new THREE.BufferAttribute(Float32Array.from(r.value), 1));
	analysisPoints = new THREE.Points(g, makeAnalysisMaterial());   // categorical vs viridis per props.analysisMode
	analysisPoints.renderOrder = 1;
	analysisPoints.frustumCulled = false;
	scene.add(analysisPoints);
	invalidate();
}
watch(() => props.analysisResult, rebuildAnalysis);
watch(() => props.analysisMode, () => { if (analysisPoints) { (analysisPoints.material as THREE.Material).dispose(); analysisPoints.material = makeAnalysisMaterial(); invalidate(); } });
```

`makeAnalysisMaterial()` reuses `DiagScatter`'s shader (the `uCluster` / `uPalette` / viridis branch, minus the selection-dim path). Point size a touch larger than the octree's so the overlay reads on top.

- [ ] **Step 3: Emit bounds (undebounced — the workbench debounces)**

```ts
function emitBounds() {
	const b = currentBounds();
	emit('bounds', [b.xmin, b.ymin, b.xmax, b.ymax]);
}
```
Call `emitBounds()` from the existing `controls.addEventListener('change', ...)` path and after `frameCamera()`. No timer here — the workbench's `watch(viewportBounds)` (Task 5) is the single 600 ms settle debounce. Stacking a debounce here would compound latency and both timers would restart on every zoom frame.

- [ ] **Step 4: typecheck + existing package tests** — `npm run typecheck -w @d1/force-plotting && npm test -w @d1/force-plotting` → green (DiagOctreeView has no unit test; new props optional).

- [ ] **Step 5: Commit**

```bash
git add packages/force-plotting/src/DiagOctreeView.vue
git commit -m "feat(diag-ui): DiagOctreeView gains the analysis overlay + paint tools + bounds emit"
```

---

## Task 5: `DiagnosticsWorkbench.vue` — rewire to the full-res model

**Files:**
- Modify: `packages/force-plotting/src/DiagnosticsWorkbench.vue`, `packages/force-plotting/src/RecipePanel.vue`
- Test: headless (Task 6)

**Interfaces:**
- Consumes: `DiagOctreeView` (Task 4), `fetchViewportCompute` (Task 3), everything Phase F wired.
- Produces:
  - `DiagScatter` import removed. Spatial panel = `<DiagOctreeView>` with `:octree-path="`${diagPath}/full`"`, `:total-points="totalPoints"`, `:analysis-result="analysisResult"`, `:analysis-mode`, `:layers`, `:active-layer-name`, `:paint-mode`, `@polygon="onPolygon"`, `@bounds="onBounds"`.
  - `analysisResult = ref<ViewportResult | null>(null)`; `viewportBounds = ref<[number,number,number,number] | null>(null)`.
  - `channel` still drives which analysis the overlay shows: `getis_ord`→`gi_star`, `hdbscan`→`cluster_id`, `grow_segmentation`→`segment_id`. `analysisMode = channel is clusterId|segmentId ? 'categorical' : 'continuous'`.
  - **Gi\* auto:** `watch(viewportBounds, ...)` — fires only when `getis_ord` is enabled AND `channel.value === 'giStar'` (the analyst is actually looking at Gi\*); debounce 600 ms → `runViewport('getis_ord', { focus: false })`. Panning while studying a HDBSCAN result (`channel === 'clusterId'`) does NOT trigger a surprise recompute or yank the channel. Also `watch(channel, ...)`: switching back to `giStar` with stale/empty `analysisResult` kicks one `runViewport('getis_ord', { focus: false })`. `AbortController` per call.
  - **HDBSCAN / segmentation buttons:** `runViewport('hdbscan', { focus: true })` / `runViewport('grow_segmentation', { focus: true })` fired from RecipePanel buttons (new emit `run-step`) or a control in the Spatial toolbar.
  - `runViewport(op, { focus })`: reads `viewportBounds`, the step's params from `recipe.value`, `layersForRequest(layers.value)` for masks+seeds, calls `fetchViewportCompute`, sets `analysisResult`. Sets `channel` to the op's output **only when `focus` is true** (explicit button run) — an auto-Gi\* refresh never moves the channel selector.
  - `loadBaked()` no longer fetches `attrs.d1an` for a `DiagScatter` WorkingSet — but the Signal panel + Selection Inspector still need it. Keep `bakedWS` from `attrs.d1an` for those two; the Spatial panel ignores it.
  - Layout: `layout` array → Spatial `{x:0,y:0,w:9,h:12}`, Recipe `{x:9,y:0,w:3,h:7}`, Signal `{x:9,y:7,w:3,h:5}`. Recipe panel `collapsed` state (ref, default `false`; auto-collapse once `bakedWS` loads and no recipe edit pending — optional, keep simple: a manual chevron).
  - State strip: `viewport: {analysisResult?.n ?? '—'} pts · Gi* {autoArmed ? 'auto' : 'off'}` alongside the existing bake state.

- [ ] **Step 1: RecipePanel — per-spatial-step trigger + collapse**

Add to `RecipePanel.vue`:
- prop `collapsed?: boolean`, emit `update:collapsed`.
- emit `(e: 'run-step', op: string)`.
- In the step `<li>` for `getis_ord` / `hdbscan` / `grow_segmentation` when `s.on`: a line `<span class="scope-note">runs on the current view</span>`, and for `hdbscan` / `grow_segmentation` a `<button @click="emit('run-step', s.op)">Run on this view</button>`.
- A header chevron toggling `collapsed`; when collapsed, render only the header + footer (bake button + library).

- [ ] **Step 2: Workbench script rewire**

Remove the `DiagScatter` import and `<DiagScatter>` usage. Add:

```ts
import DiagOctreeView from './DiagOctreeView.vue';
import { fetchViewportCompute, type ViewportResult, type ViewportStep } from './diagViewport';

const analysisResult = ref<ViewportResult | null>(null);
const viewportBounds = ref<[number, number, number, number] | null>(null);
const viewportBusy = ref(false);
let viewportAbort: AbortController | null = null;

const OUTPUT_OF: Record<string, string> = { getis_ord: 'giStar', hdbscan: 'clusterId', grow_segmentation: 'segmentId' };
const analysisMode = computed<'continuous' | 'categorical'>(() =>
	channel.value === 'clusterId' || channel.value === 'segmentId' ? 'categorical' : 'continuous');

function stepParams(op: string): Record<string, unknown> {
	const s = recipe.value.steps.find((x) => x.op === op && x.on);
	return s ? { ...s.params } : {};
}
function stepInputs(op: string): Record<string, unknown> | undefined {
	const s = recipe.value.steps.find((x) => x.op === op && x.on);
	return s?.inputs;
}

async function runViewport(
	op: 'getis_ord' | 'hdbscan' | 'grow_segmentation',
	{ focus }: { focus: boolean } = { focus: true },
) {
	if (!viewportBounds.value) return;
	viewportAbort?.abort();
	const ac = new AbortController();
	viewportAbort = ac;
	viewportBusy.value = true;
	try {
		const step: ViewportStep = { op, params: stepParams(op), inputs: stepInputs(op) };
		const r = await fetchViewportCompute(props.analysisId, viewportBounds.value, step, {
			layers: layers.value.length ? layersForRequest(layers.value) : undefined,
			signal: ac.signal,
			output: op === 'getis_ord' ? 'gi_star' : undefined,
		});
		if (ac.signal.aborted) return;
		analysisResult.value = r;
		if (focus) channel.value = OUTPUT_OF[op] as typeof channel.value;
	} catch (e: unknown) {
		if (!ac.signal.aborted) previewErr.value = (e as { message?: string })?.message ?? 'viewport compute failed';
	} finally {
		if (viewportAbort === ac) viewportBusy.value = false;
	}
}

function onBounds(b: [number, number, number, number]) {
	viewportBounds.value = b;
}
// auto Gi* on settle — only while the analyst is actually viewing Gi*
let giTimer = 0;
function maybeAutoGi() {
	const gi = recipe.value.steps.find((s) => s.op === 'getis_ord' && s.on);
	if (!gi || channel.value !== 'giStar' || !viewportBounds.value) return;
	clearTimeout(giTimer);
	giTimer = window.setTimeout(() => runViewport('getis_ord', { focus: false }), 600);
}
watch(viewportBounds, maybeAutoGi);
watch(channel, (c) => { if (c === 'giStar' && !analysisResult.value) maybeAutoGi(); });
```

Keep `bakedWS` (from `attrs.d1an`) for the Signal chart + Selection Inspector; the debounced `runPreview` (256/rev diag-service preview) can stay for the Signal chart's `resid_z` tuning, OR be dropped.

**Ruling during execution:** `runPreview` / `previewWS` KEPT, not dropped. Dropping them would remove all live feedback for non-spatial param edits (radial_detrend, tsa) — the Signal panel would only update on bake. The path is already written and tested; keeping it costs a little workbench state and can be removed later if it proves confusing. `previewWS` now only feeds the Signal chart + Selection Inspector + ClusterTable (DiagScatter, its former consumer, is gone); the Spatial panel is the octree + viewport overlay and ignores it. Cost if wrong: minor extra complexity, easily reverted.

- [ ] **Step 3: Template + layout**

```vue
<WorkbenchPanel v-else-if="item.i === 'spatial'" title="Spatial" icon="scatter_plot">
	<DiagOctreeView
		:octree-path="`${diagPath}/full`"
		:channel="'residZ'"
		:colormap="'viridis'"
		:point-size="1.5"
		:total-points="totalPoints"
		:analysis-result="analysisResult"
		:analysis-mode="analysisMode"
		:layers="layers"
		:active-layer-name="activeLayerName"
		:paint-mode="drawing ? 'draw' : 'off'"
		@polygon="onPolygon"
		@bounds="onBounds"
	/>
	<template #footer>
		<div class="dw-spatial-footer">
			<LayerPanel ... unchanged ... />
			<select v-model="channel" class="dw-channel-select"> ... channelOptions ... </select>
			<span v-if="viewportBusy" class="dw-vp-busy">computing…</span>
		</div>
	</template>
</WorkbenchPanel>
```

`layout` ref → `[{x:0,y:0,w:9,h:12,i:'spatial'}, {x:9,y:0,w:3,h:7,i:'recipe'}, {x:9,y:7,w:3,h:5,i:'signal'}]`.

RecipePanel gets `:collapsed="recipeCollapsed"` `@update:collapsed="recipeCollapsed = $event"` `@run-step="runViewport"`.

- [ ] **Step 4: typecheck both workspaces** — `npm run typecheck -w @d1/force-plotting && npm run typecheck -w force-app-web` → 0 errors. (`DiagnosticsPage.vue` passes `diag-metrics`/`total-points` already; confirm `totalPoints` is populated — it comes from `diag_points`, which is the 256/rev count. For the octree LOD budget we want the FULL count. **Add:** `DiagnosticsPage` fetches `octree_points` or reads the `full/metadata.json` `points` — simplest: pass `diag_points * (fullRatio)`... no. Pass a generous fixed budget: `DiagOctreeView`'s `pointBudget` falls back to `15_000_000` when `totalPoints` is 0/absent — so pass `0` / omit `totalPoints` for the full octree and let the fallback cover it. Update Task 5 to omit `:total-points` or pass `15_000_000`.)

- [ ] **Step 5: Run package tests** — `npm test -w @d1/force-plotting` → green.

- [ ] **Step 6: Commit**

```bash
git add packages/force-plotting/src/DiagnosticsWorkbench.vue packages/force-plotting/src/RecipePanel.vue
git commit -m "feat(diag-ui): workbench renders the full-res octree; spatial steps run on the viewport"
```

---

## Task 6: end-to-end verification

- [ ] **Step 1: Full suites**

```bash
py -3 -m pytest tests/scripts/ plugins/diag-service/tests/ -q
npm test -w @d1/force-plotting
npm run typecheck -w @d1/force-plotting
npm run typecheck -w force-app-web
```
All green, 0 type errors. Record counts.

- [ ] **Step 2: Rebuild service, restart daemon, re-bake all cuts at `DIAG_VERSION=7`**

```bash
docker compose build diag-service && docker compose up -d diag-service
# restart the daemon (kill the PID in %TEMP%\d1_orch_err.log; relaunch with .env loaded)
```
Poll `SELECT id, diag_status, diag_version FROM machining_force_analysis WHERE diag_status IN ('done','pending','processing')` until every row is `done` at `diag_version = 7`. Serial, ~1 min/cut extra for the second PotreeConverter run.
Verify one cut: `infra/octrees/diag/<op>/full/` has `metadata.json` (finite `resid_z` min/max), `hierarchy.bin`, `octree.bin`, `full.d1an` (~7M rows, 3 cols).

- [ ] **Step 3: Direct `/diag/viewport` check on a real cut**

```bash
# whole-cloud bbox, HDBSCAN -> expect real clusters
curl -s -X POST http://localhost/diag/viewport -H "Authorization: Bearer $TOK" -H 'content-type: application/json' \
  -d '{"analysis_id":"<204800-pt cut id>","bbox":[-50,-50,50,50],"step":{"op":"hdbscan","params":{"min_cluster_size":20}},"max_points":800000}' \
  -o /tmp/vp.d1an -w "http %{http_code}\n"
```
Read `/tmp/vp.d1an` with `read_d1an` — assert `>1` distinct non-`-1` `value`, and `x`/`y` within the bbox. Time it (`X-Diag-Ms`).

- [ ] **Step 4: Headless workbench (playwright-core)**

Drive `/diagnostics`:
1. select a baked cut — the Spatial panel streams the **full-res octree** (point count in the LOD readout is millions, not 205k), coloured by `resid_z`.
2. pan/zoom to a sub-region → within ~1 s a `/diag/viewport` fires for `getis_ord` (check the request body's `bbox` matches the view), an overlay of Gi\* points appears.
3. RecipePanel → the `hdbscan` step shows a "Run on this view" button; click it → `/diag/viewport` with `op: hdbscan`, the overlay recolours categorically, the channel selector switches to `cluster_id`.
4. paint a mask polygon over part of the view → next recompute excludes it (overlay has a hole / those points `-1`).
5. add `grow_segmentation`, paint 2 seeds, bind them, click "Run on this view" → overlay shows 2 classes.
6. collapse the Recipe panel → Spatial takes the width.
7. screenshot at step 3; assert the canvas is not uniformly one colour and the LOD point count > 1_000_000.
8. **Record the actual fit-view LOD point count and frame behaviour** (console `pco.visibleNodes` / potree-core stats, or the LOD readout) before any param tuning — the `15_000_000` pointBudget fallback with `minNodePixelSize` 1 will stream a lot at fit-view on a 7M cloud. If it janks, note it as a follow-up (raise `minNodePixelSize`, or pass a real budget); do not tune diag params in this phase.

- [ ] **Step 5: fix anything broken, re-run Step 1, commit fixes**

- [ ] **Step 6: Finish the branch** — "I'm using the finishing-a-development-branch skill." Full suite on the merged result, base `main`, merge `--no-ff`, push, delete branch (per the standing "merge each phase as it finishes").

---

## Self-Review

**Spec coverage:**
- Component 1 (bake broadcasts `resid_z`) → Task 1. `np.interp`, `full.d1an` + `full/` octree, NaN handling, additive (no golden change). ✔
- Component 2 (`POST /diag/viewport`) → Task 2. Crop, stride, one step, authz on LRU hit, result LRU. ✔
- Component 3 (Spatial panel = octree + overlay) → Tasks 3 (client) + 4 (octree overlay). The `DiagAnalysisOverlay.vue` file was dropped in Task 3 Step 1 — the overlay shares `DiagOctreeView`'s context. File Structure updated. ✔
- Component 4 (recipe reframe) → Task 5. Base steps global; spatial steps viewport; Gi\* auto, HDBSCAN/seg button; channel selector fallback message. ✔
- Component 5 (layout) → Task 5 Step 3. Spatial hero w:9, Recipe collapsible, Signal in the rail. ✔
- Component 6 (painting on full-res) → Task 4 Step 1 (verbatim port from `DiagScatter`). Same coordinate space, no schema change. ✔
- Testing section → broadcast fidelity (T1), viewport crop/stride/parity/segmentation/authz (T2), golden untouched (T1 Step 7), octree URL (`${diagPath}/full`, T5 Step 3), auto-vs-button (T6 Step 4). ✔

**Placeholder scan:** Task 5 Step 4 has a genuine decision worked through inline (the `totalPoints` / LOD budget — resolved to "omit / pass 15M"). Task 3 Step 1 resolves the overlay-location fork explicitly. No "TBD" / "add error handling" / bare "write tests". Every code step has real code.

**Type consistency:**
- `ViewportResult { x, y, value: Float32Array; n; ms }` — Task 3 interface, `diagViewport.ts` impl, `DiagOctreeView` `analysisResult` prop, workbench `analysisResult` ref. ✔
- `ViewportStep { op, params, inputs? }` — Task 3, workbench `runViewport`, service request shape (Task 2 `step`). ✔
- Service `/viewport` response = D1AN `{x, y, value}` — `write_d1an` in Task 2, `parseD1an` → `attrs.columns.{x,y,value}` in Task 3. ✔
- `emit('bounds', [x0,y0,x1,y1])` (Task 4) → `onBounds(b)` → `viewportBounds` → `fetchViewportCompute(..., bbox, ...)` (Task 5) → service `bbox` (Task 2). Order `[x0,y0,x1,y1]` consistent throughout. ✔
- `OUTPUT_OF` maps op → camelCase channel key (`giStar`/`clusterId`/`segmentId`), matching `ChannelKey` from Phase F. ✔
- `broadcast_to_spiral(rev_grid, value_grid, revs_full)` — Task 1 interface, impl, and the `process_diag_row` call site. ✔

**Scope:** one phase, one merge. Server (T1, T2) and UI (T3–T5) share the D1AN response contract. `DiagScatter` retired from the workbench but kept exported — no consumer audit needed because `index.ts` still exports it.
