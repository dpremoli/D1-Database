"""`invert`: value inversion (complement or reciprocal), NOT sign flip or deconvolution.

`source` names WHICH already-produced column to invert, chosen at recipe-edit time -- so
unlike every other step's fixed `requires`, this one is a genuinely runtime dependency the
static registry graph cannot express. `requires=()` is deliberate, not an oversight: the op
raises a clear error itself when the chosen source is not present, and the client mirrors
that in recipeProblems() (see recipeChannels.test.ts) so the doomed request is still caught
before it is sent.
"""

import os
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", "scripts"))

from diag import ops as _ops  # noqa: F401 -- registers the steps
from diag.registry import STEPS


def _cols(n=200, rng=None):
    rng = rng or np.random.default_rng(3)
    return {
        "x": rng.uniform(-30, 30, n),
        "y": rng.uniform(-30, 30, n),
        "resid_z": rng.normal(0, 2, n),
    }


def test_registered_with_the_right_contract():
    spec = STEPS["invert"]
    assert spec.produces == ("inverted",)
    assert spec.requires == ()
    assert spec.tier == "derived"
    assert spec.category == "transform"


def test_complement_reflects_around_the_finite_max():
    c = _cols()
    out, _ = STEPS["invert"].fn(c, {"source": "resid_z", "mode": "complement"}, {})
    want = np.nanmax(c["resid_z"]) - c["resid_z"]
    np.testing.assert_allclose(out["inverted"], want)


def test_complement_turns_the_max_into_zero_and_the_min_into_the_largest_value():
    c = _cols()
    out, _ = STEPS["invert"].fn(c, {"source": "resid_z", "mode": "complement"}, {})
    assert out["inverted"][np.argmax(c["resid_z"])] == pytest.approx(0.0)
    assert np.argmax(out["inverted"]) == np.argmin(c["resid_z"])


def test_reciprocal_inverts_magnitude_but_keeps_sign():
    c = _cols()
    out, _ = STEPS["invert"].fn(
        c, {"source": "resid_z", "mode": "reciprocal", "epsilon": 1e-6}, {}
    )
    want = np.copysign(1.0 / (np.abs(c["resid_z"]) + 1e-6), c["resid_z"])
    np.testing.assert_allclose(out["inverted"], want)
    assert np.array_equal(np.sign(out["inverted"]), np.sign(c["resid_z"]))


def test_reciprocal_epsilon_guards_a_zero_value():
    c = _cols(n=5)
    c["resid_z"][:] = 0.0
    out, _ = STEPS["invert"].fn(
        c, {"source": "resid_z", "mode": "reciprocal", "epsilon": 1e-3}, {}
    )
    assert np.all(np.isfinite(out["inverted"]))
    assert out["inverted"][0] == pytest.approx(1000.0)


def test_reciprocal_orders_small_magnitudes_above_large_ones():
    # The whole point: a "low is bad" channel should read as "high is bad" once inverted.
    c = {"resid_z": np.array([0.1, 1.0, 5.0])}
    out, _ = STEPS["invert"].fn(c, {"source": "resid_z", "mode": "reciprocal"}, {})
    assert out["inverted"][0] > out["inverted"][1] > out["inverted"][2]


def test_nan_in_nan_out():
    c = _cols()
    c["resid_z"][::10] = np.nan
    out, _ = STEPS["invert"].fn(c, {"source": "resid_z", "mode": "complement"}, {})
    assert np.array_equal(np.isnan(out["inverted"]), np.isnan(c["resid_z"]))


def test_default_mode_is_complement():
    c = _cols()
    out, _ = STEPS["invert"].fn(c, {"source": "resid_z"}, {})
    want = np.nanmax(c["resid_z"]) - c["resid_z"]
    np.testing.assert_allclose(out["inverted"], want)


def test_default_source_is_resid_z():
    c = _cols()
    out, _ = STEPS["invert"].fn(c, {}, {})
    want = np.nanmax(c["resid_z"]) - c["resid_z"]
    np.testing.assert_allclose(out["inverted"], want)


def test_raises_a_clear_error_when_the_source_column_is_absent():
    c = _cols()
    with pytest.raises(ValueError, match="gi_star"):
        STEPS["invert"].fn(c, {"source": "gi_star"}, {})


def test_an_all_nan_source_produces_an_all_nan_result_rather_than_crashing():
    c = _cols(n=5)
    c["resid_z"][:] = np.nan
    out, _ = STEPS["invert"].fn(c, {"source": "resid_z", "mode": "complement"}, {})
    assert np.all(np.isnan(out["inverted"]))
