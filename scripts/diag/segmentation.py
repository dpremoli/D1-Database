"""Seeded segmentation: turn a handful of painted example regions into a full per-point
class map via semi-supervised label propagation over a k-NN graph.

Classical, not learned -- no training set, matching the pipeline's rejection of PointNet++/
U-Net. LabelSpreading over [x, y, scaled attributes] is exactly "classify every point from
sparse labels"; it is deterministic, multi-class, and needs no dependency the pipeline does
not already carry. Provisional defaults, like the rest of scripts/diag/spatial.py -- treat
them as starting points to tune against real cuts, not calibrated constants.
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
    """Propagate the seed classes to every point.

    `features` are the non-spatial columns (e.g. [resid_z]); each is z-scored and then
    multiplied by `attr_weight` so spatial-vs-attribute distance is tunable. `seed_masks`
    is ordered -- `seed_masks[c]` is True where a point is a painted example of class `c`,
    and that index becomes the point's `segment_id`.

    Returns (segment_id, status): `segment_id` is float64 length n, the class index per
    point or -1 where unsegmentable (fewer than 2 seed classes, a masked NaN feature, too
    few finite points). `status` is '' on a clean run or a short reason string.
    """
    from sklearn.preprocessing import StandardScaler
    from sklearn.semi_supervised import LabelSpreading

    x = np.asarray(x, dtype=np.float64)
    y = np.asarray(y, dtype=np.float64)
    n = x.size
    seg = np.full(n, -1.0)

    if sum(1 for m in seed_masks if np.any(m)) < 2:
        return seg, "needs >= 2 seed classes"

    cols = [x, y]
    dropped = 0
    for f in features:
        f = np.asarray(f, dtype=np.float64)
        finite_f = f[np.isfinite(f)]
        if finite_f.size and np.ptp(finite_f) > 0:
            cols.append(f)
        else:
            dropped += 1
    F = np.column_stack(cols)

    finite = np.all(np.isfinite(F), axis=1)
    if int(finite.sum()) < max(4, k + 1):
        return seg, "too few finite points to propagate"

    scaled = np.zeros_like(F, dtype=np.float64)  # ~finite rows stay 0 and are never fit/used
    scaled[finite] = StandardScaler().fit_transform(F[finite])
    if scaled.shape[1] > 2:
        scaled[:, 2:] *= float(attr_weight)

    y_labels = np.full(n, -1)
    for c, m in enumerate(seed_masks):
        y_labels[np.asarray(m, dtype=bool) & finite] = c
    if len({int(v) for v in y_labels[y_labels >= 0]}) < 2:
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
