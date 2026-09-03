"""Server-side rasterisation of hand-painted polygon layers.

A layer's geometry is polygons in (x, y) millimetres on the ANGULAR-RESAMPLED analysis grid
-- the coordinate space frame_transform produces and DiagScatter renders. Rasterising means
testing each analysis-grid point against those polygons to get a boolean array the recipe's
steps consume. The browser draws the polygons; this module is the only place they become
per-point booleans (Recipe Workbench spec, Component 3: "the browser computes nothing").
"""
from __future__ import annotations

import numpy as np

# {"polygons": [ [ [x, y], [x, y], ... ], ... ]} -- a list of rings, each >= 3 vertices.
LayerGeometry = dict


def validate_geometry(geometry: dict) -> None:
    """Raise ValueError unless `geometry` is {"polygons": [ring, ...]} with each ring a list
    of >= 3 [x, y] numeric vertices."""
    if not isinstance(geometry, dict) or "polygons" not in geometry:
        raise ValueError("layer geometry must be a dict with a 'polygons' key")
    polys = geometry["polygons"]
    if not isinstance(polys, list):
        raise ValueError("geometry['polygons'] must be a list of rings")
    for ring in polys:
        if not isinstance(ring, list) or len(ring) < 3:
            raise ValueError("each polygon ring needs >= 3 vertices")
        for v in ring:
            if (
                not isinstance(v, (list, tuple))
                or len(v) != 2
                or not all(isinstance(c, (int, float)) and not isinstance(c, bool) for c in v)
            ):
                raise ValueError("each vertex must be [x, y] numbers")


def _ring_contains(ring: np.ndarray, x: np.ndarray, y: np.ndarray) -> np.ndarray:
    """Vectorised even-odd ray-cast: which of (x, y) fall inside `ring` (shape (m, 2))."""
    xs, ys = ring[:, 0], ring[:, 1]
    m = len(ring)
    inside = np.zeros(x.shape, dtype=bool)
    j = m - 1
    for i in range(m):
        xi, yi, xj, yj = xs[i], ys[i], xs[j], ys[j]
        crosses = (yi > y) != (yj > y)
        with np.errstate(divide="ignore", invalid="ignore"):
            xints = (xj - xi) * (y - yi) / (yj - yi) + xi
        inside ^= crosses & (x < xints)
        j = i
    return inside


def rasterize_polygons(geometry: dict, x: np.ndarray, y: np.ndarray) -> np.ndarray:
    """Boolean array, length x.size, True where a point is inside ANY ring (union, even-odd
    fill). `x`/`y` are the angular-grid mm coordinates at the consuming step's position."""
    validate_geometry(geometry)
    x = np.asarray(x, dtype=np.float64)
    y = np.asarray(y, dtype=np.float64)
    out = np.zeros(x.shape, dtype=bool)
    for ring in geometry["polygons"]:
        out |= _ring_contains(np.asarray(ring, dtype=np.float64), x, y)
    return out
