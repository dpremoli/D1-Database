import os
import sys

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", "scripts"))

from diag.segmentation import grow_segmentation


def test_recovers_a_planted_high_residual_region():
    # LabelSpreading is a TOTAL partition -- every finite point gets class 0 or 1, there is
    # no background. So the clean seed must be a REPRESENTATIVE scattered sample of clean
    # material (what an analyst actually paints), not one compact far-away patch. Assert on
    # the attribute-driven property, not a "false positive rate" against an undefined negative.
    rng = np.random.default_rng(3)
    n = 4000
    x = rng.uniform(-40, 40, n)
    y = rng.uniform(-40, 40, n)
    resid = rng.normal(0, 1, n)
    planted = (x > 10) & (x < 25) & (y > -8) & (y < 8)
    resid[planted] += 6.0

    seed_defect = (x > 15) & (x < 20) & (y > -3) & (y < 3)
    seed_clean = (np.abs(resid) < 0.5) & ~planted & (rng.uniform(size=n) < 0.15)
    seg, status = grow_segmentation(
        x, y, [resid], [seed_defect, seed_clean], k=15, attr_weight=3.0
    )
    assert status == ""
    assert (seg[planted] == 0).mean() > 0.9, (seg[planted] == 0).mean()
    assert (seg[np.abs(resid) < 1.0] == 1).mean() > 0.8, (seg[np.abs(resid) < 1.0] == 1).mean()


def test_multi_class_preserves_seed_order():
    rng = np.random.default_rng(4)
    n = 3000
    x = rng.uniform(-40, 40, n)
    y = rng.uniform(-40, 40, n)
    resid = rng.normal(0, 1, n)
    a = x < -15
    b = (x > -5) & (x < 5)
    c = x > 15
    seg, status = grow_segmentation(x, y, [resid], [a, b, c])
    assert status == ""
    assert set(np.unique(seg)) <= {0.0, 1.0, 2.0}
    assert seg[a].mean() < 0.5
    assert abs(seg[b].mean() - 1) < 0.5
    assert abs(seg[c].mean() - 2) < 0.5


def test_degrades_below_two_seed_classes():
    x = np.arange(50.0)
    y = np.zeros(50)
    seg, status = grow_segmentation(x, y, [np.zeros(50)], [x > 40])
    assert status == "needs >= 2 seed classes"
    assert np.all(seg == -1)


def test_nan_feature_points_are_minus_one_and_excluded():
    rng = np.random.default_rng(5)
    n = 800
    x = rng.uniform(-10, 10, n)
    y = rng.uniform(-10, 10, n)
    resid = rng.normal(0, 1, n)
    resid[:100] = np.nan
    seg, status = grow_segmentation(x, y, [resid], [x < -5, x > 5])
    assert np.all(seg[:100] == -1)
    assert status == ""
