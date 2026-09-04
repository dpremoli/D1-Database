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

_MAD_TO_SIGMA = 1.4826


def getis_ord_gi_star(
    x: np.ndarray, y: np.ndarray, v: np.ndarray, k: int = 30
) -> tuple[np.ndarray, np.ndarray]:
    """Getis-Ord Gi* statistic per point, using k-nearest-neighbour binary spatial weights
    (each point's own neighbourhood includes itself, size k for every point).

    Returns (gi_star, p_values): p_values are two-sided, from the standard normal
    approximation Gi* is asymptotically distributed under.

    The textbook formula normalises by the GLOBAL mean/std of `v`. That is exactly wrong for
    this pipeline's actual input: `v` is a residual that may already carry a handful of
    extreme, sparse outliers -- the very things being searched for. A non-robust std is
    dominated by those outliers (verified against this pipeline's own synthetic ground-truth
    cut: a single implanted anomaly of 25 points out of ~10000 inflated the global std from
    ~1 to ~3.6, which alone dropped every Gi* score below significance, including the
    anomaly's own). Median and MAD-based sigma are used instead, the same substitution
    detrend.py already makes for the same reason.
    """
    x = np.asarray(x, dtype=np.float64)
    y = np.asarray(y, dtype=np.float64)
    v = np.asarray(v, dtype=np.float64)
    n = x.size
    if n < k + 1:
        raise ValueError(
            f"need at least k+1={k + 1} points for k={k} neighbours, got {n}"
        )

    tree = cKDTree(np.column_stack([x, y]))
    _, idx = tree.query(np.column_stack([x, y]), k=k)  # idx includes the point itself

    vbar = float(np.median(v))
    s = float(np.median(np.abs(v - vbar))) * _MAD_TO_SIGMA
    if s == 0.0:
        # A perfectly uniform field has no spatial structure to detect; Gi* is undefined
        # (division by zero) and every point is equally "not a hotspot".
        return np.zeros(n), np.ones(n)

    neighbor_sum = v[idx].sum(axis=1)
    w_sum = float(k)  # binary weights, all 1, k of them (including self)
    w_sq_sum = float(k)  # squared weights are also 1 each
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
    features = np.column_stack([xr, yr, vr])
    # copy=False pins today's default explicitly -- sklearn warns that it flips to True in
    # 1.10; behaviour is unchanged, this just silences the FutureWarning ahead of that.
    h = HDBSCAN(min_cluster_size=min_cluster_size, copy=False).fit(features)
    glosh = 1.0 - h.probabilities_
    return h.labels_.astype(np.float64), glosh.astype(np.float64)


def assign_from_grid(
    cell_id: np.ndarray, labels_reduced: np.ndarray, glosh_reduced: np.ndarray
) -> tuple[np.ndarray, np.ndarray]:
    """Broadcast the reduced set's cluster labels/glosh to every full-resolution point via
    its grid cell (exact -- see grid_reduce's docstring).

    Kept, and still the right tool when you want the reduction itself to be visible (the
    equivalence tests use it), but NOT what the ops call any more: because every boundary
    lands on a cell edge, the result reads as blocky. See assign_by_neighbours.
    """
    cell_id = np.asarray(cell_id, dtype=np.int64)
    return labels_reduced[cell_id], glosh_reduced[cell_id]


def assign_by_neighbours(
    x: np.ndarray,
    y: np.ndarray,
    xr: np.ndarray,
    yr: np.ndarray,
    labels_reduced: np.ndarray,
    glosh_reduced: np.ndarray,
    k: int = 4,
) -> tuple[np.ndarray, np.ndarray]:
    """Carry a clustering computed on the reduced set back to full resolution by an
    inverse-distance-weighted vote over the `k` nearest reduced centroids.

    Why this exists. `grid_reduce` sizes its grid for a target CELL COUNT, so at the default
    grid_target=20000 it is about 141x141 cells across whatever extent it is handed. Pairing
    it with `assign_from_grid`, which gives every point its own cell's label, quantized each
    cluster boundary to one cell -- roughly 1/141 of the view, at EVERY zoom level, since
    zooming shrinks the cells but never adds any. No parameter could remove that, so the fix
    had to be in the assignment rather than in the reduction.

    Voting over neighbouring centroids lets a boundary fall anywhere between them, so it
    follows the data. `-1` (noise) votes like any other label rather than abstaining: were it
    ignored, every noise point beside a cluster would be absorbed into it and noise regions
    would disappear. glosh gets the same weighted mean, which also stops it reading as
    piecewise-constant.

    `k` is deliberately not a recipe parameter -- it controls the smoothness of the hand-off,
    not the clustering, and exposing it would invite tuning the wrong knob.
    """
    x = np.asarray(x, dtype=np.float64)
    y = np.asarray(y, dtype=np.float64)
    xr = np.asarray(xr, dtype=np.float64)
    yr = np.asarray(yr, dtype=np.float64)
    labels_reduced = np.asarray(labels_reduced, dtype=np.float64)
    glosh_reduced = np.asarray(glosh_reduced, dtype=np.float64)

    if xr.size == 0:
        return np.full(x.size, -1.0), np.zeros(x.size)
    kq = int(max(1, min(k, xr.size)))

    tree = cKDTree(np.column_stack([xr, yr]))
    dist, idx = tree.query(np.column_stack([x, y]), k=kq)
    # cKDTree drops the trailing axis when k == 1; restore it so one code path handles both.
    if kq == 1:
        dist = dist[:, None]
        idx = idx[:, None]

    # Inverse-distance weights. A point coincident with a centroid is at distance 0, which
    # must hand that centroid ALL the weight rather than yielding inf/nan: those rows collapse
    # to a one-hot weight on the zero-distance neighbour(s).
    with np.errstate(divide="ignore"):
        w = 1.0 / dist
    exact = ~np.isfinite(w)
    rows_exact = exact.any(axis=1)
    if rows_exact.any():
        w[rows_exact] = exact[rows_exact].astype(np.float64)

    neighbour_labels = labels_reduced[idx]

    # Majority vote by summed weight. The label set is small (cluster ids plus -1), so
    # accumulating a column per distinct label is both cheaper and clearer than a general
    # argmax over (point, neighbour) pairs.
    uniq = np.unique(labels_reduced)
    scores = np.empty((x.size, uniq.size), dtype=np.float64)
    for j, lab in enumerate(uniq):
        scores[:, j] = np.where(neighbour_labels == lab, w, 0.0).sum(axis=1)
    out_labels = uniq[np.argmax(scores, axis=1)]

    wsum = w.sum(axis=1)
    out_glosh = (glosh_reduced[idx] * w).sum(axis=1) / np.where(wsum > 0, wsum, 1.0)

    return out_labels.astype(np.float64), out_glosh.astype(np.float64)
