# Diagnostics Phase F — Seeded Segmentation & Recipe Library Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `grow_segmentation` recipe step that turns a few painted seed regions into a full `segment_id` map (semi-supervised label propagation over a k-NN graph), a recipe library UI (save / name / apply saved recipes across cuts against the existing `diag_recipes` table), and a DB trigger that requeues a cut when its `diag_recipe` or `tool_setup_id` is edited outside the workbench.

**Architecture:** `grow_segmentation` is a `derived`-tier step: `sklearn.semi_supervised.LabelSpreading(kernel="knn")` fit on a `StandardScaler`-normalised `[x, y, *features]` matrix with sparse seed labels (each bound `seed`-role layer = one class), producing `segment_id` — the 12th D1AN column. It degrades to all `-1` when fewer than 2 seed classes are painted, and holds Phase-E-masked (`NaN` `resid_z`) points out of the fit. `resolve_inputs` gains a list-binding mode (`{"layers": [...]}` → ordered dict of boolean arrays). The recipe library and trigger mirror `filter_profiles` / `filter_chain` precedent exactly. Adding the 12th column bumps `DIAG_VERSION` 5→6, re-baking every cut.

**Tech Stack:** Python 3.12 / numpy / scikit-learn (`semi_supervised`, `preprocessing` — both already dependencies), dbmate SQL + plpgsql, Vue 3 + TypeScript + Three.js (`@d1/force-plotting`), Directus items API.

**Spec:** `docs/superpowers/specs/2026-09-03-diagnostics-phase-f-segmentation-and-library-design.md`

## Global Constraints

- **Default-recipe equivalence is sacred.** `grow_segmentation` is NOT in `DEFAULT_RECIPE`. The golden fixtures (`tests/scripts/diag/fixtures/golden_default_recipe.npz`, `golden_envelope.npz`) are frozen and NEVER regenerated — the capture script is deleted. The only permitted equivalence-test change is relaxing `assert_columns_match_golden`'s `set(cols) == set(expected)` to `set(expected) <= set(cols)` plus an assertion that any extra column is exactly `segment_id` and all `-1`.
- **The browser computes nothing.** Segmentation runs server-side in `run_recipe`. The client edits the recipe, paints polygons, and posts.
- **`segment_id` default is `-1`, not `0`.** `0` is a valid class index; `-1` means "unsegmented". This applies to the runner's assembly fill AND every degradation path in the op.
- **`_TRUNCATABLE` is NOT widened.** `segment_id` is produced by a `derived` step that runs *after* `tsa` consumed the truncation marker — it never exists when `_truncate` runs. The file's own comment forbids widening `_TRUNCATABLE` in step with `PUBLIC_COLUMNS`; obey it. Only `PUBLIC_COLUMNS` gains `segment_id`.
- **Masked points** (`resid_z` is `NaN` under a Phase-E mask) get `segment_id = -1` and are excluded from the `LabelSpreading` fit.
- **`DIAG_VERSION` 5 → 6.** Every baked `attrs.d1an` becomes stale; all 5 cuts re-bake. `base.d1an` (pre-`tsa`: `t, rev, x, y, sig`) is unaffected.
- **`recipe_hash` schema care.** `scripts/diag/recipe.py::_canonical` already folds per-step `inputs` into the hash. A `{"layers": [a, b]}` binding must hash stably and order-sensitively (the class order is semantic). Do not sort the list.
- **Trigger must not fight the daemon.** `process_diag_row`'s completion `UPDATE` never touches `diag_recipe` / `tool_setup_id`, so `IS DISTINCT FROM` on those columns is false on daemon writes.
- Migrations: `docker run ghcr.io/amacneil/dbmate:2` on network `d1-database_d1net`, DSN `postgres://d1:change_me@postgres:5432/d1_database?sslmode=disable`, `MSYS_NO_PATHCONV=1` on Git-Bash. Directus DB user is `d1` / db `d1_database` (NOT `directus`).
- Python: `py -3 -m pytest ...` via the PowerShell tool (bash `python`/`py` are WindowsApps stubs). Real interpreter: `C:\Program Files\Python313\python.exe`. Package: `npm test -w @d1/force-plotting`. Types: `npm run typecheck -w @d1/force-plotting` and `-w force-app-web`, both 0 errors.
- The orchestrator daemon runs on this host under PID from `%TEMP%\d1_orch_*.log`; it needs `.env` loaded for `DATABASE_URL` (host DSN `@localhost:5432`).

---

## File Structure

**Create:**
- `scripts/diag/segmentation.py` — `grow_segmentation(x, y, features, seed_masks, *, k, alpha, attr_weight) -> (segment_id, status)`. The algorithm, no registry decorator (mirrors `spatial.py` / `detrend.py`).
- `tests/scripts/diag/test_segmentation.py` — algorithm unit tests + planted-region recovery.
- `tests/scripts/diag/test_grow_segmentation_op.py` — the `@step` wrapper: degradation, masking, multi-class, `-1` default.
- `db/migrations/20260903000109_diag_recipes_directus.sql` — register `diag_recipes` with Directus (table exists; never registered).
- `db/migrations/20260903000110_diag_requeue_trigger.sql` — the `BEFORE UPDATE` trigger.
- `packages/force-plotting/src/diagRecipes.ts` — `fetchRecipeLibrary`, `saveRecipe`, `deleteRecipe`.
- `packages/force-plotting/src/diagRecipes.test.ts`.
- `packages/force-plotting/src/RecipeLibrary.vue` — the save/apply/delete control.

**Modify:**
- `scripts/diag/ops.py` — register `_op_grow_segmentation`.
- `scripts/diag/registry.py` — `resolve_inputs` list mode (`{"layers": [...]}`).
- `scripts/diag/runner.py` — `PUBLIC_COLUMNS` / `_TRUNCATABLE` += `segment_id`; assembly fill `-1.0` for `segment_id`.
- `scripts/force_orchestrator.py` — `DIAG_VERSION = 6`.
- `tests/scripts/diag/conftest.py` — relax `assert_columns_match_golden`.
- `tests/scripts/diag/test_runner_inputs.py` — add list-mode cases.
- `plugins/diag-service/tests/test_preview.py` — one seeded-preview test.
- `packages/force-plotting/src/selection.ts` — `ChannelKey` / `WorkingSet` / `COLUMN_MAP` / `CHANNEL_ACCESSOR` += `segmentId` / `segment_id`.
- `packages/force-plotting/src/recipeChannels.ts` — `STEP_META['grow_segmentation']`, `PRODUCED_TO_CHANNEL['segment_id']`, `ALL_CHANNELS` += segment.
- `packages/force-plotting/src/DiagScatter.vue` — `segmentId` renders categorically (reuse the cluster palette path).
- `packages/force-plotting/src/RecipePanel.vue` — add-step menu + remove-step; a seed-layer multiselect for `grow_segmentation`'s `inputs.seeds.layers`; `RecipeLibrary` in the footer; new props `seedLayerNames`, `library`.
- `packages/force-plotting/src/DiagnosticsWorkbench.vue` — load recipe library, pass `seedLayerNames` (from `layers`), handle apply/save; segment channel legend.
- `packages/force-plotting/src/index.ts` — exports.
- `packages/force-plotting/src/diagAttrs.ts` — if it hardcodes the D1AN column list, add `segment_id` (check first).

---

## Task 1: `resolve_inputs` list-binding mode

**Files:**
- Modify: `scripts/diag/registry.py`
- Test: `tests/scripts/diag/test_runner_inputs.py`

**Interfaces:**
- Consumes: Phase E `resolve_inputs`, `rasterize_polygons`.
- Produces: a binding with `"layers"` (a `list[str]`) instead of `"layer"` (a `str`) resolves to `Inputs[key] = dict[str, np.ndarray]` — an insertion-ordered dict, one boolean array per resolvable layer, **layers absent from `layers` are skipped** (not `None`-entried). `required=True` with zero resolvable layers raises `RecipeError`. The tier gate and per-array shape assertion apply to each. A `"layer"` binding is unchanged (`np.ndarray | None`).
- `Inputs` type widens to `dict[str, "np.ndarray | None | dict[str, np.ndarray]"]`.

- [ ] **Step 1: Write the failing test**

```python
# append to tests/scripts/diag/test_runner_inputs.py


def test_resolve_inputs_list_mode_returns_ordered_dict():
    step = {
        "op": "grow_segmentation",
        "on": True,
        "inputs": {"seeds": {"layers": ["defect", "clean"], "required": False}},
    }
    layers = {
        "clean": _layer([_sq(1.0)]),
        "defect": _layer([[[5.0, 5.0], [7.0, 5.0], [7.0, 7.0], [5.0, 7.0]]]),
    }
    x = np.array([0.0, 6.0, 20.0])
    y = np.array([0.0, 6.0, 20.0])
    out = resolve_inputs(step, layers, x, y)
    assert list(out["seeds"].keys()) == [
        "defect",
        "clean",
    ]  # recipe order, not dict order
    assert out["seeds"]["defect"].tolist() == [False, True, False]
    assert out["seeds"]["clean"].tolist() == [True, False, False]


def test_resolve_inputs_list_mode_skips_missing_layers():
    step = {
        "op": "grow_segmentation",
        "inputs": {"seeds": {"layers": ["a", "gone"], "required": False}},
    }
    out = resolve_inputs(step, {"a": _layer([_sq(1.0)])}, np.zeros(2), np.zeros(2))
    assert list(out["seeds"].keys()) == ["a"]


def test_resolve_inputs_list_mode_required_with_none_raises():
    step = {
        "op": "grow_segmentation",
        "inputs": {"seeds": {"layers": ["gone"], "required": True}},
    }
    with pytest.raises(RecipeError, match="seeds"):
        resolve_inputs(step, {}, np.zeros(2), np.zeros(2))


def test_list_binding_hashes_stably_and_order_sensitively():
    from diag.recipe import recipe_hash

    mk = lambda layers: {
        "steps": [
            {"id": "a", "op": "frame_transform", "on": True, "params": {}},
            {
                "id": "s",
                "op": "grow_segmentation",
                "on": True,
                "params": {},
                "inputs": {"seeds": {"layers": layers}},
            },
        ]
    }
    assert recipe_hash(mk(["x", "y"])) == recipe_hash(mk(["x", "y"]))
    assert recipe_hash(mk(["x", "y"])) != recipe_hash(
        mk(["y", "x"])
    )  # class order is semantic
```

(This exercises `_canonical` in `recipe.py`: `dict(sorted(inputs.items()))` sorts only the top-level `inputs` keys, and the JSON encoding of the value preserves nested list order — so the swapped-list hash differs. If the test shows otherwise, that is a `_canonical` bug to fix here.)

- [ ] **Step 2: Run, verify fail** — `py -3 -m pytest tests/scripts/diag/test_runner_inputs.py -q` → FAIL (list binding hits `binding.get("layer")` → `None` → treated as missing).

- [ ] **Step 3: Implement**

In `resolve_inputs`, inside the `for key, binding in bindings.items():` loop, before the existing `name = binding.get("layer")` line:

```python
if "layers" in binding:
    names = binding["layers"]
    resolved: dict[str, np.ndarray] = {}
    for lname in names:  # recipe order is semantic — do not sort
        layer = (layers or {}).get(lname)
        if layer is None:
            continue
        arr = rasterize_polygons(layer["geometry"], x, y)
        if arr.shape != xa.shape:
            raise RecipeError(
                f"layer {lname!r} rasterised to {arr.shape}, "
                f"step {op!r} expects {xa.shape}"
            )
        resolved[lname] = arr
    if not resolved and binding.get("required"):
        raise RecipeError(
            f"step {op!r} requires input {key!r} but no bound layer resolved"
        )
    out[key] = resolved
    continue
```

(The `xa = np.asarray(x)` and the base-tier gate above already run for any step with bindings.)

Widen the `Inputs` alias comment and type:

```python
Inputs = dict[str, "np.ndarray | None | dict[str, np.ndarray]"]
```

- [ ] **Step 4: Run the new cases + full diag suite** — `py -3 -m pytest tests/scripts/diag/ -q` → all green (Phase E `mask` tests still pass — the `"layer"` path is untouched).

- [ ] **Step 5: Commit**

```bash
git add scripts/diag/registry.py tests/scripts/diag/test_runner_inputs.py
git commit -m "feat(diag): resolve_inputs list-binding mode for multi-layer step inputs"
```

---

## Task 2: `scripts/diag/segmentation.py` — the algorithm

**Files:**
- Create: `scripts/diag/segmentation.py`, `tests/scripts/diag/test_segmentation.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces:
  ```python
  def grow_segmentation(
      x: np.ndarray,
      y: np.ndarray,
      features: list[np.ndarray],  # e.g. [resid_z] — non-spatial columns, each len n
      seed_masks: list[
          np.ndarray
      ],  # ordered; seed_masks[c] True where point is a class-c example
      *,
      k: int = 15,
      alpha: float = 0.2,
      attr_weight: float = 1.0,
  ) -> tuple[np.ndarray, str]:
      """Returns (segment_id, status). segment_id is float64 length n: the class index
      (0-based, matching seed_masks order) for every point, or -1 where unsegmentable.
      status is '' on success or a short reason string on degradation."""
  ```
- Rules:
  - `< 2` non-empty `seed_masks` → `(np.full(n, -1.0), "needs >= 2 seed classes")`.
  - Build `F = column_stack([x, y] + features)`; `StandardScaler().fit_transform(F)`; multiply columns `2:` by `attr_weight`.
  - Any feature column that is all-constant (zero variance → NaN after scaling) is dropped; if that leaves `< 1` feature, still proceed with `[x, y]` only and note it in status.
  - `y_labels = np.full(n, -1)`; for `c, m in enumerate(seed_masks): y_labels[m & finite] = c` where `finite = np.all(np.isfinite(F_scaled), axis=1)`.
  - Points that are non-finite in `F` (a masked `NaN` feature) → `segment_id = -1`, excluded from fit.
  - `LabelSpreading(kernel="knn", n_neighbors=min(k, n_fit - 1), alpha=alpha, max_iter=60)` fit on `F_scaled[fit_idx]`, `y_labels[fit_idx]` where `fit_idx = finite`. `segment_id[fit_idx] = model.transduction_`; `segment_id[~finite] = -1`.
  - Overlapping seed polygons: last class wins (later `seed_masks` entry overwrites — matches `y_labels[m] = c` in order).

- [ ] **Step 1: Write the failing test**

```python
# tests/scripts/diag/test_segmentation.py
import os
import sys

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", "scripts"))

from diag.segmentation import grow_segmentation


def _disc(n, cx, cy, r, rng):
    ang = rng.uniform(0, 2 * np.pi, n)
    rad = r * np.sqrt(rng.uniform(0, 1, n))
    return cx + rad * np.cos(ang), cy + rad * np.sin(ang)


def test_recovers_a_planted_high_residual_region():
    # NOTE: LabelSpreading is a TOTAL partition -- every finite point gets class 0 or 1,
    # there is no "background". So the clean seed must be a REPRESENTATIVE scattered sample
    # of clean material (what an analyst actually paints), not one compact far-away patch,
    # or the spatial term hands the middle of the cut to whichever seed is nearer. Assert on
    # the attribute-driven property, not a "false positive rate" against an undefined negative.
    rng = np.random.default_rng(3)
    n = 4000
    x = rng.uniform(-40, 40, n)
    y = rng.uniform(-40, 40, n)
    resid = rng.normal(0, 1, n)
    planted = (x > 10) & (x < 25) & (y > -8) & (y < 8)  # a rectangular macrozone
    resid[planted] += 6.0

    seed_defect = (x > 15) & (x < 20) & (y > -3) & (y < 3)  # small patch inside
    seed_clean = (np.abs(resid) < 0.5) & ~planted & (rng.uniform(size=n) < 0.15)
    seg, status = grow_segmentation(
        x, y, [resid], [seed_defect, seed_clean], k=15, attr_weight=3.0
    )
    assert status == ""
    assert (seg[planted] == 0).mean() > 0.9, (seg[planted] == 0).mean()
    assert (seg[np.abs(resid) < 1.0] == 1).mean() > 0.8, (
        seg[np.abs(resid) < 1.0] == 1
    ).mean()


def test_multi_class_preserves_seed_order():
    rng = np.random.default_rng(4)
    n = 3000
    x = rng.uniform(-40, 40, n)
    y = rng.uniform(-40, 40, n)
    resid = rng.normal(0, 1, n)
    a = x < -15
    b = (x > -5) & (x < 5)
    c = x > 15
    seg, status = grow_segmentation(x, y, [resid], [a, b, c])
    assert status == ""
    assert set(np.unique(seg)) <= {0.0, 1.0, 2.0}
    assert (
        seg[a].mean() < 0.5
        and abs(seg[b].mean() - 1) < 0.5
        and abs(seg[c].mean() - 2) < 0.5
    )


def test_degrades_below_two_seed_classes():
    x = np.arange(50.0)
    y = np.zeros(50)
    seg, status = grow_segmentation(x, y, [np.zeros(50)], [x > 40])
    assert status == "needs >= 2 seed classes"
    assert np.all(seg == -1)


def test_nan_feature_points_are_minus_one_and_excluded():
    rng = np.random.default_rng(5)
    n = 800
    x = rng.uniform(-10, 10, n)
    y = rng.uniform(-10, 10, n)
    resid = rng.normal(0, 1, n)
    resid[:100] = np.nan  # a Phase-E mask
    seg, status = grow_segmentation(x, y, [resid], [x < -5, x > 5])
    assert np.all(seg[:100] == -1)
    assert status == ""
```

- [ ] **Step 2: Run, verify fail** — `py -3 -m pytest tests/scripts/diag/test_segmentation.py -q` → `ModuleNotFoundError: diag.segmentation`.

- [ ] **Step 3: Implement**

```python
# scripts/diag/segmentation.py
"""Seeded segmentation: turn a handful of painted example regions into a full per-point
class map via semi-supervised label propagation over a k-NN graph.

Classical, not learned -- no training set, matching the pipeline's rejection of PointNet++/
U-Net. LabelSpreading over [x, y, scaled attributes] is exactly "classify every point from
sparse labels"; it is deterministic, multi-class, and needs no dependency the pipeline does
not already carry. Provisional defaults, like the rest of scripts/diag/spatial.py.
"""

from __future__ import annotations

import numpy as np


def grow_segmentation(
    x: np.ndarray,
    y: np.ndarray,
    features: list[np.ndarray],
    seed_masks: list[np.ndarray],
    *,
    k: int = 15,
    alpha: float = 0.2,
    attr_weight: float = 1.0,
) -> tuple[np.ndarray, str]:
    from sklearn.preprocessing import StandardScaler
    from sklearn.semi_supervised import LabelSpreading

    x = np.asarray(x, dtype=np.float64)
    y = np.asarray(y, dtype=np.float64)
    n = x.size
    non_empty = [m for m in seed_masks if np.any(m)]
    if len(non_empty) < 2:
        return np.full(n, -1.0), "needs >= 2 seed classes"

    cols = [x, y]
    dropped = 0
    for f in features:
        f = np.asarray(f, dtype=np.float64)
        # constant column -> zero variance -> NaN under StandardScaler; drop it
        finite_f = f[np.isfinite(f)]
        if finite_f.size and np.ptp(finite_f) > 0:
            cols.append(f)
        else:
            dropped += 1
    F = np.column_stack(cols)

    finite = np.all(np.isfinite(F), axis=1)
    seg = np.full(n, -1.0)
    if int(finite.sum()) < max(4, k + 1):
        return seg, "too few finite points to propagate"

    scaled = np.zeros_like(
        F, dtype=np.float64
    )  # ~finite rows stay 0 and are never fit/used
    scaled[finite] = StandardScaler().fit_transform(F[finite])
    if scaled.shape[1] > 2:
        scaled[:, 2:] *= float(attr_weight)

    y_labels = np.full(n, -1)
    for c, m in enumerate(seed_masks):
        y_labels[np.asarray(m, dtype=bool) & finite] = c
    if len(set(int(v) for v in y_labels[y_labels >= 0])) < 2:
        return seg, "needs >= 2 seed classes"

    fit_idx = np.where(finite)[0]
    kk = int(min(k, fit_idx.size - 1))
    model = LabelSpreading(
        kernel="knn", n_neighbors=max(1, kk), alpha=float(alpha), max_iter=60
    )
    model.fit(scaled[fit_idx], y_labels[fit_idx])
    seg[fit_idx] = model.transduction_.astype(np.float64)

    status = "" if not dropped else f"dropped {dropped} constant feature(s)"
    return seg, status
```

- [ ] **Step 4: Run tests** — `py -3 -m pytest tests/scripts/diag/test_segmentation.py -q` → 4 passed. If `test_recovers_a_planted_high_residual_region` is marginal, bump `attr_weight` in the test to 4.0 (the algorithm is sound; the synthetic's spatial spread competes with the attribute signal) — do NOT loosen the recall/fpr thresholds below 0.85 / 0.15.

- [ ] **Step 5: Commit**

```bash
git add scripts/diag/segmentation.py tests/scripts/diag/test_segmentation.py
git commit -m "feat(diag): seeded segmentation via k-NN label propagation"
```

---

## Task 3: register `grow_segmentation` as a step

**Files:**
- Modify: `scripts/diag/ops.py`
- Test: `tests/scripts/diag/test_grow_segmentation_op.py` (create)

**Interfaces:**
- Consumes: `grow_segmentation` (Task 2), `resolve_inputs` list mode (Task 1).
- Produces:
  ```python
  @step(
      "grow_segmentation",
      produces=["segment_id"],
      requires=["x", "y", "resid_z"],
      tier="derived",
  )
  def _op_grow_segmentation(cols, params, inputs): ...
  ```
  - `params`: `k` (default 15), `alpha` (0.2), `attr_weight` (1.0), `features` (list[str], default `["resid_z"]`).
  - `inputs["seeds"]` is the ordered `dict[str, np.ndarray]` from `resolve_inputs` list mode (or `{}` if unbound).
  - Returns `{"segment_id": seg}, {"segmentation_status": status, "segmentation_n_classes": int}`.
  - `seed_masks = list(inputs.get("seeds", {}).values())` — order preserved from `resolve_inputs`.
  - `feature_cols = [cols[f] for f in params.get("features", ["resid_z"]) if f in cols]`.

- [ ] **Step 1: Write the failing test**

```python
# tests/scripts/diag/test_grow_segmentation_op.py
import os
import sys

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", "scripts"))

from diag.registry import STEPS


def _cols(n=600, rng=None):
    rng = rng or np.random.default_rng(1)
    return {
        "x": rng.uniform(-30, 30, n),
        "y": rng.uniform(-30, 30, n),
        "resid_z": rng.normal(0, 1, n),
    }


def test_registered_with_the_right_contract():
    spec = STEPS["grow_segmentation"]
    assert spec.produces == ("segment_id",)
    assert spec.tier == "derived"
    assert "resid_z" in spec.requires


def test_op_segments_with_two_seed_masks():
    c = _cols()
    n = c["x"].size
    seeds = {"a": c["x"] < -15, "b": c["x"] > 15}
    out, metrics = STEPS["grow_segmentation"].fn(
        c, {"features": ["resid_z"]}, {"seeds": seeds}
    )
    assert out["segment_id"].shape == (n,)
    assert set(np.unique(out["segment_id"])) <= {0.0, 1.0}
    assert metrics["segmentation_status"] == ""


def test_op_degrades_to_minus_one_without_seeds():
    c = _cols()
    out, metrics = STEPS["grow_segmentation"].fn(c, {}, {})
    assert np.all(out["segment_id"] == -1)
    assert "seed" in metrics["segmentation_status"]


def test_op_passes_masked_nan_through_as_minus_one():
    c = _cols()
    c["resid_z"][:80] = np.nan
    seeds = {"a": c["x"] < -15, "b": c["x"] > 15}
    out, _ = STEPS["grow_segmentation"].fn(c, {}, {"seeds": seeds})
    assert np.all(out["segment_id"][:80] == -1)
```

- [ ] **Step 2: Run, verify fail** — `KeyError: 'grow_segmentation'`.

- [ ] **Step 3: Implement** (append to `scripts/diag/ops.py`, after `_op_hdbscan`)

```python
@step(
    "grow_segmentation",
    produces=["segment_id"],
    requires=["x", "y", "resid_z"],
    tier="derived",
)
def _op_grow_segmentation(cols: Columns, params: dict, inputs: dict):
    """Seeded segmentation: each bound seed-role layer is one class; LabelSpreading fills
    every other point. Degrades to all -1 below 2 seed classes. Not in DEFAULT_RECIPE --
    it needs seeds that do not exist by default."""
    from .segmentation import grow_segmentation

    feature_names = params.get("features") or ["resid_z"]
    feature_cols = [cols[f] for f in feature_names if f in cols]
    seeds = inputs.get("seeds") or {}
    seed_masks = list(seeds.values())
    seg, status = grow_segmentation(
        cols["x"],
        cols["y"],
        feature_cols,
        seed_masks,
        k=int(params.get("k", 15)),
        alpha=float(params.get("alpha", 0.2)),
        attr_weight=float(params.get("attr_weight", 1.0)),
    )
    n_classes = int(len({int(v) for v in seg[seg >= 0]}))
    return {"segment_id": seg}, {
        "segmentation_status": status,
        "segmentation_n_classes": n_classes,
    }
```

- [ ] **Step 4: Run** — `py -3 -m pytest tests/scripts/diag/test_grow_segmentation_op.py tests/scripts/diag/ -q` → new file 4 passed; **every existing test still green** (`grow_segmentation` not in `DEFAULT_RECIPE`, so no golden/runner test reaches it yet — that comes in Task 4).

- [ ] **Step 5: Commit**

```bash
git add scripts/diag/ops.py tests/scripts/diag/test_grow_segmentation_op.py
git commit -m "feat(diag): register grow_segmentation step"
```

---

## Task 4: `segment_id` as the 12th D1AN column

**Files:**
- Modify: `scripts/diag/runner.py`, `scripts/force_orchestrator.py`, `tests/scripts/diag/conftest.py`
- Test: `tests/scripts/diag/test_runner.py` (add), plus the relaxed golden assertion covers the rest

**Interfaces:**
- Consumes: Task 3's `segment_id` producer.
- Produces:
  - `PUBLIC_COLUMNS` gains `"segment_id"` (append, last). `_TRUNCATABLE` is **left unchanged** — see Global Constraints.
  - The assembly loop fills a missing `segment_id` with `-1.0` (every other missing column stays `0.0`).
  - `DIAG_VERSION = 6`.
  - `assert_columns_match_golden`: `set(expected) <= set(cols)`, and `set(cols) - set(expected)` must be `⊆ {"segment_id"}` with that column all `-1`.

- [ ] **Step 1: Write the failing test**

```python
# tests/scripts/diag/test_runner.py -- add near the other run_recipe tests


def test_default_recipe_emits_segment_id_all_minus_one():
    cols, _ = run_recipe(DEFAULT_RECIPE, _seed())
    assert "segment_id" in cols
    assert np.all(cols["segment_id"] == -1)
    assert cols["segment_id"].dtype == np.float32
```

And in `conftest.py`, a test-support change (not a test) — update `assert_columns_match_golden`.

- [ ] **Step 2: Run, verify fail** — `test_default_recipe_emits_segment_id_all_minus_one` fails (`segment_id` not in `PUBLIC_COLUMNS`); the two `assert_columns_match_golden` call sites still pass for now.

- [ ] **Step 3: Widen `PUBLIC_COLUMNS` only** (leave `_TRUNCATABLE` alone — `segment_id` is produced post-`tsa` and never reaches `_truncate`)

```python
PUBLIC_COLUMNS: tuple[str, ...] = (
    "t",
    "rev",
    "x",
    "y",
    "tsa_resid",
    "resid_z",
    "gi_star",
    "gi_sig",
    "cluster_id",
    "glosh",
    "env_band",
    "segment_id",
)
```

- [ ] **Step 4: Assembly fill**

In the `for name in PUBLIC_COLUMNS:` loop:

```python
for name in PUBLIC_COLUMNS:
    col = work.get(name)
    # segment_id defaults to -1 ("unsegmented"); 0 is a valid class index. Every other
    # missing/disabled column zero-fills as before.
    fill = -1.0 if name == "segment_id" else 0.0
    out[name] = (
        col[:n].astype(np.float32)
        if col is not None
        else np.full(n, fill, dtype=np.float32)
    )
```

- [ ] **Step 5: Relax `assert_columns_match_golden`**

```python
    golden = np.load(golden_path, allow_pickle=False)
    expected = {k: golden[k] for k in golden.files if not k.startswith("__")}
    for name in nondegenerate:
        assert np.count_nonzero(golden[name]) > 0, (
            f"golden {name!r} is degenerate -- fixture regenerated from a broken pipeline?"
        )
    # The frozen fixture predates segment_id (D1AN's 12th column). Every column the fixture
    # DOES contain must still be present and byte-identical; a column the run adds beyond the
    # fixture is allowed only if it is segment_id and is entirely unsegmented (-1).
    missing = set(expected) - set(cols)
    assert not missing, f"columns dropped vs the frozen reference: {missing}"
    extra = set(cols) - set(expected)
    assert extra <= {"segment_id"}, f"unexpected columns beyond the reference: {extra}"
    if "segment_id" in extra:
        assert np.all(cols["segment_id"] == -1), "default-path segment_id must be all -1"
    for name, want in expected.items():
        got = cols[name]
        assert got.dtype == want.dtype, f"column {name!r} dtype drifted"
        np.testing.assert_array_equal(
            got, want, err_msg=f"column {name!r} differs from the golden reference"
        )
    assert repr(sorted(metrics.items())) == str(golden["__metrics__"]), (
        "metrics payload differs from the golden reference"
    )
```

- [ ] **Step 6: `DIAG_VERSION = 6`** in `scripts/force_orchestrator.py`.

- [ ] **Step 7: Run the full diag suite** — `py -3 -m pytest tests/scripts/diag/ -q` → all green, including both golden call sites and the new `segment_id` test.

- [ ] **Step 8: Commit**

```bash
git add scripts/diag/runner.py scripts/force_orchestrator.py tests/scripts/diag/conftest.py tests/scripts/diag/test_runner.py
git commit -m "feat(diag): segment_id becomes the 12th D1AN column; DIAG_VERSION 6"
```

---

## Task 5: diag-service seeded-preview test

**Files:**
- Modify: `plugins/diag-service/tests/test_preview.py`

**Interfaces:**
- Consumes: Tasks 1–4. No service code change — `/preview` already forwards `layers` and calls `run_recipe`.

- [ ] **Step 1: Write the test** (fixture names per the file's existing `client` fixture — read it first if unsure)

```python
def test_preview_returns_segment_id_from_seeds(client):
    import copy

    recipe = copy.deepcopy(DEFAULT_RECIPE)
    recipe["steps"].append(
        {
            "id": "seg",
            "op": "grow_segmentation",
            "on": True,
            "params": {"features": ["resid_z"], "k": 15},
            "inputs": {"seeds": {"layers": ["a", "b"], "required": False}},
        }
    )
    big_left = [[[-1e9, -1e9], [0, -1e9], [0, 1e9], [-1e9, 1e9]]]
    big_right = [[[0, -1e9], [1e9, -1e9], [1e9, 1e9], [0, 1e9]]]
    body = {
        "analysis_id": "a1",
        "recipe": recipe,
        "layers": {
            "a": {
                "role": "seed",
                "geometry": {"polygons": big_left},
                "value": None,
                "version": 1,
            },
            "b": {
                "role": "seed",
                "geometry": {"polygons": big_right},
                "value": None,
                "version": 1,
            },
        },
    }
    r = client.post("/preview", json=body)
    assert r.status_code == 200, r.text
    got = _read_bytes(r.content)
    assert "segment_id" in got
    assert set(np.unique(got["segment_id"])) <= {
        0.0,
        1.0,
    }  # two classes, everything assigned
```

- [ ] **Step 2: Run** — `py -3 -m pytest plugins/diag-service/tests/ -q` → all green.

- [ ] **Step 3: Rebuild + smoke**

```bash
docker compose build diag-service && docker compose up -d diag-service
docker compose exec -T diag-service python -c "from diag.segmentation import grow_segmentation; print('seg in image OK')"
```

- [ ] **Step 4: Commit**

```bash
git add plugins/diag-service/tests/test_preview.py
git commit -m "test(diag-service): seeded preview returns segment_id"
```

---

## Task 6: frontend channel plumbing for `segmentId`

**Files:**
- Modify: `packages/force-plotting/src/selection.ts`, `recipeChannels.ts`, `DiagScatter.vue`, `diagAttrs.ts` (check)
- Test: `packages/force-plotting/src/selection.test.ts`

**Interfaces:**
- Consumes: nothing from earlier tasks (parallel-safe with 1–5).
- Produces:
  - `ChannelKey` union gains `'segmentId'`.
  - `WorkingSet` gains `segmentId: Float32Array`; `COLUMN_MAP` gains `segment_id: 'segmentId'`; `CHANNEL_ACCESSOR` gains `segmentId: (ws, i) => ws.segmentId[i]`.
  - `STEP_META['grow_segmentation']` = `{ label: 'Seeded segmentation', tier: 'derived', produces: ['segment_id'], params: [k, alpha, attr_weight number inputs] }`.
  - `PRODUCED_TO_CHANNEL['segment_id'] = 'segmentId'`; `ALL_CHANNELS` gains `{ key: 'segmentId', label: 'segment_id — seeded regions' }`.
  - `DiagScatter` renders `segmentId` through the SAME categorical path as `clusterMode` (12-colour palette, `-1` grey). Simplest: treat `props.channel === 'segmentId'` as a categorical channel alongside `clusterMode`.

- [ ] **Step 1: Check `diagAttrs.ts`** — `grep -n "segment\|cluster_id\|column" packages/force-plotting/src/diagAttrs.ts`. If it has a hardcoded expected-column list, add `segment_id`; if it is generic (reads `n_cols` from the header), no change. `selection.ts::workingSetFromD1an` iterates `COLUMN_MAP` and throws on a missing column — so a pre-Phase-F `attrs.d1an` (11 cols) will fail to load until re-baked. That is expected and covered by Task 8's re-bake.

- [ ] **Step 2: Write the failing test**

```ts
// packages/force-plotting/src/selection.test.ts -- extend makeAttrs() and add a case

// in makeAttrs(): add   segment_id: new Float32Array([-1, 0, 0, 1, 1]),

it('maps segment_id and reads it through the accessor', () => {
	const ws = workingSetFromD1an(makeAttrs());
	expect(Array.from(ws.segmentId)).toEqual([-1, 0, 0, 1, 1]);
	expect(CHANNEL_ACCESSOR.segmentId(ws, 3)).toBe(1);
});
```

(Every existing `makeAttrs()`-based test needs the new column too, or `workingSetFromD1an` throws — add `segment_id` to `makeAttrs()` once.)

- [ ] **Step 3: Run, verify fail** — `npm test -w @d1/force-plotting -- selection` → FAIL (`segment_id` missing / `segmentId` not on type).

- [ ] **Step 4: Implement `selection.ts`** — add to the `ChannelKey` union, `WorkingSet`, `COLUMN_MAP`, `CHANNEL_ACCESSOR`. (`workingSetFromD1an` and `matches` need no other change; a `{kind:'attribute', column:'segmentId'}` selection already works via `CHANNEL_ACCESSOR`.)

- [ ] **Step 5: Implement `recipeChannels.ts`** — `STEP_META['grow_segmentation']`:

```ts
	grow_segmentation: {
		label: 'Seeded segmentation', tier: 'derived', produces: ['segment_id'],
		params: [
			{ key: 'k', label: 'Neighbours k', kind: 'number', min: 3, max: 100, step: 1 },
			{ key: 'alpha', label: 'Clamping α', kind: 'number', min: 0.01, max: 0.9, step: 0.05 },
			{ key: 'attr_weight', label: 'Attr weight', kind: 'number', min: 0.1, max: 10, step: 0.1 },
		],
	},
```

plus `PRODUCED_TO_CHANNEL['segment_id'] = 'segmentId'` and `ALL_CHANNELS.push({ key: 'segmentId', label: 'segment_id — seeded regions' })`.

- [ ] **Step 6: Implement `DiagScatter.vue`** — where `clusterMode` selects the categorical shader path, also select it when `props.channel === 'segmentId'`. Concretely: a `const categorical = computed(() => props.clusterMode || props.channel === 'segmentId')` and use `categorical.value` everywhere `props.clusterMode` currently gates the palette branch / `uCluster` uniform. The `aValue < 0.0` → grey branch already covers `segment_id === -1`.

- [ ] **Step 7: Run tests + typecheck** — `npm test -w @d1/force-plotting && npm run typecheck -w @d1/force-plotting` → green, 0 errors.

- [ ] **Step 8: Commit**

```bash
git add packages/force-plotting/src/selection.ts packages/force-plotting/src/recipeChannels.ts packages/force-plotting/src/DiagScatter.vue packages/force-plotting/src/selection.test.ts
git commit -m "feat(diag-ui): segmentId channel — categorical render + recipe metadata"
```

---

## Task 7: recipe library — Directus migration + client + component

**Files:**
- Create: `db/migrations/20260903000109_diag_recipes_directus.sql`, `packages/force-plotting/src/diagRecipes.ts`, `diagRecipes.test.ts`, `RecipeLibrary.vue`
- Modify: `packages/force-plotting/src/index.ts`

**Interfaces:**
- Consumes: `Recipe` type.
- Produces:
  ```ts
  export interface SavedRecipe { recipe_id: string; name: string; recipe: Recipe; notes: string | null; }
  export function fetchRecipeLibrary(): Promise<SavedRecipe[]>;
  export function saveRecipe(p: { name: string; recipe: Recipe; notes?: string }): Promise<SavedRecipe>;
  export function deleteRecipe(recipeId: string): Promise<void>;
  ```
  - `RecipeLibrary.vue` props `{ library: SavedRecipe[]; currentRecipe: Recipe }`, emits `(e:'apply', r: Recipe)`, `(e:'saved')`, `(e:'deleted')`. Renders a `<select>` + Apply / Save as… / Delete. Save-as uses `window.prompt` (matches `saveProfile` in `ForceDashboard.vue`).

- [ ] **Step 1: Directus migration**

```sql
-- migrate:up
-- Register the diag_recipes library table with Directus so /items/diag_recipes is exposed
-- (the table was created in 20260901000106 but never registered). Mirrors how filter_profiles
-- and diag_layer are surfaced.
INSERT INTO directus_collections (collection, icon, note, hidden, singleton)
SELECT 'diag_recipes', 'menu_book', 'Named, reusable diagnostics recipes; applying one copies its document onto a cut.', false, false
WHERE NOT EXISTS (SELECT 1 FROM directus_collections WHERE collection = 'diag_recipes');

INSERT INTO directus_fields (collection, field, special, interface, options, readonly, hidden, sort, note)
SELECT collection, field, special, interface, options::json, readonly, hidden, sort, note
FROM (VALUES
    ('diag_recipes', 'recipe_id',  'uuid',         'input',      NULL,                  true,  true,  1, 'Primary key.'),
    ('diag_recipes', 'name',       NULL,           'input',      NULL,                  false, false, 2, 'Unique library name.'),
    ('diag_recipes', 'recipe',     NULL,           'input-code', '{"language":"json"}', false, false, 3, 'The recipe document copied onto machining_force_analysis.diag_recipe when applied.'),
    ('diag_recipes', 'notes',      NULL,           'input-multiline', NULL,             false, false, 4, NULL),
    ('diag_recipes', 'created_at', 'date-created', 'datetime',   NULL,                  true,  false, 5, NULL),
    ('diag_recipes', 'updated_at', 'date-updated', 'datetime',   NULL,                  true,  false, 6, NULL)
) v(collection, field, special, interface, options, readonly, hidden, sort, note)
WHERE NOT EXISTS (SELECT 1 FROM directus_fields f WHERE f.collection = 'diag_recipes' AND f.field = v.field);

-- migrate:down
DELETE FROM directus_fields WHERE collection = 'diag_recipes';
DELETE FROM directus_collections WHERE collection = 'diag_recipes';
```

- [ ] **Step 2: Run migration + restart Directus + verify**

```bash
MSYS_NO_PATHCONV=1 docker run --rm --network d1-database_d1net -v "$PWD/db/migrations:/db/migrations" \
  ghcr.io/amacneil/dbmate:2 -u "postgres://d1:change_me@postgres:5432/d1_database?sslmode=disable" --no-dump-schema up
docker compose restart directus   # wait healthy
```
Verify: `curl -s -H "Authorization: Bearer $TOK" http://localhost:8055/items/diag_recipes` → `{"data":[]}` (get `$TOK` via `/auth/login` with `admin@example.com` / `change_me_admin`).

- [ ] **Step 3: `diagRecipes.ts`** (mirror `diagLayers.ts`)

```ts
import { useForceHost } from './host';
import type { Recipe } from './recipeChannels';

export interface SavedRecipe {
	recipe_id: string;
	name: string;
	recipe: Recipe;
	notes: string | null;
}

const FIELDS = ['recipe_id', 'name', 'recipe', 'notes'];

export async function fetchRecipeLibrary(): Promise<SavedRecipe[]> {
	const res = await useForceHost().api.get('/items/diag_recipes', {
		params: { fields: FIELDS, sort: 'name', limit: -1 },
	});
	return (res.data?.data ?? []) as SavedRecipe[];
}

export async function saveRecipe(p: { name: string; recipe: Recipe; notes?: string }): Promise<SavedRecipe> {
	const res = await useForceHost().api.post('/items/diag_recipes',
		{ name: p.name, recipe: p.recipe, notes: p.notes ?? null }, { params: { fields: FIELDS } });
	return res.data.data as SavedRecipe;
}

export async function deleteRecipe(recipeId: string): Promise<void> {
	await useForceHost().api.delete(`/items/diag_recipes/${recipeId}`);
}
```

- [ ] **Step 4: `diagRecipes.test.ts`** — a shape test (the module is thin; assert `FIELDS` round-trips and `saveRecipe` posts `{name, recipe, notes}`). Mock `useForceHost` the way `host.test.ts` does.

```ts
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { setForceHost, resetForceHost, type ForceHost } from './host';
import { saveRecipe, fetchRecipeLibrary } from './diagRecipes';
import { DEFAULT_RECIPE } from './recipeChannels';

const post = vi.fn().mockResolvedValue({ data: { data: { recipe_id: '1', name: 'x', recipe: DEFAULT_RECIPE, notes: null } } });
const get = vi.fn().mockResolvedValue({ data: { data: [] } });

beforeEach(() => {
	resetForceHost();
	setForceHost({ api: { post, get } as unknown as ForceHost['api'] } as ForceHost);
	post.mockClear(); get.mockClear();
});

describe('diagRecipes', () => {
	it('saveRecipe posts name/recipe/notes', async () => {
		await saveRecipe({ name: 'Campaign A', recipe: DEFAULT_RECIPE });
		expect(post).toHaveBeenCalledWith('/items/diag_recipes',
			{ name: 'Campaign A', recipe: DEFAULT_RECIPE, notes: null }, expect.anything());
	});
	it('fetchRecipeLibrary returns the data array', async () => {
		expect(await fetchRecipeLibrary()).toEqual([]);
	});
});
```

- [ ] **Step 5: `RecipeLibrary.vue`**

```vue
<script setup lang="ts">
import { ref } from 'vue';
import type { Recipe } from './recipeChannels';
import { saveRecipe, deleteRecipe, type SavedRecipe } from './diagRecipes';

const props = defineProps<{ library: SavedRecipe[]; currentRecipe: Recipe }>();
const emit = defineEmits<{
	(e: 'apply', r: Recipe): void;
	(e: 'saved'): void;
	(e: 'deleted'): void;
}>();

const sel = ref<string>('');
const busy = ref(false);
const err = ref<string | null>(null);

function apply() {
	const r = props.library.find((x) => x.recipe_id === sel.value);
	if (r) emit('apply', JSON.parse(JSON.stringify(r.recipe)));
}
async function saveAs() {
	const name = window.prompt('Save recipe to the library as:');
	if (!name) return;
	busy.value = true; err.value = null;
	try { await saveRecipe({ name, recipe: props.currentRecipe }); emit('saved'); }
	catch (e: unknown) { err.value = (e as { message?: string })?.message || 'save failed (name taken?)'; }
	finally { busy.value = false; }
}
async function removeSel() {
	const r = props.library.find((x) => x.recipe_id === sel.value);
	if (!r || !window.confirm(`Delete recipe "${r.name}"?`)) return;
	busy.value = true;
	try { await deleteRecipe(r.recipe_id); sel.value = ''; emit('deleted'); }
	finally { busy.value = false; }
}
</script>

<template>
	<div class="recipe-library">
		<select v-model="sel" :disabled="busy">
			<option value="">— saved recipes —</option>
			<option v-for="r in library" :key="r.recipe_id" :value="r.recipe_id" :title="r.notes ?? ''">{{ r.name }}</option>
		</select>
		<button :disabled="!sel || busy" @click="apply">Apply</button>
		<button :disabled="busy" @click="saveAs">Save as…</button>
		<button v-if="sel" :disabled="busy" class="del" @click="removeSel">✕</button>
		<span v-if="err" class="err">{{ err }}</span>
	</div>
</template>

<style scoped>
.recipe-library { display: flex; flex-wrap: wrap; gap: 4px; align-items: center; font-size: 11px; }
.recipe-library select { flex: 1; min-width: 90px; font-size: 11px; padding: 3px 5px; background: var(--bg-2, #111a33); color: var(--text, #e5e7eb); border: 1px solid var(--border, rgba(255,255,255,0.14)); border-radius: 5px; }
.recipe-library button { font-size: 11px; padding: 3px 7px; border-radius: 5px; border: 1px solid var(--border, rgba(255,255,255,0.14)); background: var(--bg-2, #111a33); color: var(--text, #e5e7eb); cursor: pointer; }
.recipe-library button:disabled { opacity: 0.45; cursor: not-allowed; }
.recipe-library .del { color: var(--danger, #fca5a5); }
.recipe-library .err { color: var(--danger, #fca5a5); width: 100%; }
</style>
```

- [ ] **Step 6: Export from `index.ts`**

```ts
export { fetchRecipeLibrary, saveRecipe, deleteRecipe } from './diagRecipes';
export type { SavedRecipe } from './diagRecipes';
export { default as RecipeLibrary } from './RecipeLibrary.vue';
```

- [ ] **Step 7: Tests + typecheck** — `npm test -w @d1/force-plotting -- diagRecipes && npm run typecheck -w @d1/force-plotting`.

- [ ] **Step 8: Commit**

```bash
git add db/migrations/20260903000109_diag_recipes_directus.sql packages/force-plotting/src/diagRecipes.ts packages/force-plotting/src/diagRecipes.test.ts packages/force-plotting/src/RecipeLibrary.vue packages/force-plotting/src/index.ts
git commit -m "feat(diag-ui): recipe library — save / apply / delete against diag_recipes"
```

---

## Task 8: RecipePanel — add/remove step, seed-layer binding, library slot

**Files:**
- Modify: `packages/force-plotting/src/RecipePanel.vue`, `DiagnosticsWorkbench.vue`
- Test: headless (Task 10)

**Interfaces:**
- Consumes: `RecipeLibrary` (Task 7), `STEP_META` (Task 6), seed-layer names from the workbench's `layers`.
- Produces:
  - `RecipePanel` new props: `seedLayerNames: string[]`, `library: SavedRecipe[]`.
  - `RecipePanel` new emits: `(e:'apply', r: Recipe)`, `(e:'library-changed')` — forwarded from `RecipeLibrary`.
  - **Add step:** a `<select>` of registered ops NOT already in the recipe (`Object.keys(STEP_META)` minus present ops). Choosing one appends `{ id: 'x'+Date.now(), op, on: true, params: <defaults from STEP_META>, ... }`. For `grow_segmentation`, also seed `inputs: { seeds: { layers: [], required: false } }`.
  - **Remove step:** an `✕` on any step whose id is not `s1..s7` (the default steps are not removable; added steps are).
  - **Seed binding editor:** when a step is `grow_segmentation` and `on`, render a checkbox list of `seedLayerNames`; toggling updates `s.inputs.seeds.layers` (order = insertion order of checks — append on check, splice on uncheck). If `seedLayerNames` is empty, show "paint a seed layer first".
  - `RecipeLibrary` rendered in `.rp-footer` above the preview line.

- [ ] **Step 1: Implement `RecipePanel.vue`** — extend the script:

```ts
import { STEP_META, type Recipe, type RecipeStep } from './recipeChannels';
import RecipeLibrary from './RecipeLibrary.vue';
import type { SavedRecipe } from './diagRecipes';
import { computed } from 'vue';

const props = defineProps<{
	recipe: Recipe;
	baked: boolean;
	bakeStale: boolean;
	previewing: boolean;
	previewMs: number | null;
	previewError: string | null;
	seedLayerNames: string[];
	library: SavedRecipe[];
}>();
const emit = defineEmits<{
	(e: 'update:recipe', r: Recipe): void;
	(e: 'bake'): void;
	(e: 'apply', r: Recipe): void;
	(e: 'library-changed'): void;
}>();

const DEFAULT_IDS = new Set(['s1', 's2', 's3', 's4', 's5', 's6', 's7']);
const addableOps = computed(() => {
	const present = new Set(props.recipe.steps.map((s) => s.op));
	return Object.keys(STEP_META).filter((op) => !present.has(op));
});

function defaultParams(op: string): Record<string, number | string | null> {
	const out: Record<string, number | string | null> = {};
	for (const p of STEP_META[op]?.params ?? []) {
		out[p.key] = p.kind === 'number' ? (p.min ?? 0) : (p.options?.[0]?.value ?? '');
	}
	return out;
}
function addStep(op: string) {
	if (!op) return;
	edit((r) => {
		const step: RecipeStep = { id: `x${Date.now()}`, op, on: true, params: defaultParams(op) };
		if (op === 'grow_segmentation') step.inputs = { seeds: { layers: [], required: false } };
		r.steps.push(step);
	});
}
function removeStep(id: string) {
	edit((r) => { r.steps = r.steps.filter((s) => s.id !== id); });
}
function seedBound(s: RecipeStep): string[] {
	return ((s.inputs?.seeds as { layers?: string[] } | undefined)?.layers) ?? [];
}
function toggleSeed(id: string, name: string) {
	edit((r) => {
		const s = r.steps.find((x) => x.id === id);
		if (!s) return;
		s.inputs = s.inputs ?? {};
		const seeds = (s.inputs.seeds as { layers: string[]; required: boolean } | undefined)
			?? { layers: [], required: false };
		seeds.layers = seeds.layers.includes(name)
			? seeds.layers.filter((n) => n !== name)
			: [...seeds.layers, name];
		s.inputs.seeds = seeds;
	});
}
```

Template additions: an "add step" `<select>` after the `<ol>`; an `✕` button in `.step-head` `v-if="!DEFAULT_IDS.has(s.id)"`; the seed checkbox list inside the params block `v-if="s.op === 'grow_segmentation' && s.on"`; `<RecipeLibrary :library="library" :current-recipe="recipe" @apply="(r) => emit('apply', r)" @saved="emit('library-changed')" @deleted="emit('library-changed')" />` at the top of `.rp-footer`.

- [ ] **Step 2: Wire `DiagnosticsWorkbench.vue`**

```ts
import { fetchRecipeLibrary, type SavedRecipe } from './diagRecipes';

const library = ref<SavedRecipe[]>([]);
async function loadLibrary() { try { library.value = await fetchRecipeLibrary(); } catch { library.value = []; } }
onMounted(loadLibrary);

const seedLayerNames = computed(() => layers.value.filter((l) => l.role === 'seed').map((l) => l.name));

function onApplyRecipe(r: Recipe) { recipe.value = r; }   // fires the debounced preview via the existing watch
```

Pass to `<RecipePanel>`: `:seed-layer-names="seedLayerNames"`, `:library="library"`, `@apply="onApplyRecipe"`, `@library-changed="loadLibrary"`.

- [ ] **Step 3: Segment channel legend** — when `channel === 'segmentId'`, the Spatial footer shows a tiny legend mapping class index → seed-layer name. Reuse the `boundMasks`-style computed:

```ts
const segmentLegend = computed(() => {
	const seg = recipe.value.steps.find((s) => s.op === 'grow_segmentation' && s.on);
	const names = (seg?.inputs?.seeds as { layers?: string[] } | undefined)?.layers ?? [];
	return names.map((n, i) => ({ id: i, name: n }));
});
```

Render it in the footer `v-if="channel === 'segmentId' && segmentLegend.length"`, each row a `clusterColorCss(id)` swatch + name.

- [ ] **Step 4: typecheck both workspaces** — `npm run typecheck -w @d1/force-plotting && npm run typecheck -w force-app-web` → 0 errors. (`RecipePanel`'s two new required props mean every caller must pass them — `DiagnosticsWorkbench` is the only one; update its template.)

- [ ] **Step 5: Run package tests** — `npm test -w @d1/force-plotting` → all green (existing `RecipePanel` has no unit test; the new props are additive).

- [ ] **Step 6: Commit**

```bash
git add packages/force-plotting/src/RecipePanel.vue packages/force-plotting/src/DiagnosticsWorkbench.vue
git commit -m "feat(diag-ui): add/remove steps, seed-layer binding, recipe library in the panel"
```

---

## Task 9: the requeue trigger

**Files:**
- Create: `db/migrations/20260903000110_diag_requeue_trigger.sql`
- Test: `tests/scripts/test_diag_requeue_trigger.py` (create) — SQL-level via psycopg2

**Interfaces:**
- Produces: `BEFORE UPDATE ON machining_force_analysis` trigger that sets `diag_status='pending'`, `diag_requested_at=now()` when `diag_recipe` or `tool_setup_id` changed.

- [ ] **Step 1: Migration**

```sql
-- migrate:up
-- Editing a cut's diag_recipe or tool_setup_id outside the workbench (e.g. in the Directus
-- admin, or by applying a library recipe) must requeue it -- otherwise the daemon never
-- re-bakes and the artifacts silently disagree with the stored recipe. process_diag_row's
-- completion UPDATE touches diag_status/path/points/version/metrics/hash/error but NOT
-- diag_recipe or tool_setup_id, so IS DISTINCT FROM is false on daemon writes and this does
-- not fight the daemon.
CREATE OR REPLACE FUNCTION diag_requeue_on_recipe_change() RETURNS trigger AS $$
BEGIN
    IF NEW.diag_recipe IS DISTINCT FROM OLD.diag_recipe
       OR NEW.tool_setup_id IS DISTINCT FROM OLD.tool_setup_id THEN
        NEW.diag_status := 'pending';
        NEW.diag_requested_at := now();
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS diag_requeue_on_recipe_change ON machining_force_analysis;
CREATE TRIGGER diag_requeue_on_recipe_change
    BEFORE UPDATE ON machining_force_analysis
    FOR EACH ROW EXECUTE FUNCTION diag_requeue_on_recipe_change();

-- migrate:down
DROP TRIGGER IF EXISTS diag_requeue_on_recipe_change ON machining_force_analysis;
DROP FUNCTION IF EXISTS diag_requeue_on_recipe_change();
```

- [ ] **Step 2: Run migration** (same dbmate invocation as Task 7 Step 2).

- [ ] **Step 3: Write the test**

```python
# tests/scripts/test_diag_requeue_trigger.py
import os
import pytest

psycopg2 = pytest.importorskip("psycopg2")

DSN = os.environ.get(
    "DATABASE_URL", "postgres://d1:change_me@localhost:5432/d1_database"
)


@pytest.fixture
def conn():
    c = psycopg2.connect(DSN)
    yield c
    c.rollback()
    c.close()


def _smallest_done_row(cur):
    # smallest cut (ffe1286d, ~17.9k pts) -> least likely to be mid-bake and holding a row lock
    cur.execute(
        "SELECT id FROM machining_force_analysis WHERE diag_status='done' "
        "ORDER BY diag_points ASC LIMIT 1"
    )
    row = cur.fetchone()
    if not row:
        pytest.skip("no baked diag row to test against")
    return row[0]


def test_editing_diag_recipe_requeues(conn):
    with conn.cursor() as cur:
        cur.execute(
            "SET lock_timeout = '3s'"
        )  # fail loud on a daemon collision, don't hang
        rid = _smallest_done_row(cur)
        cur.execute(
            "UPDATE machining_force_analysis SET diag_recipe = '{\"steps\":[]}'::jsonb "
            "WHERE id = %s RETURNING diag_status",
            [rid],
        )
        assert cur.fetchone()[0] == "pending"
    conn.rollback()


def test_touching_unrelated_columns_does_not_requeue(conn):
    with conn.cursor() as cur:
        cur.execute("SET lock_timeout = '3s'")
        rid = _smallest_done_row(cur)
        cur.execute(
            "UPDATE machining_force_analysis SET diag_points = diag_points "
            "WHERE id = %s RETURNING diag_status",
            [rid],
        )
        assert cur.fetchone()[0] == "done"
    conn.rollback()
```

- [ ] **Step 4: Run** — `py -3 -m pytest tests/scripts/test_diag_requeue_trigger.py -q` (needs `.env`'s `DATABASE_URL`; set it in the shell or the test's default DSN covers it).

- [ ] **Step 5: Commit**

```bash
git add db/migrations/20260903000110_diag_requeue_trigger.sql tests/scripts/test_diag_requeue_trigger.py
git commit -m "feat(diag): requeue a cut when its diag_recipe or tool_setup_id changes"
```

---

## Task 10: end-to-end verification

**Files:** none (verification) + any fixes surfaced.

- [ ] **Step 1: Full suites**

```bash
py -3 -m pytest tests/scripts/diag/ plugins/diag-service/tests/ tests/scripts/test_orchestrator_diag_layers.py tests/scripts/test_diag_requeue_trigger.py -q
npm test -w @d1/force-plotting
npm run typecheck -w @d1/force-plotting
npm run typecheck -w force-app-web
```
All green, 0 type errors. Record counts.

- [ ] **Step 2: Rebuild service, restart daemon, re-bake all cuts under `DIAG_VERSION=6`**

```bash
docker compose build diag-service && docker compose up -d diag-service
# restart the daemon (kill the PID in %TEMP%\d1_orch_err.log; relaunch with .env loaded)
```
`claim_diag`'s staleness clause requeues every `done` row whose `diag_version < 6`. The daemon processes them **serially** (~40 s wall clock each — MATLAB + PotreeConverter, as measured in Phase E), so ~4 min total for 5 cuts. Poll `SELECT id, diag_status, diag_version FROM machining_force_analysis WHERE diag_status IN ('done','pending','processing')` in a loop until every row is `done` at `diag_version = 6` — do not assume timing.
Verify one file:
```python
# via C:\Program Files\Python313\python.exe
from diag.d1an import read_d1an

d = read_d1an("infra/octrees/diag/<op>/attrs.d1an")
assert "segment_id" in d and (d["segment_id"] == -1).all()  # no seeds bound -> all -1
```

- [ ] **Step 3: Headless workbench (playwright-core)**

Drive `/diagnostics` in the force app (login via `/auth/login`, seed `localStorage['force-app.auth']`, as in the Phase E script):
1. select a baked cut.
2. RecipePanel: "add step" → `grow_segmentation` appears; its params (k / α / attr_weight) render; "paint a seed layer first" shows (no seed layers yet).
3. LayerPanel: `+ seed` twice → `seed-1`, `seed-2`; draw a triangle in each on the scatter.
4. Back in RecipePanel: the two seed names now have checkboxes; check both.
5. Within ~1 s a `/diag/preview` fires whose body has `steps[].op == 'grow_segmentation'` with `inputs.seeds.layers == ['seed-1','seed-2']` and `layers` carrying both geometries.
6. Channel selector → `segment_id`; the scatter recolours categorically; the footer legend shows `0 → seed-1`, `1 → seed-2`.
7. RecipeLibrary: "Save as…" → name it; reload the page → the recipe appears in the dropdown; select it + Apply on a *different* cut → that cut's recipe panel shows `grow_segmentation`.
8. Screenshot at step 6; assert the canvas is not uniformly one colour.

- [ ] **Step 4: Trigger in situ** — `curl -X PATCH .../items/machining_force_analysis/<id>` setting `diag_recipe` to a trivial edit; confirm `diag_status` flips to `pending` and the daemon re-bakes.

- [ ] **Step 5: fix anything broken, re-run Step 1, commit fixes**

- [ ] **Step 6: Finish the branch** — "I'm using the finishing-a-development-branch skill to complete this work." Full suite on the merged result, base branch `main`, merge `--no-ff`, push, delete branch (per the standing "merge each phase as it finishes").

---

## Self-Review

**Spec coverage:**
- Component 1 (`grow_segmentation` step) → Tasks 2 (algorithm) + 3 (registration). Algorithm, degradation, masking, 2-class/multi-class all covered. ✔
- Component 2 (`resolve_inputs` list mode) → Task 1. Ordered dict, skip-missing, required-raises. ✔
- Component 3 (the new channel) → Task 4 (server: PUBLIC_COLUMNS/_TRUNCATABLE/fill/DIAG_VERSION/golden relax) + Task 6 (frontend: ChannelKey/WorkingSet/STEP_META/DiagScatter). `clusterStats` explicitly not extended — matches spec. ✔
- Component 4 (recipe library) → Task 7 (migration + client + component) + Task 8 (wire into panel). Apply copies onto local recipe, no auto-bake, seeds not touched. ✔
- Component 5 (trigger) → Task 9. `IS DISTINCT FROM` on `diag_recipe`/`tool_setup_id` only; daemon-write safety asserted by test. ✔
- Testing section → every named test maps to a task: planted-region recovery (T2), multi-class order (T2/T3), degradation (T2/T3), `resolve_inputs` list mode (T1), recipe-hash stability of a list binding (**gap — add to T1**), default-recipe equivalence (T4), trigger (T9), library round-trip (T7 client test + T10 headless). ✔ after the T1 fix below.
- "add/remove step" — implied by RecipePanel's own comment ("Step reorder / add / remove are Phase F") and required to reach `grow_segmentation` (not in DEFAULT_RECIPE) → Task 8. Drag-reorder deferred (validate_recipe enforces ordering; append is the correct position for a `resid_z`-consumer). ✔

**Gap found in self-review — fix inline:** Task 1 has no recipe-hash-stability test for a `{"layers": [...]}` binding. Add to Task 1 Step 1:

```python
def test_list_binding_hashes_stably_and_order_sensitively():
    from diag.recipe import recipe_hash

    base = {
        "steps": [
            {"id": "a", "op": "frame_transform", "on": True, "params": {}},
            {
                "id": "s",
                "op": "grow_segmentation",
                "on": True,
                "params": {},
                "inputs": {"seeds": {"layers": ["x", "y"]}},
            },
        ]
    }
    same = {
        "steps": [
            dict(base["steps"][0]),
            {
                "id": "s",
                "op": "grow_segmentation",
                "on": True,
                "params": {},
                "inputs": {"seeds": {"layers": ["x", "y"]}},
            },
        ]
    }
    swapped = {
        "steps": [
            dict(base["steps"][0]),
            {
                "id": "s",
                "op": "grow_segmentation",
                "on": True,
                "params": {},
                "inputs": {"seeds": {"layers": ["y", "x"]}},
            },
        ]
    }
    assert recipe_hash(base) == recipe_hash(same)
    assert recipe_hash(base) != recipe_hash(swapped)  # class order is semantic
```

(This exercises `_canonical` in `recipe.py` — confirm it JSON-encodes the `inputs` value without sorting nested lists; `dict(sorted(inputs.items()))` only sorts the top-level keys, so a nested list order is preserved. If a test shows otherwise, that is a `_canonical` bug to fix in Task 1.)

**Placeholder scan:** no "TBD" / "add error handling" / bare "write tests". Every code step has real code. The `diagAttrs.ts` check in Task 6 Step 1 is a genuine conditional ("if it hardcodes … add …"), not a placeholder.

**Type consistency:**
- `grow_segmentation(x, y, features: list, seed_masks: list, *, k, alpha, attr_weight)` — identical signature in Task 2 interface, impl, and Task 3's call. ✔
- `Inputs` widened to include `dict[str, np.ndarray]` in Task 1; Task 3 reads `inputs.get("seeds")` as a dict. ✔
- `SavedRecipe { recipe_id, name, recipe, notes }` — Task 7 client, `diagRecipes.test.ts`, `RecipeLibrary.vue` props, Task 8 workbench. ✔
- `RecipeLibrary` emits `apply`/`saved`/`deleted`; `RecipePanel` forwards as `apply`/`library-changed`; `DiagnosticsWorkbench` handles `onApplyRecipe`/`loadLibrary`. Names consistent. ✔
- `segmentId` (camel) / `segment_id` (snake) — `COLUMN_MAP` maps snake→camel exactly as the other 11; `PRODUCED_TO_CHANNEL['segment_id'] = 'segmentId'`. ✔
- `STEP_META['grow_segmentation'].params` keys (`k`, `alpha`, `attr_weight`) match the op's `params.get(...)` keys in Task 3. ✔
