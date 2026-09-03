# Diagnostics Phase E — Paint Layers Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a user paint polygon regions on the Diagnostics analysis cloud that (a) exclude fixture/chuck artefacts from the compute (`mask`), (b) annotate regions for export (`label`), or (c) mark in/out examples for a future segmentation step (`seed`) — server-side rasterised, resolution-independent, and honoured by both the preview service and the orchestrator bake.

**Architecture:** A `diag_layer` table stores polygons in `(x, y)` millimetres (never a per-point array). `scripts/diag/layers.py` rasterises a polygon set against a coordinate pair server-side. `run_recipe` resolves each step's declared `inputs` bindings against a `layers` dict, rasterises, and hands the step a boolean array. `radial_detrend` holds masked points out of its fit and emits `NaN` for them; `getis_ord` and `hdbscan` are made non-finite-safe so the `NaN` propagates cleanly. The browser draws polygons and renders the overlay — it computes nothing. diag-service already accepts inline `layers`; the orchestrator bake gains a read of persisted `diag_layer` rows and folds their versions into `diag_recipe_hash`.

**Tech Stack:** Python 3.12 / numpy / scipy / scikit-learn (worker + service), FastAPI (service), dbmate SQL migrations, Vue 3 + TypeScript + Three.js (`@d1/force-plotting`), Directus items API for layer CRUD.

**Spec:** `docs/superpowers/specs/2026-09-01-diagnostics-recipe-workbench-design.md` (Component 3 — paint layers; Phase E row of the Phasing table)

## Global Constraints

- **Default-recipe equivalence is sacred.** A recipe with no `inputs` bindings and no `layers` must produce byte-identical D1AN columns to today. The golden-fixture tests (`tests/scripts/diag/`) must stay green with zero fixture regeneration. `fixtures/golden_default_recipe.npz` / `golden_envelope.npz` are NEVER regenerated — the capture script is deleted.
- **The browser computes nothing.** Rasterisation is server-side only, in one shared helper. The client sends polygon geometry; it never sends per-point arrays.
- **`NaN` is the D1AN masked-point value, never the octree/LAS value.** Masked points are `NaN` in `attrs.d1an` (the WorkingSet the workbench reads). But `process_diag_row` also writes those same columns as LAS float32 extra dims, and PotreeConverter derives per-attribute `min`/`max` for `metadata.json` from them — a `NaN` there makes `DiagOctreeView`'s `loadMeta` set `uRange` to `NaN` and the **entire** octree renders blank. So every column array MUST be sanitised (`np.nan_to_num(arr, nan=0.0)`) immediately before the LAS write in `process_diag_row`, with a comment that the D1AN file is authoritative for masked points and the octree is a downstream visual. The `fza` intensity ramp uses `np.nanmin`/`np.nanmax` for its lo/hi if any masked NaN could reach it.
- **Layer input bindings are `derived`-tier only.** `resolve_inputs` rasterises against `work["x"]/work["y"]` at the step's position. Before `angular_resample` those are cache-resolution arrays (wrong length and coordinate space); after, they are the angular grid. A binding on a `base`-tier step raises `ValueError` rather than silently rasterising wrong.
- **Geometry, not indices.** Layers are polygons in `(x, y)` mm. The resolution-independence test (same polygon → same physical region at 256 and 512 samples/rev) is the test that justifies this and must exist.
- **Coordinate space is the angular grid.** Polygons are drawn on `DiagScatter`'s WorkingSet, whose `x`/`y` are `run_recipe`'s angular-grid columns (produced by `frame_transform`), NOT the cache-resolution spiral. Rasterisation runs against `work["x"]/work["y"]` at the step's position in the pipeline, which are those same angular-grid coords. Every `diag_layer.geometry` comment and every docstring must state this.
- **Authorization parity with `32fb4b7`.** diag-service must authorize the caller against Directus for the analysis row on every `/preview` call including LRU hits. Phase E does not touch that guard; do not regress it.
- **`recipe_hash` schema care.** `scripts/diag/recipe.py`'s `_canonical` already folds per-step `inputs` into the hash. Changing what `inputs` contains at rest changes every hash — keep the at-rest `inputs` shape (a dict of `{binding_key: {"layer": name, "required": bool}}`) stable and documented.
- Migrations run via `docker run ghcr.io/amacneil/dbmate:2` on network `d1-database_d1net` with DSN host `@postgres:5432` (the Makefile's localhost DSN fails from a container). `MSYS_NO_PATHCONV=1` on Git-Bash.
- Python: `pytest` from repo root. Package: `npm test -w @d1/force-plotting`. Types: `npm run typecheck -w @d1/force-plotting` and `-w force-app-web`, both must be 0 errors.

---

## File Structure

**Create:**
- `db/migrations/20260903000108_diag_layer.sql` — the `diag_layer` table + Directus field registration for the workbench's use (the table is edited via the items API, not the admin UI, so no per-field interfaces — just enough for the API to expose it).
- `scripts/diag/layers.py` — `rasterize_polygons(geometry, x, y) -> np.ndarray[bool]`; `LayerGeometry` shape validation.
- `tests/scripts/diag/test_layers.py` — rasterisation correctness + resolution-independence.
- `tests/scripts/diag/test_masked_recipe.py` — a mask bound to `radial_detrend` changes `resid_z`/`gi_star`/`cluster_id` for masked points and leaves unmasked points identical to the unmasked run.
- `packages/force-plotting/src/diagLayers.ts` — `DiagLayer` / `LayerRole` / `LayerGeometry` types; `layersForRecipe()`; Directus CRUD (`fetchLayers`, `saveLayer`, `deleteLayer`).
- `packages/force-plotting/src/diagLayers.test.ts` — wire-format + `layersForRecipe` tests.
- `packages/force-plotting/src/LayerPanel.vue` — layer list: role badge, visibility toggle, rename, delete, "+ mask / + label / + seed".
- `packages/force-plotting/src/PaintOverlay.md` — NO. (Overlay lives inside DiagScatter; no separate file.)

**Modify:**
- `scripts/diag/registry.py` — add `Inputs` type alias + `resolve_inputs(step, layers, x, y)`; export from `scripts/diag/__init__.py` if it has an `__all__`.
- `scripts/diag/runner.py:136-159` — resolve each step's `inputs` before calling `spec.fn`; pass the resolved dict as the third arg instead of the raw `layers or {}`.
- `scripts/diag/ops.py:98-140` — `_op_radial_detrend` honours `inputs["mask"]`; `_op_getis_ord` and `_op_hdbscan` guard non-finite `resid_z`.
- `scripts/diag/recipe.py:23-45` — `DEFAULT_RECIPE`'s `radial_detrend` step gains an empty `inputs: {}` (explicit, documented) — NO, this changes the hash. Instead: document that a step with no `inputs` key is unmasked, and leave `DEFAULT_RECIPE` untouched.
- `plugins/diag-service/app/main.py:150-181` — validate inline `layers` geometry shape; pass through unchanged otherwise (already plumbed).
- `plugins/diag-service/tests/test_preview.py` — add a masked-preview test.
- `scripts/force_orchestrator.py` (`process_diag_row`, ~line 995 onward) — read `diag_layer` rows for the analysis, pass as `layers` to `run_recipe`, fold a layer fingerprint into the stored hash.
- `packages/force-plotting/src/DiagScatter.vue` — `paintMode` prop + `polygon` emit (draw), `layers` prop (overlay render), non-finite-safe `packValue`/`percentileRange`.
- `packages/force-plotting/src/selection.ts` — `clusterStats` / `computeStats` skip non-finite points.
- `packages/force-plotting/src/DiagnosticsWorkbench.vue` — LayerPanel in the Spatial panel, paint-tool toggle, send `layers` with preview, bind a mask into the recipe `inputs` for the preview call.
- `packages/force-plotting/src/index.ts` — export the new symbols.
- `apps/force-app/web/src/force/StandaloneDiagnosticsWorkbench.vue` + `force/DiagnosticsPage.vue` — pass-through; persist layers on bake.

---

## Task 1: `diag_layer` table + Directus registration

**Files:**
- Create: `db/migrations/20260903000108_diag_layer.sql`
- Test: manual `psql \d diag_layer` + `docker compose exec directus ...` schema check

**Interfaces:**
- Produces: table `diag_layer(layer_id uuid pk, analysis_id uuid fk→machining_force_analysis on delete cascade, name text, role text check in ('mask','label','seed'), geometry jsonb, value jsonb null, version int default 1, created_at, updated_at, unique(analysis_id,name))`.

- [ ] **Step 1: Write the migration**

```sql
-- migrate:up
-- Hand-painted regions for the Diagnostics Workbench. A layer is POLYGONS IN (x, y)
-- MILLIMETRES on the angular-resampled analysis grid (frame_transform's output — the same
-- coordinates DiagScatter renders), NOT a per-point array: geometry survives re-baking at
-- any samples_per_rev, whereas a dense mask is welded to the current point count/order.
-- Rasterisation to per-point booleans happens server-side in scripts/diag/layers.py.
CREATE TABLE IF NOT EXISTS diag_layer (
    layer_id     UUID        NOT NULL DEFAULT uuid_generate_v4(),
    analysis_id  UUID        NOT NULL REFERENCES machining_force_analysis(id) ON DELETE CASCADE,
    name         TEXT        NOT NULL,
    role         TEXT        NOT NULL,
    geometry     JSONB       NOT NULL,
    value        JSONB,
    version      INTEGER     NOT NULL DEFAULT 1,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT diag_layer_pkey PRIMARY KEY (layer_id),
    CONSTRAINT diag_layer_role_ck CHECK (role IN ('mask', 'label', 'seed')),
    CONSTRAINT diag_layer_name_uq UNIQUE (analysis_id, name)
);
CREATE INDEX IF NOT EXISTS diag_layer_analysis_idx ON diag_layer (analysis_id);

-- Register the collection with Directus so the items API exposes it (the workbench does
-- layer CRUD through /items/diag_layer). Mirrors how diag_recipes was registered.
INSERT INTO directus_collections (collection, icon, note, hidden, singleton)
SELECT 'diag_layer', 'gesture', 'Hand-painted mask/label/seed regions for a diagnostics cut.', false, false
WHERE NOT EXISTS (SELECT 1 FROM directus_collections WHERE collection = 'diag_layer');

-- NOTE: directus_fields.special is text[] (verify with `\d directus_fields` before running).
-- Pass each as a Postgres array literal, NULL where the field has no special behaviour.
INSERT INTO directus_fields (collection, field, special, interface, readonly, hidden, sort)
SELECT collection, field, special::text[], interface, readonly, hidden, sort FROM (VALUES
    ('diag_layer', 'layer_id',    '{uuid}',         'input',               true,  true,  1),
    ('diag_layer', 'analysis_id', NULL,             'select-dropdown-m2o', false, false, 2),
    ('diag_layer', 'name',        NULL,             'input',               false, false, 3),
    ('diag_layer', 'role',        NULL,             'select-dropdown',     false, false, 4),
    ('diag_layer', 'geometry',    '{cast-json}',    'input-code',          false, false, 5),
    ('diag_layer', 'value',       '{cast-json}',    'input-code',          false, false, 6),
    ('diag_layer', 'version',     NULL,             'input',               false, false, 7),
    ('diag_layer', 'created_at',  '{date-created}', 'datetime',            true,  false, 8),
    ('diag_layer', 'updated_at',  '{date-updated}', 'datetime',            true,  false, 9)
) v(collection, field, special, interface, readonly, hidden, sort)
WHERE NOT EXISTS (SELECT 1 FROM directus_fields f WHERE f.collection = 'diag_layer' AND f.field = v.field);

-- migrate:down
DELETE FROM directus_fields WHERE collection = 'diag_layer';
DELETE FROM directus_collections WHERE collection = 'diag_layer';
DROP TABLE IF EXISTS diag_layer;
```

- [ ] **Step 2: Confirm `uuid_generate_v4()` and the `directus_fields.special` type**

Run: `grep -rl "uuid_generate_v4\|uuid-ossp" db/migrations/ | head -1` — expect a hit (`diag_recipes` uses it). If NOT, prepend `CREATE EXTENSION IF NOT EXISTS "uuid-ossp";`.
Run: `docker compose exec -T postgres psql -U directus -d directus -c "\d directus_fields" | grep -E "special|options"` — confirm `special` is `text[]` (the migration casts to `text[]`) and note whether `options` is `json`/`jsonb` (this migration omits `options`, so only relevant if a later edit adds it).

- [ ] **Step 3: Run the migration**

Run:
```bash
MSYS_NO_PATHCONV=1 docker run --rm --network d1-database_d1net \
  -v "$PWD/db/migrations:/db/migrations" ghcr.io/amacneil/dbmate:2 \
  -u "postgres://directus:$PGPASS@postgres:5432/directus?sslmode=disable" up
```
(Use the same DSN form the recipe-engine phase used; read the password from the compose env, do not hardcode.)
Expected: `Applying: 20260903000108_diag_layer.sql`

- [ ] **Step 4: Verify live**

Run: `docker compose exec -T postgres psql -U directus -d directus -c "\d diag_layer"`
Expected: table with the 9 columns, the role check, and the `(analysis_id, name)` unique constraint.

- [ ] **Step 5: Restart Directus so its schema cache picks up the collection**

Run: `docker compose restart directus` then wait for healthy.
Verify: `curl -s -H "Authorization: Bearer $ADMIN_TOKEN" http://localhost:8055/items/diag_layer | head -c 200` returns `{"data":[]}` not a 403/404.

- [ ] **Step 6: Commit**

```bash
git add db/migrations/20260903000108_diag_layer.sql
git commit -m "feat(diag): diag_layer table for hand-painted mask/label/seed regions"
```

---

## Task 2: `scripts/diag/layers.py` — polygon rasteriser

**Files:**
- Create: `scripts/diag/layers.py`
- Test: `tests/scripts/diag/test_layers.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces:
  - `LayerGeometry = dict` with shape `{"polygons": list[list[[float, float]]]}` (a list of rings; each ring a list of `[x, y]` vertices in mm).
  - `def validate_geometry(geometry: dict) -> None` — raises `ValueError` on a malformed shape.
  - `def rasterize_polygons(geometry: dict, x: np.ndarray, y: np.ndarray) -> np.ndarray` — returns a boolean array, length `x.size`, `True` where the point is inside ANY ring (even-odd fill, union of rings). `x` and `y` are the angular-grid mm coordinates.

- [ ] **Step 1: Write the failing test**

```python
# tests/scripts/diag/test_layers.py
import numpy as np
import pytest
from diag.layers import rasterize_polygons, validate_geometry


def _square(cx, cy, half):
    return [[cx - half, cy - half], [cx + half, cy - half],
            [cx + half, cy + half], [cx - half, cy + half]]


def test_rasterize_marks_points_inside_a_single_polygon():
    geom = {"polygons": [_square(0.0, 0.0, 1.0)]}
    x = np.array([0.0, 0.5, 2.0, -0.9])
    y = np.array([0.0, 0.5, 2.0, 0.9])
    inside = rasterize_polygons(geom, x, y)
    assert inside.tolist() == [True, True, False, True]


def test_rasterize_is_the_union_of_multiple_polygons():
    geom = {"polygons": [_square(-5.0, 0.0, 1.0), _square(5.0, 0.0, 1.0)]}
    x = np.array([-5.0, 0.0, 5.0])
    y = np.array([0.0, 0.0, 0.0])
    assert rasterize_polygons(geom, x, y).tolist() == [True, False, True]


def test_rasterize_is_resolution_independent():
    # The SAME polygon must select the SAME physical disc regardless of how densely the
    # grid is sampled -- this is the property that justifies storing geometry over indices.
    geom = {"polygons": [_square(3.0, -2.0, 1.5)]}
    rng = np.random.default_rng(0)

    def fraction_inside(n):
        x = rng.uniform(-10, 10, n)
        y = rng.uniform(-10, 10, n)
        return rasterize_polygons(geom, x, y).mean()

    lo = fraction_inside(20_000)
    hi = fraction_inside(200_000)
    assert abs(lo - hi) < 0.01


def test_validate_geometry_rejects_malformed_shapes():
    for bad in [{}, {"polygons": "x"}, {"polygons": [[[0.0]]]},
                {"polygons": [[[0.0, 0.0], [1.0, 0.0]]]}]:  # <3 vertices
        with pytest.raises(ValueError):
            validate_geometry(bad)


def test_rasterize_empty_geometry_selects_nothing():
    out = rasterize_polygons({"polygons": []}, np.zeros(5), np.zeros(5))
    assert out.tolist() == [False] * 5
```

- [ ] **Step 2: Run it, verify it fails**

Run: `pytest tests/scripts/diag/test_layers.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'diag.layers'`

- [ ] **Step 3: Implement**

```python
# scripts/diag/layers.py
"""Server-side rasterisation of hand-painted polygon layers.

A layer's geometry is polygons in (x, y) millimetres on the ANGULAR-RESAMPLED analysis grid
-- the coordinate space frame_transform produces and DiagScatter renders. Rasterising means
testing each analysis-grid point against those polygons to get a boolean array the recipe's
steps consume. The browser draws the polygons; this module is the only place they become
per-point booleans.
"""
from __future__ import annotations

import numpy as np

# {"polygons": [ [ [x, y], [x, y], ... ], ... ]} -- a list of rings, each >= 3 vertices.
LayerGeometry = dict


def validate_geometry(geometry: dict) -> None:
    if not isinstance(geometry, dict) or "polygons" not in geometry:
        raise ValueError("layer geometry must be a dict with a 'polygons' key")
    polys = geometry["polygons"]
    if not isinstance(polys, list):
        raise ValueError("geometry['polygons'] must be a list of rings")
    for ring in polys:
        if not isinstance(ring, list) or len(ring) < 3:
            raise ValueError("each polygon ring needs >= 3 vertices")
        for v in ring:
            if (not isinstance(v, (list, tuple)) or len(v) != 2
                    or not all(isinstance(c, (int, float)) for c in v)):
                raise ValueError("each vertex must be [x, y] numbers")


def _ring_contains(ring: np.ndarray, x: np.ndarray, y: np.ndarray) -> np.ndarray:
    """Vectorised even-odd ray-cast: which of (x, y) fall inside `ring` (shape (m, 2))."""
    inside = np.zeros(x.shape, dtype=bool)
    xs, ys = ring[:, 0], ring[:, 1]
    m = len(ring)
    j = m - 1
    for i in range(m):
        xi, yi, xj, yj = xs[i], ys[i], xs[j], ys[j]
        crosses = (yi > y) != (yj > y)
        # guard against a horizontal edge (yj == yi) -> crosses is False there anyway
        with np.errstate(divide="ignore", invalid="ignore"):
            xints = (xj - xi) * (y - yi) / (yj - yi) + xi
        hit = crosses & (x < xints)
        inside ^= hit
        j = i
    return inside


def rasterize_polygons(geometry: dict, x: np.ndarray, y: np.ndarray) -> np.ndarray:
    validate_geometry(geometry)
    x = np.asarray(x, dtype=np.float64)
    y = np.asarray(y, dtype=np.float64)
    out = np.zeros(x.shape, dtype=bool)
    for ring in geometry["polygons"]:
        out |= _ring_contains(np.asarray(ring, dtype=np.float64), x, y)
    return out
```

- [ ] **Step 4: Run tests, verify pass**

Run: `pytest tests/scripts/diag/test_layers.py -v`
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add scripts/diag/layers.py tests/scripts/diag/test_layers.py
git commit -m "feat(diag): server-side polygon rasteriser for paint layers"
```

---

## Task 3: `run_recipe` resolves step `inputs` bindings

**Files:**
- Modify: `scripts/diag/registry.py`, `scripts/diag/runner.py:136-159`
- Test: `tests/scripts/diag/test_runner_inputs.py` (create)

**Interfaces:**
- Consumes: `rasterize_polygons`, `validate_geometry` (Task 2).
- Produces:
  - `registry.Inputs = dict[str, np.ndarray | None]` — the RESOLVED shape a step's `fn` receives (was the raw `layers` dict).
  - `registry.resolve_inputs(step: dict, layers: dict | None, x, y) -> Inputs` — for each `(key, binding)` in `step.get("inputs", {})`, look up `layers[binding["layer"]]`, rasterise its `geometry` against `(x, y)`, and return `{key: bool_array}`. Missing layer + `binding.get("required")` → `ValueError`. Missing layer + not required → `{key: None}`. `layers` value shape: `{"role": str, "geometry": {...}, "value": {...} | None, "version": int}`.
  - **Tier gate:** `resolve_inputs` takes the step's `STEPS[op].tier`; if it is `"base"` and the step declares `inputs`, raise `ValueError("layer bindings are only valid on derived-tier steps; '<op>' is base")`. This prevents a binding rasterising against the pre-resample cache coords. `DEFAULT_RECIPE` binds nothing, so this never fires today.
  - After rasterising, `resolve_inputs` asserts `bool_array.shape == np.asarray(x).shape` and raises a clear error on mismatch (a guard for the case above slipping through).
  - At-rest `inputs` shape on a recipe step: `{"mask": {"layer": "chuck_mark", "required": false}}`. Documented in `recipe.py`'s module docstring.

- [ ] **Step 1: Write the failing test**

```python
# tests/scripts/diag/test_runner_inputs.py
import numpy as np
import pytest
from diag.registry import resolve_inputs


def _sq(h):
    return [[-h, -h], [h, -h], [h, h], [-h, h]]


def test_resolve_inputs_rasterizes_a_bound_layer():
    step = {"op": "radial_detrend", "on": True,
            "inputs": {"mask": {"layer": "chuck", "required": False}}}
    layers = {"chuck": {"role": "mask", "geometry": {"polygons": [_sq(1.0)]},
                        "value": {"mode": "exclude"}, "version": 1}}
    x = np.array([0.0, 5.0])
    y = np.array([0.0, 5.0])
    out = resolve_inputs(step, layers, x, y)
    assert out["mask"].tolist() == [True, False]


def test_resolve_inputs_no_binding_returns_empty():
    assert resolve_inputs({"op": "tsa", "on": True}, None, np.zeros(3), np.zeros(3)) == {}


def test_resolve_inputs_missing_optional_layer_is_none():
    step = {"op": "radial_detrend", "inputs": {"mask": {"layer": "absent"}}}
    out = resolve_inputs(step, {}, np.zeros(3), np.zeros(3))
    assert out == {"mask": None}


def test_resolve_inputs_missing_required_layer_raises():
    step = {"op": "radial_detrend", "inputs": {"mask": {"layer": "absent", "required": True}}}
    with pytest.raises(ValueError, match="absent"):
        resolve_inputs(step, {}, np.zeros(3), np.zeros(3))
```

- [ ] **Step 2: Run it, verify it fails**

Run: `pytest tests/scripts/diag/test_runner_inputs.py -v`
Expected: FAIL — `ImportError: cannot import name 'resolve_inputs'`

- [ ] **Step 3: Add `resolve_inputs` to `registry.py`**

```python
# scripts/diag/registry.py -- add near the Columns type alias
from .layers import rasterize_polygons  # noqa: E402  (layers.py has no registry import -> no cycle)

Inputs = dict[str, "np.ndarray | None"]


def resolve_inputs(step: dict, layers: dict | None, x, y) -> Inputs:
    """Resolve a step's declared `inputs` bindings into per-point boolean arrays.

    At rest a binding is {"layer": <name>, "required": <bool>}. This looks the named layer
    up in `layers` (the request/DB-supplied {name: {role, geometry, value, version}} dict),
    rasterises its polygons against (x, y) -- the angular-grid coords AT THIS STEP -- and
    hands the step {key: bool_array}. True = the point is inside the painted region.
    """
    bindings = step.get("inputs") or {}
    out: Inputs = {}
    if bindings and STEPS[step["op"]].tier == "base":
        raise ValueError(
            f"layer bindings are only valid on derived-tier steps; '{step['op']}' is base"
        )
    xa = np.asarray(x)
    for key, binding in bindings.items():
        name = binding.get("layer")
        layer = (layers or {}).get(name)
        if layer is None:
            if binding.get("required"):
                raise ValueError(
                    f"step '{step.get('op')}' requires layer '{name}' but the cut has none"
                )
            out[key] = None
            continue
        arr = rasterize_polygons(layer["geometry"], x, y)
        if arr.shape != xa.shape:
            raise ValueError(
                f"layer '{name}' rasterised to {arr.shape}, step '{step['op']}' expects {xa.shape}"
            )
        out[key] = arr
    return out
```

- [ ] **Step 4: Wire it into `runner.py`**

Replace the `spec.fn` call site (`runner.py:159`):

```python
        # Resolve this step's painted-layer bindings (if any) into per-point boolean arrays
        # against the CURRENT angular-grid coords. A step with no `inputs` key gets {} --
        # byte-for-byte identical to the pre-Phase-E behaviour where every step got `layers`
        # raw and no step read it.
        resolved = resolve_inputs(s, layers, work.get("x"), work.get("y"))
        produced, frag = spec.fn(work, params, resolved)
```

Add `resolve_inputs` to the `from .registry import ...` line at the top of `runner.py`.

- [ ] **Step 5: Run the new test + the full diag suite**

Run: `pytest tests/scripts/diag/test_runner_inputs.py tests/scripts/diag/ -v`
Expected: new file 4 passed; **every golden/equivalence test still passes** (a recipe with no `inputs` → `resolved == {}`, ops ignore it).

- [ ] **Step 6: Commit**

```bash
git add scripts/diag/registry.py scripts/diag/runner.py tests/scripts/diag/test_runner_inputs.py
git commit -m "feat(diag): run_recipe resolves per-step paint-layer input bindings"
```

---

## Task 4: `radial_detrend` masks; `getis_ord` / `hdbscan` are non-finite-safe

**Files:**
- Modify: `scripts/diag/ops.py` (`_op_radial_detrend`, `_op_getis_ord`, `_op_hdbscan`)
- Test: `tests/scripts/diag/test_masked_recipe.py` (create)

**Interfaces:**
- Consumes: resolved `inputs["mask"]` — a boolean array (`True` = excluded) or `None`, from Task 3.
- Masked points are `NaN` in the returned `resid_z`/`gi_star` columns (and `attrs.d1an`). The LAS/octree sanitisation of that `NaN` is **Task 11**, not here — this task's tests assert `NaN` in the `run_recipe` output directly.
- Produces:
  - `_op_radial_detrend`: when `inputs.get("mask")` is a boolean array, points where it is `True` are held out of the radial-bin fit AND assigned `resid_z = np.nan`. Unmasked points: fit and values identical to the no-mask run.
  - `_op_getis_ord`: computes only over `np.isfinite(resid_z)` points; non-finite points get `gi_star = np.nan`, `gi_sig = 0`.
  - `_op_hdbscan`: `grid_reduce` / clustering see only finite points; non-finite → `cluster_id = -1`, `glosh = 0`.
- The `_radial_detrend` low-level function in `ops.py`'s imports is NOT modified — masking is done in the `@step` wrapper.

- [ ] **Step 1: Write the failing test**

```python
# tests/scripts/diag/test_masked_recipe.py
import numpy as np
from diag.recipe import DEFAULT_RECIPE
from diag.runner import run_recipe
from tests.scripts.diag.conftest import synthetic_cut  # seeded synthetic


def _bind_mask(recipe, polygons):
    r = {"steps": [dict(s) for s in recipe["steps"]]}
    for s in r["steps"]:
        if s["op"] == "radial_detrend":
            s["inputs"] = {"mask": {"layer": "art", "required": False}}
    layers = {"art": {"role": "mask", "geometry": {"polygons": polygons},
                      "value": {"mode": "exclude"}, "version": 1}}
    return r, layers


def test_mask_nans_covered_points_and_leaves_the_rest_identical():
    cols = synthetic_cut()
    base, _ = run_recipe(DEFAULT_RECIPE, dict(cols))

    # a polygon covering roughly the outer third of the disc
    poly = [[-100.0, -100.0], [100.0, -100.0], [100.0, 100.0], [-100.0, 100.0]]
    # shrink to a band that only covers SOME points: use a small square near one edge
    x = base["x"]; y = base["y"]
    cx, cy = float(x.max()) - 1.0, float(y[np.argmax(x)])
    sq = [[cx - 2, cy - 2], [cx + 2, cy - 2], [cx + 2, cy + 2], [cx - 2, cy + 2]]
    recipe, layers = _bind_mask(DEFAULT_RECIPE, [sq])
    masked, _ = run_recipe(recipe, dict(cols), layers=layers)

    from diag.layers import rasterize_polygons
    covered = rasterize_polygons({"polygons": [sq]}, base["x"], base["y"])
    assert covered.any() and not covered.all()

    assert np.all(np.isnan(masked["resid_z"][covered]))
    # unmasked points: resid_z unchanged (the fit excluded the covered band, so allow a
    # small tolerance -- the bins differ slightly -- but the vast majority are close)
    good = ~covered & np.isfinite(masked["resid_z"])
    assert np.corrcoef(masked["resid_z"][good], base["resid_z"][good])[0, 1] > 0.98


def test_downstream_channels_are_finite_safe_under_a_mask():
    cols = synthetic_cut()
    base, _ = run_recipe(DEFAULT_RECIPE, dict(cols))
    x = base["x"]
    cx = float(x.max()) - 1.0
    sq = [[cx - 2, -50], [cx + 2, -50], [cx + 2, 50], [cx - 2, 50]]
    recipe, layers = _bind_mask(DEFAULT_RECIPE, [sq])
    masked, _ = run_recipe(recipe, dict(cols), layers=layers)
    from diag.layers import rasterize_polygons
    covered = rasterize_polygons({"polygons": [sq]}, base["x"], base["y"])
    assert np.all(np.isnan(masked["gi_star"][covered]))
    assert np.all(masked["gi_sig"][covered] == 0)
    assert np.all(masked["cluster_id"][covered] == -1)
    # every non-covered gi_star / cluster_id value is finite
    assert np.all(np.isfinite(masked["gi_star"][~covered]))
```

(If `synthetic_cut` is not importable that way, match `conftest.py`'s actual fixture name/usage — it is a pytest fixture, so take it as a test arg instead of importing.)

- [ ] **Step 2: Run it, verify it fails**

Run: `pytest tests/scripts/diag/test_masked_recipe.py -v`
Expected: FAIL — masked points are not `NaN` (mask ignored).

- [ ] **Step 3: Implement the mask in `_op_radial_detrend`**

```python
@step("radial_detrend", produces=["resid_z"],
      requires=["tsa_resid", "x", "y"], tier="derived")
def _op_radial_detrend(cols: Columns, params: dict, inputs: dict):
    r = np.hypot(cols["x"], cols["y"])
    tsa = cols["tsa_resid"]
    mask = inputs.get("mask")  # True = excluded region (a fixture/chuck artefact)
    if mask is not None and np.any(mask):
        keep = ~np.asarray(mask, dtype=bool)
        z = np.full(r.shape, np.nan)
        z[keep] = _radial_detrend(
            r[keep], tsa[keep],
            n_bins=int(params.get("n_bins", 200)),
            min_per_bin=int(params.get("min_per_bin", 8)),
        )
    else:
        z = _radial_detrend(
            r, tsa,
            n_bins=int(params.get("n_bins", 200)),
            min_per_bin=int(params.get("min_per_bin", 8)),
        )
    finite = z[np.isfinite(z)]
    return {"resid_z": z}, {
        "resid_z_p99": float(np.percentile(np.abs(finite), 99)) if finite.size else 0.0,
    }
```

- [ ] **Step 4: Make `_op_getis_ord` finite-safe**

```python
@step("getis_ord", produces=["gi_star", "gi_sig"],
      requires=["x", "y", "resid_z"], tier="derived")
def _op_getis_ord(cols: Columns, params: dict, inputs: dict):
    k = int(params.get("k", 30))
    alpha = float(params.get("alpha", 0.05))
    z = cols["resid_z"]
    n = z.size
    fin = np.isfinite(z)
    gi = np.full(n, np.nan)
    sig = np.zeros(n)
    if int(fin.sum()) > k:
        g, p = getis_ord_gi_star(cols["x"][fin], cols["y"][fin], z[fin], k=k)
        gi[fin] = g
        sig[fin] = benjamini_hochberg(p, alpha=alpha).astype(np.float64)
    return {"gi_star": gi, "gi_sig": sig}, {}
```

- [ ] **Step 5: Make `_op_hdbscan` finite-safe**

```python
@step("hdbscan", produces=["cluster_id", "glosh"],
      requires=["x", "y", "resid_z"], tier="derived")
def _op_hdbscan(cols: Columns, params: dict, inputs: dict):
    target = int(params.get("grid_target", 20000))
    min_size = int(params.get("min_cluster_size", 10))
    z = cols["resid_z"]
    n = z.size
    fin = np.isfinite(z)
    cluster_id = np.full(n, -1.0)
    glosh = np.zeros(n)
    if int(fin.sum()) >= min_size:
        xr, yr, vr, cell_id = grid_reduce(cols["x"][fin], cols["y"][fin], z[fin], target_n=target)
        if xr.size >= min_size:
            labels, gl = cluster_hdbscan(xr, yr, vr, min_cluster_size=min_size)
            cid_fin, gl_fin = assign_from_grid(cell_id, labels, gl)
            cluster_id[fin] = cid_fin
            glosh[fin] = gl_fin
    return {"cluster_id": cluster_id, "glosh": glosh}, {}
```

- [ ] **Step 6: Run the masked test + the FULL diag suite (equivalence guard)**

Run: `pytest tests/scripts/diag/ -v`
Expected: `test_masked_recipe.py` passes; **all golden/equivalence tests still pass** — the no-mask code path in every op above is unchanged (`assign_from_grid` on the full `fin=all-True` array is identical to today; `np.full(n, -1.0)` + fill == today's shape).
If a golden test drifts: STOP. The no-mask branch must be byte-identical. Diff the branch against the original and fix.

- [ ] **Step 7: Commit**

```bash
git add scripts/diag/ops.py tests/scripts/diag/test_masked_recipe.py
git commit -m "feat(diag): radial_detrend honours a mask; getis_ord/hdbscan finite-safe"
```

---

## Task 5: diag-service validates and forwards inline layers

**Files:**
- Modify: `plugins/diag-service/app/main.py:150-181`
- Test: `plugins/diag-service/tests/test_preview.py` (add cases)

**Interfaces:**
- Consumes: `resolve_inputs` behaviour (Task 3), `validate_geometry` (Task 2).
- Produces: `/diag/preview` accepts `layers: {name: {role, geometry, value?, version?}}` in the POST body (already read at `main.py:152`). Each layer's `geometry` is validated with `validate_geometry`; a bad shape → `HTTPException(422, ...)`. The `layers_key` in the LRU key already incorporates `layers` — confirm it survives a `geometry` dict (it does: `repr(sorted(...))`).

- [ ] **Step 0: Read the existing test fixtures FIRST**

Run: `sed -n '1,60p' plugins/diag-service/tests/conftest.py` and skim `test_preview.py`'s existing `test_preview_approximates_a_full_bake`. Note the ACTUAL fixture names (client/app fixture, the analysis-id source, how auth headers are supplied). The test code below uses placeholder names `client` / `seeded_analysis` — rename to match before running, or the first `pytest` invocation wastes a full cycle.

- [ ] **Step 1: Write the failing test**

```python
# plugins/diag-service/tests/test_preview.py -- add (fixture names per Step 0)

def test_preview_applies_an_inline_mask(client, seeded_analysis):
    # seeded_analysis: the fixture that already backs test_preview_approximates_a_full_bake
    body_unmasked = {"analysis_id": seeded_analysis.id, "recipe": seeded_analysis.recipe}
    r0 = client.post("/preview", json=body_unmasked, headers=seeded_analysis.auth)
    assert r0.status_code == 200

    recipe = json.loads(json.dumps(seeded_analysis.recipe))
    for s in recipe["steps"]:
        if s["op"] == "radial_detrend":
            s["inputs"] = {"mask": {"layer": "art", "required": False}}
    body_masked = {
        "analysis_id": seeded_analysis.id,
        "recipe": recipe,
        "layers": {"art": {"role": "mask",
                           "geometry": {"polygons": [[[-1e9, -1e9], [1e9, -1e9],
                                                      [1e9, 1e9], [-1e9, 1e9]]]},
                           "value": {"mode": "exclude"}, "version": 1}},
    }
    r1 = client.post("/preview", json=body_masked, headers=seeded_analysis.auth)
    assert r1.status_code == 200
    # an all-covering mask -> every resid_z is NaN -> D1AN encodes NaN; assert the columns differ
    assert r0.content != r1.content


def test_preview_rejects_malformed_layer_geometry(client, seeded_analysis):
    body = {
        "analysis_id": seeded_analysis.id,
        "recipe": seeded_analysis.recipe,
        "layers": {"bad": {"role": "mask", "geometry": {"polygons": "nope"}}},
    }
    r = client.post("/preview", json=body, headers=seeded_analysis.auth)
    assert r.status_code == 422
```

(Adjust fixture names to whatever `test_preview.py` already uses — reuse its existing analysis/auth fixtures, do not invent new ones.)

- [ ] **Step 2: Run it, verify it fails**

Run: `pytest plugins/diag-service/tests/test_preview.py -v -k "mask or malformed"`
Expected: FAIL — malformed geometry returns 500 (unhandled `ValueError`) or 200, not 422.

- [ ] **Step 3: Implement validation**

In `main.py`, right after `layers = body.get("layers") or None`:

```python
    if layers:
        from diag.layers import validate_geometry
        if not isinstance(layers, dict):
            raise HTTPException(422, "layers must be an object keyed by layer name")
        for lname, layer in layers.items():
            try:
                validate_geometry((layer or {}).get("geometry") or {})
            except (ValueError, AttributeError) as e:
                raise HTTPException(422, f"layer '{lname}': {e}") from e
```

Leave the `run_recipe(recipe, dict(base), layers=layers, from_step=...)` call as-is — Task 3 made the runner resolve bindings.

- [ ] **Step 4: Run the diag-service suite**

Run: `pytest plugins/diag-service/tests/ -v`
Expected: all prior tests pass + the 2 new ones.

- [ ] **Step 5: Rebuild + smoke the container**

```bash
docker compose build diag-service && docker compose up -d diag-service
curl -s -X POST http://localhost:8055/diag/preview -H "Authorization: Bearer $TOKEN" \
  -H 'content-type: application/json' \
  -d '{"analysis_id":"<F19 id>","recipe":{...},"layers":{"bad":{"geometry":{"polygons":"x"}}}}' -i | head -1
```
Expected: `HTTP/1.1 422`

- [ ] **Step 6: Commit**

```bash
git add plugins/diag-service/app/main.py plugins/diag-service/tests/test_preview.py
git commit -m "feat(diag-service): validate inline paint-layer geometry on /preview"
```

---

## Task 6: `diagLayers.ts` — types + Directus CRUD

**Files:**
- Create: `packages/force-plotting/src/diagLayers.ts`, `packages/force-plotting/src/diagLayers.test.ts`
- Modify: `packages/force-plotting/src/index.ts`

**Interfaces:**
- Consumes: `useForceHost().api` (axios), `ForceHost`.
- Produces:
  ```ts
  export type LayerRole = 'mask' | 'label' | 'seed';
  export interface LayerGeometry { polygons: [number, number][][]; }
  export interface DiagLayer {
    layer_id: string; analysis_id: string; name: string; role: LayerRole;
    geometry: LayerGeometry; value: Record<string, unknown> | null; version: number;
  }
  // wire shape the preview service wants: { [name]: { role, geometry, value, version } }
  export function layersForRequest(layers: DiagLayer[]): Record<string, {
    role: LayerRole; geometry: LayerGeometry; value: unknown; version: number;
  }>;
  export function fetchLayers(analysisId: string): Promise<DiagLayer[]>;
  export function saveLayer(l: Partial<DiagLayer> & { analysis_id: string; name: string; role: LayerRole; geometry: LayerGeometry }): Promise<DiagLayer>;
  export function deleteLayer(layerId: string): Promise<void>;
  ```

- [ ] **Step 1: Write the failing test**

```ts
// packages/force-plotting/src/diagLayers.test.ts
import { describe, expect, it } from 'vitest';
import { layersForRequest, type DiagLayer } from './diagLayers';

const L = (over: Partial<DiagLayer>): DiagLayer => ({
  layer_id: 'id', analysis_id: 'a', name: 'chuck', role: 'mask',
  geometry: { polygons: [[[0, 0], [1, 0], [1, 1]]] }, value: null, version: 1, ...over,
});

describe('layersForRequest', () => {
  it('keys layers by name and keeps only the service-relevant fields', () => {
    const out = layersForRequest([L({ name: 'chuck' }), L({ name: 'edge', role: 'label' })]);
    expect(Object.keys(out).sort()).toEqual(['chuck', 'edge']);
    expect(out.chuck).toEqual({
      role: 'mask', geometry: { polygons: [[[0, 0], [1, 0], [1, 1]]] }, value: null, version: 1,
    });
    expect((out.chuck as any).layer_id).toBeUndefined();
  });

  it('is empty for no layers', () => {
    expect(layersForRequest([])).toEqual({});
  });
});
```

- [ ] **Step 2: Run it, verify it fails** — `pytest`? no: `npm test -w @d1/force-plotting -- diagLayers` → FAIL (module missing).

- [ ] **Step 3: Implement**

```ts
// packages/force-plotting/src/diagLayers.ts
import { useForceHost } from './host';

export type LayerRole = 'mask' | 'label' | 'seed';
export interface LayerGeometry { polygons: [number, number][][]; }
export interface DiagLayer {
  layer_id: string;
  analysis_id: string;
  name: string;
  role: LayerRole;
  geometry: LayerGeometry;
  value: Record<string, unknown> | null;
  version: number;
}

const FIELDS = 'layer_id,analysis_id,name,role,geometry,value,version';

/** The shape POST /diag/preview wants: keyed by name, service-relevant fields only. */
export function layersForRequest(layers: DiagLayer[]) {
  const out: Record<string, { role: LayerRole; geometry: LayerGeometry; value: unknown; version: number }> = {};
  for (const l of layers) {
    out[l.name] = { role: l.role, geometry: l.geometry, value: l.value, version: l.version };
  }
  return out;
}

export async function fetchLayers(analysisId: string): Promise<DiagLayer[]> {
  const { data } = await useForceHost().api.get('/items/diag_layer', {
    params: { 'filter[analysis_id][_eq]': analysisId, fields: FIELDS, limit: -1 },
  });
  return data.data as DiagLayer[];
}

export async function saveLayer(
  l: Partial<DiagLayer> & { analysis_id: string; name: string; role: LayerRole; geometry: LayerGeometry },
): Promise<DiagLayer> {
  const api = useForceHost().api;
  const payload = {
    analysis_id: l.analysis_id, name: l.name, role: l.role,
    geometry: l.geometry, value: l.value ?? null, version: l.version ?? 1,
  };
  if (l.layer_id) {
    const { data } = await api.patch(`/items/diag_layer/${l.layer_id}`, payload, { params: { fields: FIELDS } });
    return data.data as DiagLayer;
  }
  const { data } = await api.post('/items/diag_layer', payload, { params: { fields: FIELDS } });
  return data.data as DiagLayer;
}

export async function deleteLayer(layerId: string): Promise<void> {
  await useForceHost().api.delete(`/items/diag_layer/${layerId}`);
}
```

- [ ] **Step 4: Export from `index.ts`**

```ts
export { fetchLayers, saveLayer, deleteLayer, layersForRequest } from './diagLayers';
export type { DiagLayer, LayerRole, LayerGeometry } from './diagLayers';
```

- [ ] **Step 5: Run tests + typecheck** — `npm test -w @d1/force-plotting -- diagLayers` (2 passed); `npm run typecheck -w @d1/force-plotting` (0 errors).

- [ ] **Step 6: Commit**

```bash
git add packages/force-plotting/src/diagLayers.ts packages/force-plotting/src/diagLayers.test.ts packages/force-plotting/src/index.ts
git commit -m "feat(diag-ui): diagLayers types + Directus CRUD client"
```

---

## Task 7: `DiagScatter.vue` — polygon draw + layer overlay + finite-safe colour

**Files:**
- Modify: `packages/force-plotting/src/DiagScatter.vue`
- Test: manual (headless) — covered by Task 12's workbench verification. Add one vitest for the pure helper only.

**Interfaces:**
- Consumes: `LayerGeometry`, `DiagLayer` (Task 6).
- Produces:
  - new props: `paintMode?: 'off' | 'draw'` (default `'off'`), `layers?: DiagLayer[]` (default `[]`), `activeLayerName?: string | null`.
  - new emit: `(e: 'polygon', ring: [number, number][])` — fired on draw completion (double-click or Enter), ring in **angular-grid mm** (unprojected from screen via the ortho camera).
  - overlay: each layer in `layers` draws as a `THREE.LineLoop` per ring, coloured by role (mask = amber `#f59e0b`, label = sky `#38bdf8`, seed = violet `#a78bfa`), the active layer brighter.
  - `percentileRange` and `packValue` skip non-finite values (a masked `resid_z` column is now full of `NaN`s).
  - export a pure helper for the unproject math test:
    `export function screenToWorld(nx: number, ny: number, cam: THREE.OrthographicCamera): [number, number]` — actually keep this inline; instead export `ringToWorld` is overkill. Skip the standalone test; rely on Task 12.

- [ ] **Step 1: finite-safe `percentileRange`**

```ts
function percentileRange(a: Float32Array): [number, number] {
	const s = Float32Array.from(a).filter((v) => Number.isFinite(v)).sort();
	if (s.length === 0) return [0, 1];
	const lo = s[Math.floor(0.01 * (s.length - 1))];
	const hi = s[Math.floor(0.99 * (s.length - 1))];
	return hi > lo ? [lo, hi] : [lo, lo + 1];
}
```

And in the shader, guard `NaN` (GLSL: `aValue != aValue` is the NaN test): in `makeMaterial`'s vertexShader, before the colour branch:

```glsl
				if (aValue != aValue) {          // NaN -> masked-out point
					vColor = vec3(0.12);
					vDim = 0.25;
					gl_PointSize = uSize;
					gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
					return;
				}
```

- [ ] **Step 2: draw interaction**

Add pointer handlers on the canvas, active only when `props.paintMode === 'draw'`:

```ts
let draftRing: [number, number][] = [];
let draftObj: THREE.Line | null = null;

function canvasToWorld(ev: PointerEvent): [number, number] {
	const r = canvasEl.value!.getBoundingClientRect();
	const nx = ((ev.clientX - r.left) / r.width) * 2 - 1;
	const ny = -(((ev.clientY - r.top) / r.height) * 2 - 1);
	const v = new THREE.Vector3(nx, ny, 0).unproject(camera!);
	return [v.x, v.y];
}
function onPaintClick(ev: PointerEvent) {
	if (props.paintMode !== 'draw') return;
	draftRing.push(canvasToWorld(ev));
	redrawDraft();
}
function finishRing() {
	if (draftRing.length >= 3) emit('polygon', draftRing.slice());
	draftRing = [];
	redrawDraft();
}
```

Wire `@pointerdown` (single point add), `@dblclick="finishRing"`, and disable `controls.enablePan` while `paintMode === 'draw'` (watch the prop). `redrawDraft()` rebuilds a dashed `THREE.LineLoop` from `draftRing` and `invalidate()`s.

- [ ] **Step 3: layer overlay**

```ts
let overlayGroup: THREE.Group | null = null;
const ROLE_COLOR: Record<string, number> = { mask: 0xf59e0b, label: 0x38bdf8, seed: 0xa78bfa };
function rebuildOverlay() {
	if (overlayGroup) { scene?.remove(overlayGroup); overlayGroup.traverse((o: any) => o.geometry?.dispose?.()); }
	overlayGroup = new THREE.Group();
	for (const layer of props.layers ?? []) {
		const active = layer.name === props.activeLayerName;
		const mat = new THREE.LineBasicMaterial({
			color: ROLE_COLOR[layer.role] ?? 0xffffff,
			transparent: true, opacity: active ? 1 : 0.55,
		});
		for (const ring of layer.geometry.polygons) {
			const pts = ring.map(([x, y]) => new THREE.Vector3(x, y, 1));
			overlayGroup.add(new THREE.LineLoop(new THREE.BufferGeometry().setFromPoints(pts), mat));
		}
	}
	scene?.add(overlayGroup);
	invalidate();
}
watch(() => [props.layers, props.activeLayerName], rebuildOverlay, { deep: true });
```

Call `rebuildOverlay()` at the end of `setupGL`. Dispose `overlayGroup` in `onBeforeUnmount`.

- [ ] **Step 4: typecheck + existing package tests**

Run: `npm run typecheck -w @d1/force-plotting && npm test -w @d1/force-plotting`
Expected: 0 type errors; all existing tests still pass (DiagScatter has no unit test; the new props are optional so no caller breaks).

- [ ] **Step 5: Commit**

```bash
git add packages/force-plotting/src/DiagScatter.vue
git commit -m "feat(diag-ui): DiagScatter polygon draw, layer overlay, NaN-safe colour"
```

---

## Task 8: `LayerPanel.vue`

**Files:**
- Create: `packages/force-plotting/src/LayerPanel.vue`
- Modify: `packages/force-plotting/src/index.ts`

**Interfaces:**
- Consumes: `DiagLayer`, `LayerRole` (Task 6).
- Produces:
  - props: `{ layers: DiagLayer[]; activeName: string | null; drawing: boolean }`.
  - emits: `(e: 'update:activeName', n: string | null)`, `(e: 'update:drawing', v: boolean)`, `(e: 'add', role: LayerRole)`, `(e: 'rename', p: { layer: DiagLayer; name: string })`, `(e: 'delete', layer: DiagLayer)`.
  - Renders a role-grouped list; each row = colour dot + name (inline-editable) + point/ring count + delete. A "Draw" toggle button reflects `drawing`. Three "+ mask / + label / + seed" buttons.

- [ ] **Step 1: implement** (no separate test — it is presentational; Task 12 exercises it)

```vue
<script setup lang="ts">
import { ref } from 'vue';
import type { DiagLayer, LayerRole } from './diagLayers';

const props = defineProps<{ layers: DiagLayer[]; activeName: string | null; drawing: boolean }>();
const emit = defineEmits<{
	(e: 'update:activeName', n: string | null): void;
	(e: 'update:drawing', v: boolean): void;
	(e: 'add', role: LayerRole): void;
	(e: 'rename', p: { layer: DiagLayer; name: string }): void;
	(e: 'delete', layer: DiagLayer): void;
}>();

const ROLE_DOT: Record<LayerRole, string> = { mask: '#f59e0b', label: '#38bdf8', seed: '#a78bfa' };
const editing = ref<string | null>(null);
const draft = ref('');

function startEdit(l: DiagLayer) { editing.value = l.layer_id; draft.value = l.name; }
function commitEdit(l: DiagLayer) {
	if (draft.value.trim() && draft.value !== l.name) emit('rename', { layer: l, name: draft.value.trim() });
	editing.value = null;
}
function ringCount(l: DiagLayer) { return l.geometry?.polygons?.length ?? 0; }
</script>

<template>
	<div class="layer-panel">
		<div class="lp-tools">
			<button :class="{ on: drawing }" @click="emit('update:drawing', !drawing)">
				{{ drawing ? '■ stop drawing' : '✎ draw polygon' }}
			</button>
			<span class="lp-add">
				<button @click="emit('add', 'mask')">+ mask</button>
				<button @click="emit('add', 'label')">+ label</button>
				<button @click="emit('add', 'seed')">+ seed</button>
			</span>
		</div>
		<ul class="lp-list">
			<li v-for="l in layers" :key="l.layer_id"
				:class="{ active: l.name === activeName }"
				@click="emit('update:activeName', l.name === activeName ? null : l.name)">
				<span class="lp-dot" :style="{ background: ROLE_DOT[l.role] }" />
				<input v-if="editing === l.layer_id" v-model="draft"
					@click.stop @keyup.enter="commitEdit(l)" @blur="commitEdit(l)" />
				<span v-else class="lp-name" @dblclick.stop="startEdit(l)">{{ l.name }}</span>
				<span class="lp-meta">{{ l.role }} · {{ ringCount(l) }} ring{{ ringCount(l) === 1 ? '' : 's' }}</span>
				<button class="lp-del" @click.stop="emit('delete', l)">✕</button>
			</li>
			<li v-if="!layers.length" class="lp-empty">no layers — paint one to mask an artefact</li>
		</ul>
	</div>
</template>

<style scoped>
.layer-panel { display: flex; flex-direction: column; gap: 6px; font-size: 12px; }
.lp-tools { display: flex; flex-wrap: wrap; gap: 4px; }
.lp-tools button { font-size: 11px; padding: 3px 7px; border-radius: 6px; border: 1px solid var(--border, rgba(255,255,255,0.14)); background: var(--bg-2, #111a33); color: var(--text, #e5e7eb); cursor: pointer; }
.lp-tools button.on { background: #d97706; border-color: #f59e0b; color: #fff; }
.lp-add { display: inline-flex; gap: 4px; }
.lp-list { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 2px; }
.lp-list li { display: flex; align-items: center; gap: 6px; padding: 3px 5px; border-radius: 5px; cursor: pointer; }
.lp-list li.active { background: color-mix(in srgb, #f59e0b 16%, transparent); }
.lp-dot { width: 9px; height: 9px; border-radius: 50%; flex: none; }
.lp-name { flex: 1; }
.lp-meta { color: var(--text-dim, #94a3b8); font-size: 10px; }
.lp-del { border: none; background: none; color: var(--text-dim, #94a3b8); cursor: pointer; }
.lp-empty { color: var(--text-dim, #94a3b8); font-style: italic; padding: 4px; }
.lp-list input { flex: 1; font-size: 12px; background: var(--bg-1, #0b1020); color: var(--text); border: 1px solid var(--border); border-radius: 4px; padding: 1px 4px; }
</style>
```

- [ ] **Step 2: export**

```ts
export { default as LayerPanel } from './LayerPanel.vue';
```

- [ ] **Step 3: typecheck** — `npm run typecheck -w @d1/force-plotting` → 0 errors.

- [ ] **Step 4: Commit**

```bash
git add packages/force-plotting/src/LayerPanel.vue packages/force-plotting/src/index.ts
git commit -m "feat(diag-ui): LayerPanel — list, rename, delete, add mask/label/seed"
```

---

## Task 9: `selection.ts` — non-finite-safe stats

**Files:**
- Modify: `packages/force-plotting/src/selection.ts`
- Test: `packages/force-plotting/src/selection.test.ts` (add cases)

**Interfaces:**
- Produces: `computeStats` and `clusterStats` skip points whose `residZ` (or the relevant channel) is not finite. `matches` for an `'attribute'` selection returns `false` for a non-finite value (a `NaN` is never "in range").

- [ ] **Step 1: failing test**

```ts
it('clusterStats and computeStats ignore NaN (masked) points', () => {
	const attrs = makeAttrs();
	attrs.columns.resid_z = new Float32Array([NaN, -1, 0, 1, NaN]);
	attrs.columns.cluster_id = new Float32Array([-1, 0, 0, 1, -1]);
	const ws = workingSetFromD1an(attrs);
	const s = computeStats(ws, null);
	expect(s.n).toBe(3);                       // 2 NaN points skipped
	expect(Number.isFinite(s.meanResidZ)).toBe(true);
	const rows = clusterStats(ws);
	const c0 = rows.find((r) => r.id === 0)!;
	expect(Number.isFinite(c0.meanAbsResidZ)).toBe(true);
});

it('attribute selection never matches a NaN value', () => {
	const attrs = makeAttrs();
	attrs.columns.resid_z = new Float32Array([NaN, 0, 0, 0, 0]);
	const ws = workingSetFromD1an(attrs);
	expect(matches(ws, { kind: 'attribute', column: 'residZ', min: -100, max: 100 }, 0)).toBe(false);
});
```

- [ ] **Step 2: run, verify fail** — `npm test -w @d1/force-plotting -- selection` → FAIL (`s.n` is 5, `meanResidZ` is `NaN`).

- [ ] **Step 3: implement**
  - `matches` `'attribute'` case: `return Number.isFinite(v) && v >= sel.min && v <= sel.max;`
  - `computeStats`: after `if (!matches(...)) continue;` add `if (!Number.isFinite(ws.residZ[i])) continue;` — this both drops the point from `n` and skips all accumulation (matches the existing test's expectation `s.n === 3`).
  - `clusterStats`: add `nFinite: number` to the accumulator. `a.n++` always (cluster membership from `cluster_id` is still valid for a masked point). Guard the rest: `if (Number.isFinite(ws.residZ[i])) { a.nFinite++; a.sumAbs += Math.abs(ws.residZ[i]); ... }` and `if (Number.isFinite(ws.giStar[i]) && ws.giStar[i] > a.maxGi) a.maxGi = ...`. Then `meanAbsResidZ: a.nFinite ? a.sumAbs / a.nFinite : 0` (mirrors the existing `maxGiStar: a.maxGi === -Infinity ? 0 : a.maxGi` idiom — a fully-masked cluster yields 0, never `NaN`). `rMin`/`rMax` are from `x`/`y` which are always finite, leave them. Fractions still use `a.n / ws.n` so they still sum to 1 (existing test unchanged).

- [ ] **Step 4: run tests** — `npm test -w @d1/force-plotting` → all pass.

- [ ] **Step 5: Commit**

```bash
git add packages/force-plotting/src/selection.ts packages/force-plotting/src/selection.test.ts
git commit -m "feat(diag-ui): selection stats skip NaN (masked) points"
```

---

## Task 10: `DiagnosticsWorkbench.vue` — wire painting end to end

**Files:**
- Modify: `packages/force-plotting/src/DiagnosticsWorkbench.vue`
- Test: manual/headless (Task 12)

**Interfaces:**
- Consumes: `LayerPanel`, `fetchLayers`/`saveLayer`/`deleteLayer`/`layersForRequest`/`DiagLayer` (Tasks 6, 8), `DiagScatter`'s new props/emit (Task 7).
- Produces:
  - loads `layers` for `props.analysisId` on mount and on `analysisId` change.
  - `LayerPanel` rendered in the Spatial panel footer (above the channel select).
  - `DiagScatter` gets `:layers`, `:active-layer-name`, `:paint-mode`; `@polygon` appends a ring to the active layer (creating it if none active) and persists via `saveLayer`.
  - **Only the ACTIVE mask binds to compute** (`activeMask = maskLayers.find(l => l.name === activeLayerName) ?? maskLayers[0]`). `runPreview()` sends `layers: layersForRequest(activeMask ? [activeMask] : [])` AND injects `inputs: { mask: { layer: activeMask.name, required: false } }` onto the recipe's `radial_detrend` step for the preview call **only** (a `structuredClone` — never mutate `recipe.value`, or the bake payload and its hash change). Other mask layers render as overlay but do not affect compute; `LayerPanel` marks the bound one (see Task 8 — the `activeName` row already reads as active, which doubles as "this is the one that masks"). The state strip gains a note when `maskLayers.length > 1`: *"only the selected mask is applied"*. If there is no mask layer, send neither `layers` nor `inputs`.
  - a `layersDirty` flag → the state strip notes "masks changed since last bake" when a mask layer differs from what the bake used (advisory only; Task 11 persists on bake).

- [ ] **Step 1: load + state**

```ts
import LayerPanel from './LayerPanel.vue';
import { fetchLayers, saveLayer, deleteLayer, layersForRequest, type DiagLayer } from './diagLayers';

const layers = ref<DiagLayer[]>([]);
const activeLayerName = ref<string | null>(null);
const drawing = ref(false);
async function loadLayers() {
	try { layers.value = await fetchLayers(props.analysisId); } catch { layers.value = []; }
}
onMounted(loadLayers);
watch(() => props.analysisId, () => { activeLayerName.value = null; loadLayers(); });

const maskLayers = computed(() => layers.value.filter((l) => l.role === 'mask'));
```

- [ ] **Step 2: paint handlers**

```ts
let addSeq = 0;
async function onPolygon(ring: [number, number][]) {
	let target = layers.value.find((l) => l.name === activeLayerName.value);
	if (!target) { target = await onAddLayer('mask'); }
	const geometry = { polygons: [...(target.geometry?.polygons ?? []), ring] };
	const saved = await saveLayer({ ...target, geometry });
	layers.value = layers.value.map((l) => (l.layer_id === saved.layer_id ? saved : l));
}
async function onAddLayer(role: 'mask' | 'label' | 'seed'): Promise<DiagLayer> {
	const name = `${role}-${++addSeq + layers.value.length}`;
	const saved = await saveLayer({ analysis_id: props.analysisId, name, role, geometry: { polygons: [] } });
	layers.value = [...layers.value, saved];
	activeLayerName.value = saved.name;
	drawing.value = true;
	return saved;
}
async function onRenameLayer({ layer, name }: { layer: DiagLayer; name: string }) {
	const saved = await saveLayer({ ...layer, name });
	layers.value = layers.value.map((l) => (l.layer_id === saved.layer_id ? saved : l));
	if (activeLayerName.value === layer.name) activeLayerName.value = saved.name;
}
async function onDeleteLayer(layer: DiagLayer) {
	await deleteLayer(layer.layer_id);
	layers.value = layers.value.filter((l) => l.layer_id !== layer.layer_id);
	if (activeLayerName.value === layer.name) activeLayerName.value = null;
}
```

- [ ] **Step 3: preview with masks**

```ts
const activeMask = computed(() =>
	maskLayers.value.find((l) => l.name === activeLayerName.value) ?? maskLayers.value[0] ?? null);

function recipeForPreview(): Recipe {
	if (!activeMask.value) return recipe.value;
	const r = structuredClone(recipe.value);
	for (const s of r.steps) {
		if (s.op === 'radial_detrend') {
			(s as { inputs?: unknown }).inputs = { mask: { layer: activeMask.value.name, required: false } };
		}
	}
	return r;
}
```

In `runPreview`, call `fetchDiagPreview(props.analysisId, recipeForPreview(), null, ac.signal, activeMask.value ? layersForRequest([activeMask.value]) : undefined)`. **Check `diagPreview.ts`'s signature** — `fetchDiagPreview(analysisId, recipe, fromStep, signal)`. Add an optional 5th `layers?: Record<string, unknown>` param and include it in the POST body as `layers` only when defined. Change the preview trigger to `watch([recipe, () => layers.value, activeLayerName], ..., { deep: true })` so painting and switching the active mask re-preview. Extend the "needs preview" early-return: `if (!bakeStale.value && !activeMask.value) { ...clear preview... return; }` (a mask over the default recipe is still a non-baked state that needs a preview).

- [ ] **Step 4: template**

In the Spatial `WorkbenchPanel`, pass the new props to `<DiagScatter>` and add `<LayerPanel>` in the `#footer` above the channel `<select>`:

```vue
<DiagScatter
	:working-set="activeWS" :channel="channel" :cluster-mode="clusterMode"
	:selection="selection" :point-size="2.6"
	:layers="layers" :active-layer-name="activeLayerName"
	:paint-mode="drawing ? 'draw' : 'off'"
	@polygon="onPolygon"
/>
...
<template #footer>
	<div class="dw-spatial-footer">
		<LayerPanel
			:layers="layers" v-model:active-name="activeLayerName" v-model:drawing="drawing"
			@add="onAddLayer" @rename="onRenameLayer" @delete="onDeleteLayer"
		/>
		<select v-model="channel" class="dw-channel-select"> ... unchanged ... </select>
		<ClusterTable ... unchanged ... />
	</div>
</template>
```

- [ ] **Step 5: typecheck both workspaces**

Run: `npm run typecheck -w @d1/force-plotting && npm run typecheck -w force-app-web`
Expected: 0 errors. (`diagPreview.ts` gained an optional param — update its one existing caller signature if TS complains.)

- [ ] **Step 6: Commit**

```bash
git add packages/force-plotting/src/DiagnosticsWorkbench.vue packages/force-plotting/src/diagPreview.ts
git commit -m "feat(diag-ui): wire paint layers through the workbench and preview"
```

---

## Task 11: Persist layers on bake; orchestrator reads them

**Files:**
- Modify: `apps/force-app/web/src/force/DiagnosticsPage.vue`, `apps/force-app/web/src/force/StandaloneDiagnosticsWorkbench.vue`, `scripts/force_orchestrator.py`
- Test: `tests/scripts/test_orchestrator_diag_layers.py` (create) — a unit test of the layer-fingerprint helper; the full bake path is integration-tested manually.

**Interfaces:**
- Consumes: `diag_layer` table (Task 1), `run_recipe(..., layers=)` (Task 3).
- Produces:
  - `process_diag_row` fetches `diag_layer` rows for the analysis (`SELECT name, role, geometry, value, version FROM diag_layer WHERE analysis_id = %s`), builds the same `{name: {role, geometry, value, version}}` dict the service uses, and passes it as `layers=` to **every** `run_recipe` call in the function (the main run, the `base` emit run — base is pre-`radial_detrend` so masks are inert there but pass anyway for uniformity).
  - **LAS/octree NaN sanitisation.** Immediately before the `for nm, arr in extra_cols.items(): setattr(las, nm, arr)` loop, replace each array with `np.nan_to_num(arr, nan=0.0)`. Before the `fza` intensity ramp `lo, hi = float(fza.min()), float(fza.max())`, use `np.nanmin`/`np.nanmax` (fza itself is unmasked today, but this is defensive and free). Comment: *"attrs.d1an is authoritative for masked points (NaN); the octree extra dims are a downstream visual and must be finite or PotreeConverter's per-attribute min/max — and therefore DiagOctreeView's colour range — go NaN and the whole octree renders blank."* `write_d1an(str(d1an_path), columns)` stays on the **un-sanitised** `columns` (NaN preserved in the D1AN).
  - the stored hash becomes `recipe_hash(recipe)` XORed/combined with a layer fingerprint: `_layer_fingerprint(layer_rows) -> str` = `sha256` of `json.dumps(sorted([(r.name, r.role, r.version) for r in rows]))[:16]`, and the column write becomes `diag_recipe_hash = f"{recipe_hash(recipe)}:{fingerprint}"` when layers exist, else `recipe_hash(recipe)` unchanged (so no-layer cuts keep their current hash and do not rebake).
  - `claim_diag`'s staleness clause already requeues on `diag_recipe_hash` mismatch — no SQL change needed; when a layer's `version` bumps, the workbench should also bump `diag_recipe` is NOT required, but the cut must be re-queued: the PATCH on bake sets `diag_status='pending'` explicitly (it already does), so an explicit Bake after painting is the trigger. A DB trigger for layer edits is **Phase F** (out of scope here) — note this in the code comment.
- `DiagnosticsPage.vue`'s `build(recipe?)` already PATCHes `diag_status='pending'`; no change beyond a comment that saved `diag_layer` rows are picked up server-side.

- [ ] **Step 1: failing test for the fingerprint helper**

```python
# tests/scripts/test_orchestrator_diag_layers.py
from force_orchestrator import _layer_fingerprint


def test_fingerprint_is_stable_and_order_independent():
    a = [{"name": "chuck", "role": "mask", "version": 2}, {"name": "edge", "role": "label", "version": 1}]
    b = list(reversed(a))
    assert _layer_fingerprint(a) == _layer_fingerprint(b)


def test_fingerprint_changes_with_version():
    a = [{"name": "chuck", "role": "mask", "version": 1}]
    c = [{"name": "chuck", "role": "mask", "version": 2}]
    assert _layer_fingerprint(a) != _layer_fingerprint(c)


def test_fingerprint_empty_is_falsy():
    assert not _layer_fingerprint([])
```

- [ ] **Step 2: run, verify fail** — `pytest tests/scripts/test_orchestrator_diag_layers.py` → ImportError.

- [ ] **Step 3: implement the helper + wire the fetch**

```python
def _layer_fingerprint(rows: list[dict]) -> str:
    """Identity of the painted layers bound to a cut, for diag_recipe_hash. Order-independent;
    changes when a layer is added/removed/renamed/re-versioned. Geometry is deliberately NOT
    hashed here -- the workbench bumps `version` on every geometry edit, so version stands in
    for content and keeps the fingerprint cheap."""
    if not rows:
        return ""
    import hashlib
    key = json.dumps(sorted((r["name"], r["role"], int(r["version"])) for r in rows))
    return hashlib.sha256(key.encode()).hexdigest()[:16]
```

In `process_diag_row`, after the row is claimed and before the first `run_recipe`:

```python
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                "SELECT name, role, geometry, value, version FROM diag_layer WHERE analysis_id = %s",
                [row["id"]],
            )
            layer_rows = cur.fetchall()
        diag_layers = {
            r["name"]: {"role": r["role"], "geometry": r["geometry"],
                        "value": r["value"], "version": r["version"]}
            for r in layer_rows
        } or None
```

Pass `layers=diag_layers` to each `run_recipe(...)` call. Change the hash write:

```python
        fp = _layer_fingerprint(layer_rows)
        stored_hash = f"{recipe_hash(recipe)}:{fp}" if fp else recipe_hash(recipe)
```

and use `stored_hash` in the `UPDATE ... SET diag_recipe_hash=%s`.

- [ ] **Step 4: run the diag suite + the new test**

Run: `pytest tests/scripts/ -v -k "diag or orchestrator"`
Expected: new test passes; existing orchestrator tests pass; **no-layer cuts produce the identical `diag_recipe_hash` as before** (assert this against a known value if a test exists, else reason it: `fp == ""` → `stored_hash == recipe_hash(recipe)`).

- [ ] **Step 5: pass-through comments in the two Vue hosts**

Add a one-line comment in `DiagnosticsPage.vue`'s `build()` and `StandaloneDiagnosticsWorkbench.vue` noting that persisted `diag_layer` rows are read by `process_diag_row`; no prop plumbing needed (the workbench already owns layer CRUD against Directus directly).

- [ ] **Step 6: Commit**

```bash
git add scripts/force_orchestrator.py tests/scripts/test_orchestrator_diag_layers.py apps/force-app/web/src/force/DiagnosticsPage.vue apps/force-app/web/src/force/StandaloneDiagnosticsWorkbench.vue
git commit -m "feat(diag): orchestrator bakes with persisted paint layers; layer fingerprint in hash"
```

---

## Task 12: End-to-end verification + suite green

**Files:** none (verification only) — plus any small fixes the verification surfaces.

- [ ] **Step 1: Full test suites**

```bash
pytest tests/scripts/diag/ plugins/diag-service/tests/ tests/scripts/test_orchestrator_diag_layers.py -q
npm test -w @d1/force-plotting
npm run typecheck -w @d1/force-plotting
npm run typecheck -w force-app-web
```
Expected: all green, 0 type errors. Record the counts.

- [ ] **Step 2: Rebuild the service, restart the daemon**

```bash
docker compose build diag-service && docker compose up -d diag-service
# restart the orchestrator daemon (same procedure the recipe-engine phase used)
```

- [ ] **Step 3: Headless workbench check (playwright-core)**

Drive `/diagnostics` in the standalone force app:
1. select the F19 cut (already baked).
2. LayerPanel visible in the Spatial panel; "+ mask" creates a layer, "draw polygon" toggles on.
3. click 3+ points on the scatter, double-click to close → a `diag_layer` row is POSTed (check network), the amber overlay renders.
4. within ~1 s a `/diag/preview` fires whose body carries `layers` + a `radial_detrend.inputs.mask` binding; the returned cloud shows the painted region dimmed (NaN colour).
5. the state strip reads "previewing recipe … approximate".
6. reload the page → the layer and its polygon are still there (persisted).
7. delete the layer → overlay clears, preview returns to unmasked.

Capture a screenshot at step 4. A blank canvas = fail.

- [ ] **Step 4: Bake path**

Set the F19 row's `diag_status='pending'` (or click Build in the header), watch the daemon log: it should `SELECT ... FROM diag_layer`, bake, and write `diag_recipe_hash` of the form `<16hex>:<16hex>`. Then verify all three:
1. `attrs.d1an` has `NaN` in `resid_z` for the painted region (quick Python check on the published file).
2. `infra/octrees/diag/<F19>/metadata.json` — every `attributes[].min`/`max` is a finite number, NOT `null`/`NaN` (this is the sanitisation working).
3. Load `/diagnostics` → F19 → the baked scatter still renders (not blank), painted region shows the NaN/dim colour, channel switch to `resid_z` still colours the rest normally.

- [ ] **Step 5: fix anything broken, re-run Step 1, commit fixes**

- [ ] **Step 6: Finish the branch**

Announce: "I'm using the finishing-a-development-branch skill to complete this work." Then:
- verify the full suite green on the merged result
- base branch is `main`
- merge `--no-ff` to `main`, push, delete the branch (per the user's standing "merge each phase to main as it finishes")

---

## Self-Review

**Spec coverage:**
- Component 3 "polygons in (x,y) mm, not per-point array" → Task 1 (schema), Task 2 (rasteriser). ✔
- "mask consumed by compute via inputs" → Tasks 3, 4. ✔
- "label — annotation only, exported with the operation" → Task 1 (role), Task 8 (create/manage). Export-with-operation is existing Directus behaviour once the row exists. ✔
- "seed — future grow_segmentation step" → Task 1 stores the role; the consuming step is **Phase F** (correctly out of scope). ✔
- "select — transient, no table, existing shader predicate" → already exists in `selection.ts` (lasso); untouched. ✔
- "Rasterisation server-side, one shared helper" → `scripts/diag/layers.py`, called by both runner (Task 3) and — transitively — the service (Task 5) and orchestrator (Task 11). ✔
- "layers sent by client inline" → Task 5, Task 10. ✔
- "authorize on LRU hit (32fb4b7)" → unchanged; Global Constraints + Task 5 note it explicitly. ✔
- "prefix hashing includes bound layer versions" → Task 11 (`_layer_fingerprint` in the stored hash). Preview already keys its LRU on `layers` (Task 5 confirms). ✔
- "layer-resolution-independence test" → Task 2 Step 1 `test_rasterize_is_resolution_independent`. ✔
- Phase E visible outcome "Artefacts maskable; regions annotatable" → mask changes compute (Task 4 + 10 + 11), label rows created/named/exported (Task 8). ✔

**Placeholder scan:** the file-structure section has two struck-through false starts (`PaintOverlay.md` NO; `DEFAULT_RECIPE` inputs NO) left in deliberately as decisions-with-rationale, not TODOs. Every code step has real code. No "add error handling" hand-waves. ✔

**Type consistency:**
- `resolve_inputs(step, layers, x, y)` — same signature in Task 3 interface, `registry.py` impl, and `runner.py` call site. ✔
- `layersForRequest` (Task 6) vs `layersForRequest` used in Task 10 Step 3 — same name. ✔ (earlier draft had `layersForRequest`/`layersForRecipe` drift — unified to `layersForRequest`.)
- `DiagLayer.geometry: LayerGeometry` with `polygons: [number,number][][]` — consistent Task 6 / 7 / 8 / 10.
- Python layer dict shape `{role, geometry, value, version}` — consistent Task 3 test, Task 5 test, Task 11 impl.
- `_layer_fingerprint` takes `list[dict]` with `name/role/version` keys — consistent Task 11 test and impl.
- diag-service layer value shape: service receives `{name: {role, geometry, value, version}}`; `resolve_inputs` reads `layer["geometry"]` — matches. ✔

**Scope:** one phase, one merge. Server (Tasks 1-5, 11) and UI (6-10) are separable but share the wire format; kept in one plan because the resolution-independence guarantee only means something when both halves agree on it. Seed-consuming segmentation and the layer-edit DB trigger are explicitly deferred to Phase F.
