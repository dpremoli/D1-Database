import os
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", "scripts"))

from diag.spatial import benjamini_hochberg, getis_ord_gi_star


def test_uniform_noise_field_yields_almost_no_hotspots():
    # THE regression test: a field with no real spatial structure must not light up.
    rng = np.random.default_rng(0)
    n = 4000
    x = rng.uniform(0, 100, n)
    y = rng.uniform(0, 100, n)
    v = rng.normal(size=n)
    gi_star, p_values = getis_ord_gi_star(x, y, v, k=30)
    sig = benjamini_hochberg(p_values, alpha=0.05)
    assert sig.sum() / n < 0.02


def test_implanted_hot_cluster_is_recovered():
    rng = np.random.default_rng(1)
    n = 4000
    x = rng.uniform(0, 100, n)
    y = rng.uniform(0, 100, n)
    v = rng.normal(size=n)
    hot = (x > 40) & (x < 50) & (y > 40) & (y < 50)
    v[hot] += 6.0
    gi_star, p_values = getis_ord_gi_star(x, y, v, k=30)
    sig = benjamini_hochberg(p_values, alpha=0.05)
    # most of the implanted cluster should come back significant and positive (a hotspot,
    # not a coldspot)
    assert sig[hot].mean() > 0.7
    assert np.median(gi_star[hot]) > 0
    # the background, away from the cluster, should mostly not be flagged
    assert sig[~hot].mean() < 0.05


def test_getis_ord_requires_more_points_than_k():
    x = np.zeros(5)
    with pytest.raises(ValueError, match="at least"):
        getis_ord_gi_star(x, x, x, k=10)


def test_getis_ord_handles_zero_variance_field():
    x = np.arange(50, dtype=np.float64)
    v = np.ones(50)
    gi_star, p_values = getis_ord_gi_star(x, x, v, k=10)
    assert np.all(gi_star == 0)
    assert np.all(p_values == 1)


def test_benjamini_hochberg_flags_the_small_p_values():
    p = np.array([0.001, 0.002, 0.01, 0.5, 0.8, 0.95])
    sig = benjamini_hochberg(p, alpha=0.05)
    assert sig[:3].all()
    assert not sig[3:].any()


def test_benjamini_hochberg_all_large_p_values_flags_nothing():
    p = np.full(20, 0.9)
    sig = benjamini_hochberg(p, alpha=0.05)
    assert not sig.any()
