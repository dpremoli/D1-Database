"""Grid interpolation: regularise a scattered value onto a grid at a chosen physical pitch,
and sample it back at each point's own location, alongside an honest per-point confidence.

The registry constraint that shapes this module: an angular-domain derived step must
preserve the point count `n` (registry.py::resolve_inputs asserts a rasterised layer's
shape matches (x, y) at the consuming step's position), so this cannot emit a denser or
sparser cloud -- only a value AT each existing point's own location. That value is the
regular grid resampled back, which behaves as a spatial low-pass filter at `resolution_mm`:
coarser than the point spacing, it averages over several real points; finer, it approaches
the identity.

Confidence (`support`) cannot be "distance from a point to itself" -- every point being
scored IS one of the real samples used to build the grid, so that distance is always zero.
It is instead each point's distance to its nearest OTHER real sample: local point density
relative to `max_fill_mm`, 1 at zero distance, falling linearly to 0 at `max_fill_mm`.
"""

from __future__ import annotations

import numpy as np
from scipy.spatial import cKDTree

# scipy.interpolate.griddata needs at least a handful of non-collinear points to triangulate;
# below this, degrade to the identity rather than let it raise on a tiny or degenerate cut.
_MIN_POINTS = 4


def grid_interpolate(
    x: np.ndarray,
    y: np.ndarray,
    v: np.ndarray,
    *,
    resolution_mm: float = 0.25,
    method: str = "linear",
    max_fill_mm: float = 1.0,
) -> tuple[np.ndarray, np.ndarray]:
    """Return (fill, support), both float64, same shape as `v`.

    `fill[i]` is `v` regularised onto a `resolution_mm`-pitch grid and read back at
    `(x[i], y[i])`. `support[i]` is in [0, 1]: how close `(x[i], y[i])` is to its nearest
    OTHER real sample, relative to `max_fill_mm`. A point whose own `v` is NaN (masked out
    upstream) stays NaN in both outputs -- it must not silently gain a value nor count as
    "real" for its neighbours' support.
    """
    x = np.asarray(x, dtype=np.float64)
    y = np.asarray(y, dtype=np.float64)
    v = np.asarray(v, dtype=np.float64)
    n = v.size
    fill = np.full(n, np.nan)
    support = np.full(n, np.nan)

    fin = np.isfinite(v) & np.isfinite(x) & np.isfinite(y)
    n_fin = int(fin.sum())
    if n_fin < _MIN_POINTS:
        # Too sparse to triangulate: nothing to interpolate against, so pass the value
        # through unchanged and call it fully supported -- there is no invented content.
        fill[fin] = v[fin]
        support[fin] = 1.0
        return fill, support

    xf, yf, vf = x[fin], y[fin], v[fin]

    # support: distance to the nearest OTHER real point. k=2 because k=1 would return the
    # point itself at distance 0, which is true for every point and therefore useless.
    tree = cKDTree(np.column_stack([xf, yf]))
    kq = min(2, xf.size)
    dist, _ = tree.query(np.column_stack([xf, yf]), k=kq)
    nn_dist = dist[:, 1] if kq > 1 else np.zeros(xf.size)
    max_fill_mm = max(float(max_fill_mm), 1e-9)  # guard a caller-supplied zero
    support[fin] = np.clip(1.0 - nn_dist / max_fill_mm, 0.0, 1.0)

    # fill: regularise onto a resolution_mm grid, then read back by nearest-cell lookup
    # (index arithmetic -- cheap, and exact since the grid is regular).
    from scipy.interpolate import griddata

    resolution_mm = max(float(resolution_mm), 1e-6)
    xlo, xhi = float(xf.min()), float(xf.max())
    ylo, yhi = float(yf.min()), float(yf.max())
    nx = max(2, int(np.ceil((xhi - xlo) / resolution_mm)) + 1)
    ny = max(2, int(np.ceil((yhi - ylo) / resolution_mm)) + 1)
    gx = np.linspace(xlo, xhi, nx)
    gy = np.linspace(ylo, yhi, ny)
    Gx, Gy = np.meshgrid(gx, gy)

    grid_vals = griddata((xf, yf), vf, (Gx, Gy), method=method)
    if method != "nearest":
        # linear (and cubic) leave NaN outside the convex hull; nearest never does, so it is
        # always a safe total fallback rather than leaving a hole grid_support cannot explain.
        nan_cells = ~np.isfinite(grid_vals)
        if nan_cells.any():
            grid_vals[nan_cells] = griddata((xf, yf), vf, (Gx, Gy), method="nearest")[nan_cells]

    col = np.clip(np.round((xf - xlo) / resolution_mm).astype(np.int64), 0, nx - 1)
    row = np.clip(np.round((yf - ylo) / resolution_mm).astype(np.int64), 0, ny - 1)
    fill[fin] = grid_vals[row, col]

    return fill, support
