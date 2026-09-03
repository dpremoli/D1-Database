import os
import sys

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", "scripts"))

from diag import ops as _ops  # noqa: F401 -- registers the steps
from diag.registry import STEPS


def _cols(n=600, rng=None):
    rng = rng or np.random.default_rng(1)
    return {
        "x": rng.uniform(-30, 30, n),
        "y": rng.uniform(-30, 30, n),
        "resid_z": rng.normal(0, 1, n),
    }


def test_registered_with_the_right_contract():
    spec = STEPS["grow_segmentation"]
    assert spec.produces == ("segment_id",)
    assert spec.tier == "derived"
    assert "resid_z" in spec.requires


def test_op_segments_with_two_seed_masks():
    c = _cols()
    n = c["x"].size
    seeds = {"a": c["x"] < -15, "b": c["x"] > 15}
    out, metrics = STEPS["grow_segmentation"].fn(c, {"features": ["resid_z"]}, {"seeds": seeds})
    assert out["segment_id"].shape == (n,)
    assert set(np.unique(out["segment_id"])) <= {0.0, 1.0}
    assert metrics["segmentation_status"] == ""


def test_op_degrades_to_minus_one_without_seeds():
    c = _cols()
    out, metrics = STEPS["grow_segmentation"].fn(c, {}, {})
    assert np.all(out["segment_id"] == -1)
    assert "seed" in metrics["segmentation_status"]


def test_op_passes_masked_nan_through_as_minus_one():
    c = _cols()
    c["resid_z"][:80] = np.nan
    seeds = {"a": c["x"] < -15, "b": c["x"] > 15}
    out, _ = STEPS["grow_segmentation"].fn(c, {}, {"seeds": seeds})
    assert np.all(out["segment_id"][:80] == -1)
