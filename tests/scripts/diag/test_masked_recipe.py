import os
import sys

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", "scripts"))

from conftest import cache_of, synthetic_cut
from diag.layers import rasterize_polygons
from diag.recipe import DEFAULT_RECIPE
from diag.runner import run_recipe, seed_columns


def _seed():
    t, fx, fy, fz, rpm, revs, x, y, fs, _ = synthetic_cut()
    return seed_columns(cache_of(t, fx, fy, fz, rpm, revs, fs), x, y)


def _bind_mask(polygons):
    r = {"steps": [dict(s) for s in DEFAULT_RECIPE["steps"]]}
    for s in r["steps"]:
        if s["op"] == "radial_detrend":
            s["inputs"] = {"mask": {"layer": "art", "required": False}}
    layers = {
        "art": {
            "role": "mask",
            "geometry": {"polygons": polygons},
            "value": {"mode": "exclude"},
            "version": 1,
        }
    }
    return r, layers


def _edge_square(base):
    """A square covering some but not all points, near the outer edge of the spiral."""
    x, y = base["x"], base["y"]
    i = int(np.argmax(x))
    cx, cy = float(x[i]), float(y[i])
    h = (float(x.max()) - float(x.min())) * 0.08
    return [[cx - h, cy - h], [cx + h, cy - h], [cx + h, cy + h], [cx - h, cy + h]]


def test_mask_nans_covered_points_and_leaves_the_rest_close():
    seed = _seed()
    base, _ = run_recipe(DEFAULT_RECIPE, dict(seed))
    sq = _edge_square(base)
    recipe, layers = _bind_mask([sq])
    masked, _ = run_recipe(recipe, dict(seed), layers=layers)

    covered = rasterize_polygons({"polygons": [sq]}, base["x"], base["y"])
    assert covered.any() and not covered.all()

    assert np.all(np.isnan(masked["resid_z"][covered]))
    good = ~covered & np.isfinite(masked["resid_z"])
    assert np.corrcoef(masked["resid_z"][good], base["resid_z"][good])[0, 1] > 0.98


def test_downstream_channels_are_finite_safe_under_a_mask():
    seed = _seed()
    base, _ = run_recipe(DEFAULT_RECIPE, dict(seed))
    sq = _edge_square(base)
    recipe, layers = _bind_mask([sq])
    masked, _ = run_recipe(recipe, dict(seed), layers=layers)

    covered = rasterize_polygons({"polygons": [sq]}, base["x"], base["y"])
    assert np.all(np.isnan(masked["gi_star"][covered]))
    assert np.all(masked["gi_sig"][covered] == 0)
    assert np.all(masked["cluster_id"][covered] == -1)
    assert np.all(np.isfinite(masked["gi_star"][~covered]))


def test_unmasked_recipe_is_unchanged_by_an_empty_layers_dict():
    seed = _seed()
    a, _ = run_recipe(DEFAULT_RECIPE, dict(seed))
    b, _ = run_recipe(DEFAULT_RECIPE, dict(seed), layers={})
    for k in a:
        np.testing.assert_array_equal(a[k], b[k])
