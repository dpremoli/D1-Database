import os
import sys

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", "scripts"))

from diag import ops as _ops  # noqa: F401 -- registers the steps
from diag.registry import STEPS


def _cols(n=600, rng=None):
    rng = rng or np.random.default_rng(6)
    return {
        "x": rng.uniform(-30, 30, n),
        "y": rng.uniform(-30, 30, n),
        "resid_z": rng.normal(0, 1, n),
    }


def test_registered_with_the_right_contract():
    spec = STEPS["gmm_segmentation"]
    assert spec.produces == ("gmm_id", "gmm_prob")
    assert set(spec.requires) == {"x", "y", "resid_z"}
    assert spec.tier == "derived"
    assert spec.category == "segmentation"


def test_op_assigns_every_finite_point_no_masking():
    c = _cols()
    out, _ = STEPS["gmm_segmentation"].fn(c, {"n_components": 3, "grid_target": 200}, {})
    assert out["gmm_id"].shape == (600,)
    assert np.all(out["gmm_id"] >= 0)
    assert np.all(out["gmm_prob"] >= 0.0) and np.all(out["gmm_prob"] <= 1.0 + 1e-9)


def test_op_passes_masked_nan_through_as_minus_one():
    c = _cols()
    c["resid_z"][:80] = np.nan
    out, _ = STEPS["gmm_segmentation"].fn(c, {"n_components": 3, "grid_target": 200}, {})
    assert np.all(out["gmm_id"][:80] == -1)
    assert np.all(out["gmm_prob"][:80] == 0.0)


def test_op_degrades_rather_than_raising_on_a_tiny_input():
    c = _cols(n=3)
    out, _ = STEPS["gmm_segmentation"].fn(c, {"n_components": 4}, {})
    assert out["gmm_id"].shape == (3,)
    assert np.all(out["gmm_id"] == -1)


def test_defaults_match_the_spec():
    c = _cols()
    out, _ = STEPS["gmm_segmentation"].fn(c, {}, {})
    # n_components defaults to 4: at most 4 distinct non-noise labels.
    labels = set(out["gmm_id"][out["gmm_id"] >= 0].tolist())
    assert len(labels) <= 4
