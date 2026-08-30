import os
import sys

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", "scripts"))

from diag.detrend import radial_detrend


def test_pure_radial_ramp_yields_no_significant_outliers():
    # THE regression test: a clean ramp with no implanted anomaly must not light up.
    rng = np.random.default_rng(0)
    r = np.linspace(10.0, 40.0, 50_000)
    v = 100.0 - 2.0 * r + rng.normal(scale=1.0, size=r.size)
    z = radial_detrend(r, v)
    assert np.mean(np.abs(z) > 4.0) < 0.001


def test_implanted_hotspot_is_recovered():
    rng = np.random.default_rng(1)
    r = np.linspace(10.0, 40.0, 50_000)
    v = 100.0 - 2.0 * r + rng.normal(scale=1.0, size=r.size)
    v[20_000:20_200] += 25.0
    z = radial_detrend(r, v)
    assert np.median(z[20_000:20_200]) > 8.0


def test_nonlinear_trend_is_removed():
    rng = np.random.default_rng(2)
    r = np.linspace(10.0, 40.0, 50_000)
    v = 0.05 * (r - 25.0) ** 3 + rng.normal(scale=1.0, size=r.size)
    z = radial_detrend(r, v)
    assert np.mean(np.abs(z) > 4.0) < 0.001


def test_sparse_bins_do_not_produce_nan():
    r = np.concatenate([np.linspace(0.0, 1.0, 500), np.array([50.0, 50.1])])
    v = np.concatenate([np.zeros(500), np.array([1.0, 2.0])])
    z = radial_detrend(r, v)
    assert np.all(np.isfinite(z))


def test_output_length_matches_input():
    r = np.linspace(0.0, 1.0, 1000)
    assert radial_detrend(r, np.zeros(1000)).size == 1000
