"""grid_interpolate: fill a value at every point's own location from a regularised grid, and
an honest per-point confidence in [0, 1] for how much of that fill is real vs invented.

The registry constraint that shapes this: every derived step must preserve `n` (see
registry.py::resolve_inputs -- an angular-domain step's (x, y) length is fixed after
angular_resample), so griddify cannot emit a denser or sparser cloud. It regularises `v`
onto a grid at `resolution_mm` pitch and samples that grid back at each ORIGINAL point's own
(x, y) -- which is why `grid_support` cannot be "distance from a point to itself" (always
zero, since every point IS one of the real samples): it is instead each point's distance to
its nearest OTHER real sample, i.e. local point density relative to `max_fill_mm`. Dense
regions (the tight radial spiral pitch) read near-1; sparse regions (wide angular gaps at
large radius) read lower.
"""
import os
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", "scripts"))

from diag.interpolate import grid_interpolate


def _grid_cloud(nx=40, ny=40, noise=0.0, rng=None):
    """A dense, evenly-spaced point cloud -- support should read near 1 everywhere."""
    rng = rng or np.random.default_rng(0)
    xs, ys = np.meshgrid(np.linspace(0, 10, nx), np.linspace(0, 10, ny))
    x, y = xs.ravel(), ys.ravel()
    v = np.sin(x) + np.cos(y)
    if noise:
        v = v + rng.normal(0, noise, v.size)
    return x, y, v


def test_shapes_and_dtypes():
    x, y, v = _grid_cloud()
    fill, support = grid_interpolate(x, y, v, resolution_mm=0.5, method="linear", max_fill_mm=1.0)
    assert fill.shape == v.shape
    assert support.shape == v.shape
    assert fill.dtype == np.float64
    assert support.dtype == np.float64


def test_support_is_bounded_zero_to_one():
    x, y, v = _grid_cloud()
    _, support = grid_interpolate(x, y, v, resolution_mm=0.5, method="linear", max_fill_mm=1.0)
    finite = support[np.isfinite(support)]
    assert finite.size
    assert finite.min() >= 0.0
    assert finite.max() <= 1.0


def test_dense_regular_cloud_reads_near_full_support():
    # Point spacing here is 10/59 ~= 0.169; support = 1 - 0.169/2.0 ~= 0.915.
    x, y, v = _grid_cloud(nx=60, ny=60)
    _, support = grid_interpolate(x, y, v, resolution_mm=0.25, method="linear", max_fill_mm=2.0)
    assert np.nanmean(support) > 0.9


def test_a_sparse_region_reads_lower_support_than_a_dense_one():
    rng = np.random.default_rng(2)
    dense = rng.uniform(0, 5, (400, 2))       # tight cluster, small spacing
    sparse = rng.uniform(20, 60, (400, 2))    # spread over a much wider area
    x = np.concatenate([dense[:, 0], sparse[:, 0]])
    y = np.concatenate([dense[:, 1], sparse[:, 1]])
    v = rng.normal(size=x.size)
    _, support = grid_interpolate(x, y, v, resolution_mm=0.5, method="linear", max_fill_mm=1.0)
    assert support[:400].mean() > support[400:].mean()


def test_a_point_far_beyond_max_fill_mm_from_any_neighbour_reads_zero_support():
    x = np.array([0.0, 0.0, 0.0, 100.0])
    y = np.array([0.0, 1.0, 2.0, 100.0])
    v = np.array([1.0, 2.0, 3.0, 4.0])
    _, support = grid_interpolate(x, y, v, resolution_mm=0.5, method="nearest", max_fill_mm=1.0)
    assert support[-1] == pytest.approx(0.0)


def test_fill_recovers_a_smooth_field_reasonably_well():
    x, y, v = _grid_cloud(nx=30, ny=30)
    fill, _ = grid_interpolate(x, y, v, resolution_mm=0.5, method="linear", max_fill_mm=2.0)
    finite = np.isfinite(fill)
    assert finite.sum() > v.size * 0.8
    err = np.abs(fill[finite] - v[finite])
    assert np.nanmedian(err) < 0.5


def test_nan_input_stays_nan_in_both_outputs():
    x, y, v = _grid_cloud()
    v = v.copy()
    v[::7] = np.nan
    fill, support = grid_interpolate(x, y, v, resolution_mm=0.5, method="linear", max_fill_mm=1.0)
    assert np.all(np.isnan(fill[::7]))
    assert np.all(np.isnan(support[::7]))
    assert not np.all(np.isnan(fill))


def test_too_few_points_passes_the_value_through_unchanged_with_full_support():
    x = np.array([0.0, 1.0, 2.0])
    y = np.array([0.0, 1.0, 0.5])
    v = np.array([10.0, 20.0, 30.0])
    fill, support = grid_interpolate(x, y, v, resolution_mm=0.5, method="linear", max_fill_mm=1.0)
    np.testing.assert_array_equal(fill, v)
    np.testing.assert_array_equal(support, np.ones(3))


def test_nearest_method_never_leaves_a_finite_input_point_as_nan():
    x, y, v = _grid_cloud(nx=15, ny=15)
    fill, _ = grid_interpolate(x, y, v, resolution_mm=1.0, method="nearest", max_fill_mm=3.0)
    assert np.all(np.isfinite(fill))


def test_resolution_mm_coarsening_averages_out_noise_on_a_smooth_field():
    # A LINEAR true field, so a coarser grid gains nothing but noise-averaging and loses
    # nothing to curvature bias -- sin(x)+cos(y) over this domain has real curvature at a
    # 2mm pitch (wavelength ~6.28), which biases a coarse grid enough to mask the benefit.
    rng = np.random.default_rng(4)
    nx = ny = 50
    xs, ys = np.meshgrid(np.linspace(0, 10, nx), np.linspace(0, 10, ny))
    x, y = xs.ravel(), ys.ravel()
    true = 0.4 * x + 0.3 * y
    v = true + rng.normal(0, 1.0, x.size)

    fine, _ = grid_interpolate(x, y, v, resolution_mm=0.1, method="linear", max_fill_mm=2.0)
    coarse, _ = grid_interpolate(x, y, v, resolution_mm=2.0, method="linear", max_fill_mm=2.0)
    fin_f, fin_c = np.isfinite(fine), np.isfinite(coarse)
    err_fine = np.nanmean(np.abs(fine[fin_f] - true[fin_f]))
    err_coarse = np.nanmean(np.abs(coarse[fin_c] - true[fin_c]))
    assert err_coarse < err_fine


def test_a_degenerate_axis_does_not_crash_the_interpolator():
    """Every finite sample shares one x (a straight-line cut, or a razor-thin radial mask):
    np.linspace(xlo, xlo, n) would be a duplicate-valued axis and RegularGridInterpolator
    rejects it. Must degrade gracefully, not raise."""
    x = np.full(8, 5.0)
    y = np.linspace(0.0, 4.0, 8)
    v = np.linspace(10.0, 24.0, 8)
    for method in ("linear", "nearest"):
        fill, support = grid_interpolate(x, y, v, resolution_mm=0.5, method=method, max_fill_mm=2.0)
        assert fill.shape == v.shape
        assert np.all(np.isfinite(fill))
        assert np.all((support >= 0.0) & (support <= 1.0))

    # And the transposed case (degenerate y).
    fill2, _ = grid_interpolate(y, x, v, resolution_mm=0.5, method="linear", max_fill_mm=2.0)
    assert np.all(np.isfinite(fill2))
