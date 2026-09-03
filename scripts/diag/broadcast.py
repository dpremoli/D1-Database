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
    """np.interp(revs_full, rev_grid, value_grid).

    rev_grid must be strictly ascending (the angular grid is). Points of revs_full outside
    rev_grid clamp to the endpoints. A NaN in value_grid propagates to every revs_full point
    whose interval touches it.
    """
    rev_grid = np.asarray(rev_grid, dtype=np.float64)
    value_grid = np.asarray(value_grid, dtype=np.float64)
    revs_full = np.asarray(revs_full, dtype=np.float64)
    # np.interp returns silent garbage for a non-monotone xp -- and _truncate slices rev_grid,
    # so guard rather than trust the comment (cf. the samples_per_rev bug in the recipe engine).
    if rev_grid.size > 1 and not np.all(np.diff(rev_grid) > 0):
        raise ValueError("rev_grid must be strictly ascending")
    return np.interp(revs_full, rev_grid, value_grid)
