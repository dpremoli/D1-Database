"""Radial detrending and robust scoring.

In face turning the cutting speed changes continuously as the radius falls, so the force
carries a strong deterministic radial trend. Run any global outlier statistic on the raw
signal and it will faithfully report that the middle of the part differs from the edge — on
every cut, forever. Removing the radial trend first is what makes the remaining variation
attributable to the material rather than to the geometry.

Binned median + MAD rather than a polynomial fit: the trend shape is not known a priori, and
a median is not dragged around by the very outliers being searched for — up to a point. A
macrozone is spatially contiguous, so it can be the *majority* of the points in the bin it
falls in; median has only a 50% breakdown point, so a single pass lets a large-enough,
dense-enough hotspot pull its own bin's "normal" trend toward itself and understate its own
z-score. One reweighting pass fixes this cheaply: points flagged after the first pass are
excluded from the bin statistics before the trend is recomputed, the way a Hampel filter
refines its own threshold. Two passes is enough for the anomaly sizes this pipeline cares
about (a macrozone is a real minority of any cut's points even when it dominates one bin);
a full iteratively-reweighted fit is not needed here.
"""

from __future__ import annotations

import numpy as np

_MAD_TO_SIGMA = 1.4826
_REFINE_Z = 3.5
_MAX_PASSES = 2
_WINDOW_HALF_SPAN = (
    2  # aggregate +/-2 neighbouring bins per output centre (5 bins total)
)


def _bin_trend(
    r: np.ndarray,
    v: np.ndarray,
    edges: np.ndarray,
    min_per_bin: int,
    weight: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """One pass of moving-window median/MAD, using only points where `weight` is True.

    Output resolution is one value per bin, but each bin's statistics pool points from
    `_WINDOW_HALF_SPAN` bins on either side too. A macrozone can be a large fraction of the
    single bin it falls in without being a large fraction of that wider pooled window, which
    is what keeps a spatially contiguous anomaly under the median's 50% breakdown point.
    """
    n_bins = edges.size - 1
    idx = np.clip(np.digitize(r, edges) - 1, 0, n_bins - 1)
    centres = 0.5 * (edges[:-1] + edges[1:])
    med = np.full(n_bins, np.nan)
    mad = np.full(n_bins, np.nan)
    order = np.argsort(idx, kind="stable")
    bounds = np.searchsorted(idx[order], np.arange(n_bins + 1))
    for b in range(n_bins):
        lo_bin = max(0, b - _WINDOW_HALF_SPAN)
        hi_bin = min(n_bins - 1, b + _WINDOW_HALF_SPAN)
        sel = order[bounds[lo_bin] : bounds[hi_bin + 1]]
        sel = sel[weight[sel]]
        if sel.size >= min_per_bin:
            vb = v[sel]
            m = np.median(vb)
            med[b] = m
            mad[b] = np.median(np.abs(vb - m))
    return med, mad, centres


def radial_detrend(
    r: np.ndarray, v: np.ndarray, n_bins: int = 200, min_per_bin: int = 8
) -> np.ndarray:
    """Return a robust z-score of `v` against its own radial trend.

    Bins by radius, takes the median and MAD in each sufficiently-populated bin, interpolates
    both across radius, then reports (v - trend) / (1.4826 * MAD). Bins with fewer than
    `min_per_bin` samples are ignored and interpolated across, so a thin outer ring cannot
    define its own baseline from three points. A flagged-point-exclusion pass follows (see
    module docstring) so a dense, spatially contiguous anomaly does not corrupt the trend it
    is supposed to stand out from.
    """
    r = np.asarray(r, dtype=np.float64)
    v = np.asarray(v, dtype=np.float64)
    if r.shape != v.shape:
        raise ValueError(f"r shape {r.shape} does not match v shape {v.shape}")
    if r.size == 0:
        return np.zeros(0, dtype=np.float64)

    lo, hi = float(np.min(r)), float(np.max(r))
    if not np.isfinite(lo) or not np.isfinite(hi) or hi <= lo:
        return np.zeros_like(v)

    edges = np.linspace(lo, hi, n_bins + 1)
    weight = np.ones(v.shape, dtype=bool)
    z = np.zeros_like(v)

    for _ in range(_MAX_PASSES):
        med, mad, centres = _bin_trend(r, v, edges, min_per_bin, weight)
        good = np.isfinite(med)
        if not np.any(good):
            return np.zeros_like(v)

        trend = np.interp(r, centres[good], med[good])
        scale = np.interp(r, centres[good], mad[good]) * _MAD_TO_SIGMA
        # A bin can be genuinely noiseless (a flat synthetic, a saturated region). Fall back
        # to the global scale there rather than dividing by zero and reporting infinite
        # outliers.
        global_scale = float(np.median(mad[good])) * _MAD_TO_SIGMA
        if not np.isfinite(global_scale) or global_scale <= 0:
            global_scale = 1.0
        scale = np.where(np.isfinite(scale) & (scale > 0), scale, global_scale)
        z = (v - trend) / scale

        new_weight = np.abs(z) <= _REFINE_Z
        if np.array_equal(new_weight, weight):
            break
        weight = new_weight

    return z
