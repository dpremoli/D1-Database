"""Broadcast a per-revolution-phase analysis column back onto the full-resolution spiral.

The pipeline computes resid_z on the 256/rev angular grid; the Phase G full-resolution
octree and the viewport-recompute source need it per raw spiral point. Linear interpolation
in revolution-phase is the honest broadcast for a continuous residual -- nearest-neighbour
would band at the phase-bin boundaries.
"""

from __future__ import annotations

import numpy as np


def broadcast_to_spiral(
    rev_grid: np.ndarray,
    value_grid: np.ndarray,
    revs_full: np.ndarray,
    *,
    fill_edges: str = "clamp",
) -> np.ndarray:
    """np.interp(revs_full, rev_grid, value_grid).

    rev_grid must be strictly ascending (the angular grid is). A NaN in value_grid propagates
    to every revs_full point whose interval touches it.

    `fill_edges` controls revs_full points outside rev_grid's span:
      "clamp" (default) -- hold the nearest endpoint value (np.interp's own behaviour).
      "nan"             -- NaN. Use this for resid_z: TSA drops the partial last revolution,
                           so the trailing raw spiral points have no residual, and a fabricated
                           resid_z[-1] there would render as a false uniform arc at the octree
                           edge (and be included in a viewport recompute).
    """
    rev_grid = np.asarray(rev_grid, dtype=np.float64)
    value_grid = np.asarray(value_grid, dtype=np.float64)
    revs_full = np.asarray(revs_full, dtype=np.float64)
    # np.interp returns silent garbage for a non-monotone xp -- and _truncate slices rev_grid,
    # so guard rather than trust the comment (cf. the samples_per_rev bug in the recipe engine).
    if rev_grid.size > 1 and not np.all(np.diff(rev_grid) > 0):
        raise ValueError("rev_grid must be strictly ascending")
    if fill_edges == "nan":
        return np.interp(revs_full, rev_grid, value_grid, left=np.nan, right=np.nan)
    if fill_edges != "clamp":
        raise ValueError(f"fill_edges must be 'clamp' or 'nan', got {fill_edges!r}")
    return np.interp(revs_full, rev_grid, value_grid)
