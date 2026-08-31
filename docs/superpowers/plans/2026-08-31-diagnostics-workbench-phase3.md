# Diagnostics Workbench Phase 3 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add spatial statistics to the diagnostics pipeline — Getis-Ord Gi* hotspot detection with FDR correction, and HDBSCAN clustering with an outlier-score proxy — so `resid_z` anomalies become spatial hotspots with a significance flag and a cluster identity, not just per-point z-scores.

**Architecture:** A new pure-function module, `scripts/diag/spatial.py`, implements Gi*/BH-FDR and a grid-reduce-then-cluster-then-broadcast HDBSCAN pipeline, entirely independent of the database, MATLAB, or the orchestrator. `pipeline.py`'s `analyse()` wires it in as four new D1AN columns. The orchestrator picks up the new columns automatically (it already writes whatever `analyse()` returns) but needs one real addition: a requeue mechanism, since none currently exists — bumping `DIAG_VERSION` today does nothing without it.

**Tech Stack:** NumPy, SciPy (`cKDTree`, `scipy.stats.norm`), `scikit-learn>=1.3` (`sklearn.cluster.HDBSCAN`).

**Spec:** `docs/superpowers/specs/2026-08-30-diagnostics-workbench-design.md` (Component 3), continuing `docs/superpowers/plans/2026-08-30-diagnostics-workbench.md`'s "Phase 3 — Spatial statistics".

## Global Constraints

- `sklearn.cluster.HDBSCAN` (verified locally at 1.9.0) exposes `probabilities_` but **not** `outlier_scores_` — there is no true GLOSH score available from this dependency. `glosh` in this plan means `1 - probabilities_`, a documented proxy, not the GLOSH algorithm. Do not add the standalone `hdbscan` package to get real GLOSH — it carries native-compile risk on the Windows orchestrator host that the whole point of choosing scikit-learn was to avoid.
- No live diag octree exists yet (the pre-existing, unrelated MATLAB/archive regression from the Phase 1 session is still unresolved). Every task here is verified with synthetic data.
- The Gi* neighbourhood size (`k`) and the HDBSCAN grid-reduction target are provisional defaults, not tuned values — the master plan explicitly defers real tuning until there's real data to tune against. Say so in the code, don't hide it.
- Never claim a step passes without running it and reading the output.
- Python target `py312`; ruff `line-length = 88`, `select = ["E","F","I","N","UP","W"]`, `ignore = ["E501"]`.

---

## File Structure

**New:**

| File | Responsibility |
|---|---|
| `scripts/diag/spatial.py` | Getis-Ord Gi* + Benjamini-Hochberg FDR; grid-reduce + HDBSCAN + broadcast-back |
| `tests/scripts/diag/test_spatial.py` | Unit tests for the above |

**Modified:**

| File | Change |
|---|---|
| `scripts/diag/pipeline.py` | `analyse()` gains `gi_star`, `gi_sig`, `cluster_id`, `glosh` columns |
| `scripts/force_orchestrator.py` | `DIAG_VERSION` → 2; `claim_diag` also requeues `done` rows with an older `diag_version` |
| `scripts/requirements.txt` | add `scikit-learn>=1.3` |
| `tests/scripts/diag/test_pipeline.py` | extend the existing ground-truth test to check the new columns |

**Explicitly out of scope:** Panel D / cluster-overlay UI (no real data to render against — see Global Constraints), any Directus/orchestrator-host `pip install` (the constraint below is a note for whoever deploys this, not a step in this plan).

---

### Task 1: Getis-Ord Gi* and Benjamini-Hochberg FDR

**Files:**
- Create: `scripts/diag/spatial.py`
- Test: `tests/scripts/diag/test_spatial.py`

**Interfaces:**
- Consumes: nothing
- Produces:
  - `getis_ord_gi_star(x: np.ndarray, y: np.ndarray, v: np.ndarray, k: int = 30) -> tuple[np.ndarray, np.ndarray]` returning `(gi_star, p_values)`
  - `benjamini_hochberg(p_values: np.ndarray, alpha: float = 0.05) -> np.ndarray` (bool array)

**The Gi\* formula being implemented** (k-nearest-neighbour binary weights, including self — so every point has the same neighbourhood size `k`, which keeps the weight-sum terms constant across points and the vectorised form simple):

```
Gi* = (sum_j(w_ij * v_j) - vbar * sum_j(w_ij)) / (s * sqrt((n*sum_j(w_ij^2) - sum_j(w_ij)^2) / (n-1)))
```

where `vbar`/`s` are the mean/std over **all** `n` points (not just the neighbourhood), and with binary kNN weights `sum_j(w_ij) = sum_j(w_ij^2) = k` for every point.

- [ ] **Step 1: Write the failing test**

```python
# tests/scripts/diag/test_spatial.py
import os
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", "scripts"))

from diag.spatial import benjamini_hochberg, getis_ord_gi_star


def test_uniform_noise_field_yields_almost_no_hotspots():
    # THE regression test: a field with no real spatial structure must not light up.
    rng = np.random.default_rng(0)
    n = 4000
    x = rng.uniform(0, 100, n)
    y = rng.uniform(0, 100, n)
    v = rng.normal(size=n)
    gi_star, p_values = getis_ord_gi_star(x, y, v, k=30)
    sig = benjamini_hochberg(p_values, alpha=0.05)
    assert sig.sum() / n < 0.02


def test_implanted_hot_cluster_is_recovered():
    rng = np.random.default_rng(1)
    n = 4000
    x = rng.uniform(0, 100, n)
    y = rng.uniform(0, 100, n)
    v = rng.normal(size=n)
    hot = (x > 40) & (x < 50) & (y > 40) & (y < 50)
    v[hot] += 6.0
    gi_star, p_values = getis_ord_gi_star(x, y, v, k=30)
    sig = benjamini_hochberg(p_values, alpha=0.05)
    # most of the implanted cluster should come back significant and positive (a hotspot,
    # not a coldspot)
    assert sig[hot].mean() > 0.7
    assert np.median(gi_star[hot]) > 0
    # the background, away from the cluster, should mostly not be flagged
    assert sig[~hot].mean() < 0.05


def test_getis_ord_requires_more_points_than_k():
    x = np.zeros(5)
    with pytest.raises(ValueError, match="at least"):
        getis_ord_gi_star(x, x, x, k=10)


def test_getis_ord_handles_zero_variance_field():
    x = np.arange(50, dtype=np.float64)
    v = np.ones(50)
    gi_star, p_values = getis_ord_gi_star(x, x, v, k=10)
    assert np.all(gi_star == 0)
    assert np.all(p_values == 1)


def test_benjamini_hochberg_flags_the_small_p_values():
    p = np.array([0.001, 0.002, 0.01, 0.5, 0.8, 0.95])
    sig = benjamini_hochberg(p, alpha=0.05)
    assert sig[:3].all()
    assert not sig[3:].any()


def test_benjamini_hochberg_all_large_p_values_flags_nothing():
    p = np.full(20, 0.9)
    sig = benjamini_hochberg(p, alpha=0.05)
    assert not sig.any()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd C:\Users\WS-X180-PC\Documents\GitHub\D1-Database\.claude\worktrees\diagnostics-workbench && python -m pytest tests/scripts/diag/test_spatial.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'diag.spatial'`

- [ ] **Step 3: Write the implementation**

```python
# scripts/diag/spatial.py
"""Spatial statistics: Getis-Ord Gi* hotspot detection with FDR correction, and HDBSCAN
clustering with an outlier-score proxy.

Provisional parameters. The Gi* neighbourhood size (`k`) and the HDBSCAN grid-reduction
target are defaults chosen to be reasonable on synthetic data, not tuned against real cuts --
the master plan defers that tuning until real diag octrees exist, which is still blocked by a
pre-existing MATLAB/archive-compatibility issue unrelated to this pipeline. Treat every
default in this module as a starting point to revisit, not a calibrated constant.

No true GLOSH here: sklearn.cluster.HDBSCAN exposes `probabilities_` (cluster-membership
confidence, 0 for noise) but not `outlier_scores_` (the actual GLOSH algorithm, only in the
standalone `hdbscan` package). `glosh` in this module is `1 - probabilities_` -- a standard,
honestly-labeled proxy, not literal GLOSH. Adding the standalone package for real GLOSH would
reintroduce the native-compile dependency risk that choosing scikit-learn was meant to avoid.
"""

from __future__ import annotations

import numpy as np
from scipy.spatial import cKDTree
from scipy.stats import norm


def getis_ord_gi_star(
    x: np.ndarray, y: np.ndarray, v: np.ndarray, k: int = 30
) -> tuple[np.ndarray, np.ndarray]:
    """Getis-Ord Gi* statistic per point, using k-nearest-neighbour binary spatial weights
    (each point's own neighbourhood includes itself, size k for every point).

    Returns (gi_star, p_values): p_values are two-sided, from the standard normal
    approximation Gi* is asymptotically distributed under.
    """
    x = np.asarray(x, dtype=np.float64)
    y = np.asarray(y, dtype=np.float64)
    v = np.asarray(v, dtype=np.float64)
    n = x.size
    if n < k + 1:
        raise ValueError(f"need at least k+1={k + 1} points for k={k} neighbours, got {n}")

    tree = cKDTree(np.column_stack([x, y]))
    _, idx = tree.query(np.column_stack([x, y]), k=k)  # idx includes the point itself

    vbar = float(v.mean())
    s = float(v.std())
    if s == 0.0:
        # A perfectly uniform field has no spatial structure to detect; Gi* is undefined
        # (division by zero) and every point is equally "not a hotspot".
        return np.zeros(n), np.ones(n)

    neighbor_sum = v[idx].sum(axis=1)
    w_sum = float(k)       # binary weights, all 1, k of them (including self)
    w_sq_sum = float(k)    # squared weights are also 1 each
    numerator = neighbor_sum - vbar * w_sum
    denom = s * np.sqrt((n * w_sq_sum - w_sum**2) / (n - 1))
    gi_star = numerator / denom
    p_values = 2.0 * norm.sf(np.abs(gi_star))
    return gi_star, p_values


def benjamini_hochberg(p_values: np.ndarray, alpha: float = 0.05) -> np.ndarray:
    """Benjamini-Hochberg step-up FDR correction. Returns a boolean array: True where the
    point is significant at the given false-discovery rate."""
    p_values = np.asarray(p_values, dtype=np.float64)
    n = p_values.size
    order = np.argsort(p_values)
    ranked = p_values[order]
    thresh = (np.arange(1, n + 1) / n) * alpha
    below = ranked <= thresh
    if not below.any():
        return np.zeros(n, dtype=bool)
    k_max = int(np.nonzero(below)[0].max())
    significant = np.zeros(n, dtype=bool)
    significant[order[: k_max + 1]] = True
    return significant
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/scripts/diag/test_spatial.py -v`
Expected: 6 passed

- [ ] **Step 5: Lint and commit**

```bash
python -m ruff check scripts/diag tests/scripts/diag
git add scripts/diag/spatial.py tests/scripts/diag/test_spatial.py
git commit -m "feat(diag): add Getis-Ord Gi* hotspot detection with BH-FDR"
```

---

### Task 2: Grid-reduce, HDBSCAN cluster, broadcast back

**Files:**
- Modify: `scripts/diag/spatial.py`
- Modify: `tests/scripts/diag/test_spatial.py`

**Interfaces:**
- Consumes: nothing new
- Produces:
  - `grid_reduce(x: np.ndarray, y: np.ndarray, v: np.ndarray, target_n: int) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]` returning `(xr, yr, vr, cell_id)` — `cell_id` has one entry per input point, indexing into `xr`/`yr`/`vr`
  - `cluster_hdbscan(xr: np.ndarray, yr: np.ndarray, vr: np.ndarray, min_cluster_size: int = 10) -> tuple[np.ndarray, np.ndarray]` returning `(labels, glosh)`, both sized like `xr`
  - `assign_from_grid(cell_id: np.ndarray, labels_reduced: np.ndarray, glosh_reduced: np.ndarray) -> tuple[np.ndarray, np.ndarray]` returning full-resolution `(cluster_id, glosh)`

**Design note — exact assignment, not approximate NN:** the design spec describes broadcasting cluster labels back to full resolution via "approximate nearest neighbour". `grid_reduce` already knows exactly which cell every input point fell into, so `assign_from_grid` is a direct array index (`labels_reduced[cell_id]`) — exact, and cheaper than a KD-tree query. This is a deliberate improvement on the spec's original phrasing, not a deviation to flag as a problem.

- [ ] **Step 1: Write the failing test**

Add to `tests/scripts/diag/test_spatial.py`:

```python
from diag.spatial import assign_from_grid, cluster_hdbscan, grid_reduce


def test_grid_reduce_every_point_gets_a_valid_cell():
    rng = np.random.default_rng(2)
    n = 5000
    x = rng.uniform(0, 100, n)
    y = rng.uniform(0, 100, n)
    v = rng.normal(size=n)
    xr, yr, vr, cell_id = grid_reduce(x, y, v, target_n=500)
    assert xr.shape == yr.shape == vr.shape
    assert cell_id.shape == (n,)
    assert cell_id.min() >= 0
    assert cell_id.max() < xr.size
    # target_n is a target, not an exact count (only occupied cells are kept), but the
    # reduction should be in the right ballpark and never expand the point count.
    assert 0 < xr.size <= n


def test_grid_reduce_cell_representative_is_the_mean_of_its_points():
    # Two points sharing one cell (grid coarse enough): the representative must be their mean.
    x = np.array([0.0, 0.0, 10.0])
    y = np.array([0.0, 0.0, 10.0])
    v = np.array([2.0, 4.0, 100.0])
    xr, yr, vr, cell_id = grid_reduce(x, y, v, target_n=2)
    assert cell_id[0] == cell_id[1]
    assert cell_id[2] != cell_id[0]
    i = cell_id[0]
    assert vr[i] == 3.0  # mean of 2.0 and 4.0


def test_cluster_hdbscan_separates_two_well_separated_blobs():
    rng = np.random.default_rng(3)
    blob_a = rng.normal(loc=(0, 0), scale=0.5, size=(200, 2))
    blob_b = rng.normal(loc=(50, 50), scale=0.5, size=(200, 2))
    xy = np.vstack([blob_a, blob_b])
    v = rng.normal(size=400)
    labels, glosh = cluster_hdbscan(xy[:, 0], xy[:, 1], v, min_cluster_size=10)
    assert labels.shape == (400,)
    assert glosh.shape == (400,)
    # at least two distinct non-noise clusters found
    assert len(set(labels[labels >= 0].tolist())) >= 2
    # the two blobs must not share a cluster label
    labels_a = set(labels[:200][labels[:200] >= 0].tolist())
    labels_b = set(labels[200:][labels[200:] >= 0].tolist())
    assert labels_a.isdisjoint(labels_b)
    assert np.all(glosh >= 0.0) and np.all(glosh <= 1.0)


def test_assign_from_grid_broadcasts_by_cell():
    cell_id = np.array([0, 0, 1, 2])
    labels_reduced = np.array([5.0, -1.0, 7.0])
    glosh_reduced = np.array([0.1, 0.9, 0.3])
    cluster_id, glosh = assign_from_grid(cell_id, labels_reduced, glosh_reduced)
    np.testing.assert_array_equal(cluster_id, [5.0, 5.0, -1.0, 7.0])
    np.testing.assert_array_equal(glosh, [0.1, 0.1, 0.9, 0.3])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/scripts/diag/test_spatial.py -v -k "grid_reduce or cluster_hdbscan or assign_from_grid"`
Expected: FAIL — `ImportError: cannot import name 'grid_reduce' from 'diag.spatial'`

- [ ] **Step 3: Write the implementation**

Append to `scripts/diag/spatial.py`:

```python
def grid_reduce(
    x: np.ndarray, y: np.ndarray, v: np.ndarray, target_n: int
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Bin points into a square grid sized so the number of occupied cells is roughly
    `target_n`, and collapse each cell to the mean (x, y, v) of the points inside it.

    Returns (xr, yr, vr, cell_id): the reduced representative points, and `cell_id` -- one
    entry per input point, the index into xr/yr/vr it was collapsed into. `cell_id` is what
    lets assign_from_grid broadcast a clustering computed on the reduced set back onto every
    original point exactly, with no further nearest-neighbour search needed.
    """
    x = np.asarray(x, dtype=np.float64)
    y = np.asarray(y, dtype=np.float64)
    v = np.asarray(v, dtype=np.float64)
    n = x.size
    if target_n < 1:
        raise ValueError("target_n must be >= 1")

    xlo, xhi = float(x.min()), float(x.max())
    ylo, yhi = float(y.min()), float(y.max())
    xspan = (xhi - xlo) or 1.0
    yspan = (yhi - ylo) or 1.0
    # Aim for a roughly square grid whose total cell count is target_n, split between axes by
    # their relative span so cells are roughly square in data units, not just in index count.
    aspect = xspan / yspan
    ny = max(1, int(round(np.sqrt(target_n / aspect))))
    nx = max(1, int(round(target_n / ny)))

    ix = np.clip(((x - xlo) / xspan * nx).astype(np.int64), 0, nx - 1)
    iy = np.clip(((y - ylo) / yspan * ny).astype(np.int64), 0, ny - 1)
    flat = ix * ny + iy

    unique_flat, cell_id = np.unique(flat, return_inverse=True)
    n_cells = unique_flat.size

    xr = np.zeros(n_cells)
    yr = np.zeros(n_cells)
    vr = np.zeros(n_cells)
    counts = np.zeros(n_cells)
    np.add.at(xr, cell_id, x)
    np.add.at(yr, cell_id, y)
    np.add.at(vr, cell_id, v)
    np.add.at(counts, cell_id, 1.0)
    xr /= counts
    yr /= counts
    vr /= counts
    return xr, yr, vr, cell_id.astype(np.int64)


def cluster_hdbscan(
    xr: np.ndarray, yr: np.ndarray, vr: np.ndarray, min_cluster_size: int = 10
) -> tuple[np.ndarray, np.ndarray]:
    """HDBSCAN on the reduced (xr, yr, vr) point set. Returns (labels, glosh):
    `labels` is HDBSCAN's own cluster id per point (-1 = noise); `glosh` is `1 -
    probabilities_`, a proxy for outlier-ness (see module docstring -- this is not the
    literal GLOSH algorithm, which sklearn's HDBSCAN does not implement).
    """
    from sklearn.cluster import HDBSCAN

    xr = np.asarray(xr, dtype=np.float64)
    yr = np.asarray(yr, dtype=np.float64)
    vr = np.asarray(vr, dtype=np.float64)
    X = np.column_stack([xr, yr, vr])
    h = HDBSCAN(min_cluster_size=min_cluster_size).fit(X)
    glosh = 1.0 - h.probabilities_
    return h.labels_.astype(np.float64), glosh.astype(np.float64)


def assign_from_grid(
    cell_id: np.ndarray, labels_reduced: np.ndarray, glosh_reduced: np.ndarray
) -> tuple[np.ndarray, np.ndarray]:
    """Broadcast the reduced set's cluster labels/glosh to every full-resolution point via
    its grid cell (exact -- see grid_reduce's docstring)."""
    cell_id = np.asarray(cell_id, dtype=np.int64)
    return labels_reduced[cell_id], glosh_reduced[cell_id]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/scripts/diag/test_spatial.py -v`
Expected: all 10 pass (the 6 from Task 1 plus 4 new)

- [ ] **Step 5: Lint and commit**

```bash
python -m ruff check scripts/diag tests/scripts/diag
git add scripts/diag/spatial.py tests/scripts/diag/test_spatial.py
git commit -m "feat(diag): add grid-reduce + HDBSCAN clustering with exact broadcast-back"
```

---

### Task 3: Wire spatial statistics into `analyse()`

**Files:**
- Modify: `scripts/diag/pipeline.py`
- Modify: `tests/scripts/diag/test_pipeline.py`

**Interfaces:**
- Consumes: `getis_ord_gi_star`, `benjamini_hochberg`, `grid_reduce`, `cluster_hdbscan`, `assign_from_grid` (Tasks 1–2)
- Produces: `analyse()`'s returned `columns` dict gains `gi_star`, `gi_sig`, `cluster_id`, `glosh` (all float32); two new optional kwargs: `gi_k: int = 30`, `hdbscan_grid_target: int = 20_000`, `hdbscan_min_cluster_size: int = 10`

`hdbscan_grid_target` defaults to 20,000, not the "1-5M" figure floated earlier in this project's planning — that number was sized for the *full* octree's raw point count, not for what actually gets fed into HDBSCAN. HDBSCAN's own memory/time cost is what `grid_reduce` exists to bound, and this default is picked to keep a unit test and a real-cut analysis both fast; it is exactly the kind of number the Global Constraints section already flags as provisional.

- [ ] **Step 1: Write the failing test**

Extend `tests/scripts/diag/test_pipeline.py`'s existing ground-truth test (do not write a new function — extend the one that already validates the implanted anomaly, so a single cut proves both the residual detection and the spatial statistics agree on where the anomaly is):

```python
def test_pipeline_recovers_implanted_anomaly_location():
    """The test that validates the science: an anomaly implanted at a known revolution
    must come back as the strongest residual at that same revolution, AND as a
    significant spatial hotspot with its own cluster."""
    t, fx, fy, fz, rpm, revs, x, y, fs, hit = _synthetic_cut()
    cache = {
        "n": t.size,
        "fs": fs,
        "feed": 0.05,
        "diam": 80.0,
        "cs_sec": 0.0,
        "ce_sec": float(t[-1]),
        "t": t,
        "fx": fx,
        "fy": fy,
        "fz": fz,
        "rpm": rpm,
        "revs": revs,
    }
    cols, metrics = analyse(cache, x, y, samples_per_rev=SPR)
    peak_rev = cols["rev"][int(np.argmax(np.abs(cols["resid_z"])))]
    assert abs(peak_rev - 25.0) < 0.2
    assert metrics["n_points"] == cols["resid_z"].size

    # the point of peak residual must also read as a significant spatial hotspot
    peak_idx = int(np.argmax(np.abs(cols["resid_z"])))
    assert cols["gi_sig"][peak_idx] == 1.0
    assert cols["gi_star"][peak_idx] > 0
```

Also add to `test_pipeline_columns_are_aligned_and_finite` and `test_pipeline_columns_include_spatial_coordinates`, so the full-column-set assertions don't silently pass while missing the new keys:

```python
def test_pipeline_columns_include_spatial_coordinates():
    t, fx, fy, fz, rpm, revs, x, y, fs, _ = _synthetic_cut(n_rev=8)
    cache = {
        "n": t.size,
        "fs": fs,
        "feed": 0.05,
        "diam": 80.0,
        "cs_sec": 0.0,
        "ce_sec": float(t[-1]),
        "t": t,
        "fx": fx,
        "fy": fy,
        "fz": fz,
        "rpm": rpm,
        "revs": revs,
    }
    cols, _ = analyse(cache, x, y, samples_per_rev=SPR)
    assert set(cols) == {
        "t", "rev", "x", "y", "tsa_resid", "resid_z",
        "gi_star", "gi_sig", "cluster_id", "glosh",
    }
    r = np.hypot(cols["x"], cols["y"])
    expected_r = 40.0 - 0.05 * cols["rev"]
    np.testing.assert_allclose(r, expected_r, atol=0.05)
```

(The `test_pipeline_columns_are_aligned_and_finite` test already iterates `cols.items()` generically checking size/finite/dtype for every key present — it needs no code change, but will now also exercise the four new columns automatically once they exist.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/scripts/diag/test_pipeline.py -v`
Expected: FAIL — `KeyError: 'gi_sig'` (or the column-set assertion mismatch)

- [ ] **Step 3: Wire the new columns into `analyse()`**

In `scripts/diag/pipeline.py`, add the import:

```python
from .spatial import assign_from_grid, benjamini_hochberg, cluster_hdbscan, getis_ord_gi_star, grid_reduce
```

Update the signature:

```python
def analyse(
    cache: dict,
    x: np.ndarray,
    y: np.ndarray,
    *,
    mount_deg: float = 0.0,
    samples_per_rev: int = DEFAULT_SAMPLES_PER_REV,
    fn_hz: float | None = None,
    channel: str = "fp",
    gi_k: int = 30,
    hdbscan_grid_target: int = 20_000,
    hdbscan_min_cluster_size: int = 10,
) -> tuple[dict[str, np.ndarray], dict]:
```

After the existing `resid_z = radial_detrend(r, residual)` line and before the `orders, amp = order_spectrum(...)` line, insert:

```python
    # Spatial statistics run on the same (x_ang, y_ang, resid_z) the detrend already used.
    # Gi* needs at least gi_k+1 points; short test cuts can fall under that, so degrade to
    # "nothing significant" rather than raising -- a two-revolution synthetic cut should not
    # crash the whole pipeline over a statistic it has too few points to compute.
    if n > gi_k:
        gi_star, gi_p = getis_ord_gi_star(x_ang, y_ang, resid_z, k=gi_k)
        gi_sig = benjamini_hochberg(gi_p, alpha=0.05).astype(np.float64)
    else:
        gi_star = np.zeros(n)
        gi_sig = np.zeros(n)

    xr, yr, vr, cell_id = grid_reduce(x_ang, y_ang, resid_z, target_n=hdbscan_grid_target)
    if xr.size >= hdbscan_min_cluster_size:
        labels_r, glosh_r = cluster_hdbscan(xr, yr, vr, min_cluster_size=hdbscan_min_cluster_size)
        cluster_id, glosh = assign_from_grid(cell_id, labels_r, glosh_r)
    else:
        cluster_id = np.full(n, -1.0)
        glosh = np.zeros(n)
```

Update the `columns` dict:

```python
    columns = {
        "t": t_ang.astype(np.float32),
        "rev": rev_grid.astype(np.float32),
        "x": x_ang.astype(np.float32),
        "y": y_ang.astype(np.float32),
        "tsa_resid": residual.astype(np.float32),
        "resid_z": resid_z.astype(np.float32),
        "gi_star": gi_star.astype(np.float32),
        "gi_sig": gi_sig.astype(np.float32),
        "cluster_id": cluster_id.astype(np.float32),
        "glosh": glosh.astype(np.float32),
    }
    return columns, metrics
```

Also update the module docstring's column list (currently says "Emits t, rev, x, y, tsa_resid and resid_z"):

```python
"""One analysis pass: D1LC cache + spiral coordinates -> D1AN columns + metrics.

Phase 1-3 scope. Emits t, rev, x, y, tsa_resid, resid_z, gi_star, gi_sig, cluster_id and
glosh. env_band (envelope analysis) arrives in Phase 4.
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/scripts/diag/ -v`
Expected: all pass (35 total: the prior 25 from Phase 1/2's work on this file, plus 10 from Task 1-2 of this plan — verify the exact count printed matches what actually ran, don't assume)

- [ ] **Step 5: Lint and commit**

```bash
python -m ruff check scripts/diag tests/scripts/diag
git add scripts/diag/pipeline.py tests/scripts/diag/test_pipeline.py
git commit -m "feat(diag): wire spatial statistics into the phase-1 pipeline"
```

---

### Task 4: Version bump and real requeue logic

**Files:**
- Modify: `scripts/force_orchestrator.py`
- Modify: `scripts/requirements.txt`

**Interfaces:**
- Consumes: nothing new
- Produces: `claim_diag` now also claims `diag_status='done'` rows whose `diag_version` is older than the current `DIAG_VERSION`

**The gap being closed:** `DIAG_VERSION` is currently written on every successful row but never read back for comparison — `claim_diag`'s `WHERE` clause only ever matches `diag_status='pending'`. Bumping the constant to 2 today would silently do nothing to the rows already processed under version 1; they would sit forever reporting stale (pre-spatial-statistics) `diag_metrics` with no way to know they're outdated short of a manual `UPDATE`.

- [ ] **Step 1: Add scikit-learn to the orchestrator's requirements**

`scripts/requirements.txt` currently reads:

```
openpyxl>=3.1
psycopg2-binary>=2.9
```

Change to:

```
openpyxl>=3.1
psycopg2-binary>=2.9
scikit-learn>=1.3
```

- [ ] **Step 2: Bump `DIAG_VERSION` and add requeue logic**

In `scripts/force_orchestrator.py`, find:

```python
DIAG_CACHE_POINTS = 5_000_000
DIAG_VERSION = 1
DIAG_SAMPLES_PER_REV = 256
```

Change to:

```python
DIAG_CACHE_POINTS = 5_000_000
# Bump whenever analyse()'s column set or its parameters change in a way that makes an
# already-'done' row's diag_metrics/D1AN stale. claim_diag requeues 'done' rows with an
# older diag_version automatically -- see claim_diag's WHERE clause below.
DIAG_VERSION = 2
DIAG_SAMPLES_PER_REV = 256
```

Find `claim_diag`:

```python
def claim_diag(conn, limit: int = 1):
    """Claim pending diagnostics rows. Concurrency is deliberately 1 by default: this host
    also serves Directus, and a clustering pass that starves the database mid-experiment is
    a worse outcome than a slow queue."""
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            """
            WITH picked AS (
                SELECT id FROM machining_force_analysis
                 WHERE diag_status='pending'
                 ORDER BY diag_requested_at NULLS FIRST
                 LIMIT %s FOR UPDATE SKIP LOCKED
            )
            UPDATE machining_force_analysis a SET diag_status='processing', updated_at=now()
              FROM picked WHERE a.id = picked.id
         RETURNING a.id, a.operation_id, a.pulses_per_rev, a.inner_diameter, a.outer_diameter, a.filter_chain::text AS filter_chain,
                   (SELECT metadata->>'archive_path' FROM directus_files WHERE id = a.directus_files_id) AS archive_path
        """,
            [limit],
        )
        rows = cur.fetchall()
    conn.commit()
    return rows
```

Replace with:

```python
def claim_diag(conn, limit: int = 1):
    """Claim pending diagnostics rows, PLUS previously-'done' rows whose diag_version is
    older than the current DIAG_VERSION -- a version bump alone changes nothing without this;
    it is what makes "bump DIAG_VERSION to invalidate and requeue" (see the migration's own
    comment on the diag_version column) actually true. Concurrency is deliberately 1 by
    default: this host also serves Directus, and a clustering pass that starves the database
    mid-experiment is a worse outcome than a slow queue."""
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            """
            WITH picked AS (
                SELECT id FROM machining_force_analysis
                 WHERE diag_status='pending'
                    OR (diag_status='done' AND (diag_version IS NULL OR diag_version < %s))
                 ORDER BY diag_requested_at NULLS FIRST
                 LIMIT %s FOR UPDATE SKIP LOCKED
            )
            UPDATE machining_force_analysis a SET diag_status='processing', updated_at=now()
              FROM picked WHERE a.id = picked.id
         RETURNING a.id, a.operation_id, a.pulses_per_rev, a.inner_diameter, a.outer_diameter, a.filter_chain::text AS filter_chain,
                   (SELECT metadata->>'archive_path' FROM directus_files WHERE id = a.directus_files_id) AS archive_path
        """,
            [DIAG_VERSION, limit],
        )
        rows = cur.fetchall()
    conn.commit()
    return rows
```

- [ ] **Step 3: Verify the module still imports and lints**

Run: `python -c "import sys; sys.path.insert(0,'scripts'); import force_orchestrator; print('DIAG_VERSION =', force_orchestrator.DIAG_VERSION)"`
Expected: `DIAG_VERSION = 2`, no other output, exit 0

Run: `python -m ruff check scripts/force_orchestrator.py`
Expected: no findings

- [ ] **Step 4: Run the full diag test suite one more time**

Run: `python -m pytest tests/scripts/ -v`
Expected: all pass — this file wasn't the target of new tests in this task, but a broken import here would be caught by the same suite that imports `force_orchestrator` indirectly through nothing else in this plan, so this is a cheap final safety check before committing infrastructure code with no direct test of its own SQL (the SQL change itself needs a live Postgres to exercise, which this plan does not assume is available — see the Phase 1 session's notes on verifying orchestrator changes against d1-server when one is).

- [ ] **Step 5: Commit**

```bash
git add scripts/force_orchestrator.py scripts/requirements.txt
git commit -m "feat(diag): bump DIAG_VERSION to 2 and requeue stale done rows"
```

---

## Self-Review Notes

**Spec coverage:** Component 3's "Getis-Ord Gi* / Local Moran's I → FDR-corrected hotspots" — Gi*/BH-FDR implemented (Task 1); Local Moran's I is not, and was never committed to in the master plan's Phase 3 description either — it's a plausible future addition, not a gap in this plan. Component 3's "HDBSCAN on a grid-reduced set → cluster_id + glosh" — implemented (Task 2), with the GLOSH caveat documented rather than silently substituted. The master plan's "bumps DIAG_VERSION to invalidate and requeue" — implemented for real in Task 4, where before this plan it was aspirational text with no code behind it.

**Known gap carried forward, not silently dropped:** Panel D / cluster-overlay UI has no task here — there is no real diag octree to render against yet (same blocker noted throughout the Phase 1/2 work), and building UI against synthetic data alone would mean re-verifying it against real data later anyway. Tracked as the next piece of work once that data exists, not forgotten.

**Type consistency check:** `analyse()`'s new kwargs (`gi_k`, `hdbscan_grid_target`, `hdbscan_min_cluster_size`) match `spatial.py`'s actual parameter names (`k`, `target_n`, `min_cluster_size`) at each call site — deliberately renamed when passed through `analyse()`'s own signature for clarity in that context (`gi_k` disambiguates from a future `hdbscan_k`-shaped parameter, `hdbscan_grid_target` disambiguates from `gi_k`'s own "target" framing), not a naming drift bug. `cluster_id`/`glosh` column names match exactly what the design spec's D1AN table (Component 5.1) already names them, so the LAS extra-dim loop in `process_diag_row` (which iterates `columns` generically) needs no changes to pick these up.
