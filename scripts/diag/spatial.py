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
        raise ValueError(
            f"need at least k+1={k + 1} points for k={k} neighbours, got {n}"
        )

    tree = cKDTree(np.column_stack([x, y]))
    _, idx = tree.query(np.column_stack([x, y]), k=k)  # idx includes the point itself

    vbar = float(v.mean())
    s = float(v.std())
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
