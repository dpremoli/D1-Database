import os
import sys

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", "scripts"))

from diag import ops as _ops  # noqa: F401 -- registers the steps
from diag.registry import STEPS


def _cols(nx=25, ny=25, rng=None):
    rng = rng or np.random.default_rng(5)
    xs, ys = np.meshgrid(np.linspace(-20, 20, nx), np.linspace(-20, 20, ny))
    x, y = xs.ravel(), ys.ravel()
    resid_z = np.sin(x / 5) + rng.normal(0, 0.1, x.size)
    return {"x": x, "y": y, "resid_z": resid_z}


def test_registered_with_the_right_contract():
    spec = STEPS["griddify"]
    assert spec.produces == ("grid_fill", "grid_support")
    assert set(spec.requires) == {"x", "y", "resid_z"}
    assert spec.tier == "derived"
    assert spec.category == "interpolation"


def test_op_returns_both_columns_at_input_length():
    c = _cols()
    out, metrics = STEPS["griddify"].fn(
        c, {"resolution_mm": 1.0, "method": "linear", "max_fill_mm": 3.0}, {}
    )
    assert out["grid_fill"].shape == c["x"].shape
    assert out["grid_support"].shape == c["x"].shape
    assert 0.0 <= metrics["grid_support_mean"] <= 1.0


def test_defaults_match_the_spec():
    c = _cols()
    out, _ = STEPS["griddify"].fn(c, {}, {})
    # Just needs to run and produce finite output with the documented defaults
    # (resolution_mm=0.25, method='linear', max_fill_mm=1.0) -- no exception, no all-NaN.
    assert np.isfinite(out["grid_fill"]).any()
    assert np.isfinite(out["grid_support"]).any()


def test_nan_resid_z_stays_nan_in_both_outputs():
    c = _cols()
    c["resid_z"][:20] = np.nan
    out, _ = STEPS["griddify"].fn(c, {"resolution_mm": 1.0, "max_fill_mm": 3.0}, {})
    assert np.all(np.isnan(out["grid_fill"][:20]))
    assert np.all(np.isnan(out["grid_support"][:20]))


def test_nearest_method_is_accepted():
    c = _cols()
    out, _ = STEPS["griddify"].fn(c, {"method": "nearest", "max_fill_mm": 3.0}, {})
    assert np.isfinite(out["grid_fill"]).any()
