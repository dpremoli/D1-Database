import os
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "scripts"))

from diag.broadcast import broadcast_to_spiral


def test_interpolates_between_phase_bins():
    grid = np.array([0.0, 1.0, 2.0, 3.0])
    vals = np.array([0.0, 10.0, 20.0, 30.0])
    full = np.array([0.0, 0.5, 1.0, 2.5, 3.0])
    out = broadcast_to_spiral(grid, vals, full)
    np.testing.assert_allclose(out, [0.0, 5.0, 10.0, 25.0, 30.0])


def test_a_point_on_a_bin_centre_equals_that_bin():
    grid = np.arange(10.0)
    vals = np.sin(grid)
    out = broadcast_to_spiral(grid, vals, grid.copy())
    np.testing.assert_array_equal(out, vals)


def test_clamps_outside_the_grid():
    grid = np.array([1.0, 2.0, 3.0])
    vals = np.array([10.0, 20.0, 30.0])
    out = broadcast_to_spiral(grid, vals, np.array([0.0, 5.0]))
    np.testing.assert_array_equal(out, [10.0, 30.0])  # np.interp clamps to endpoints


def test_nan_in_the_grid_propagates_locally():
    grid = np.array([0.0, 1.0, 2.0])
    vals = np.array([0.0, np.nan, 4.0])
    out = broadcast_to_spiral(grid, vals, np.array([0.5, 1.5]))
    assert np.all(np.isnan(out))  # both interpolate across the NaN bin


def test_rejects_a_non_monotone_grid():
    grid = np.array([0.0, 2.0, 1.0, 3.0])
    vals = np.array([0.0, 10.0, 20.0, 30.0])
    with pytest.raises(ValueError):
        broadcast_to_spiral(grid, vals, np.array([0.5, 1.5]))


def test_fill_edges_nan_marks_points_outside_the_grid():
    grid = np.array([1.0, 2.0, 3.0])
    vals = np.array([10.0, 20.0, 30.0])
    out = broadcast_to_spiral(grid, vals, np.array([0.0, 2.0, 5.0]), fill_edges="nan")
    assert np.isnan(out[0])  # before the grid
    assert out[1] == 20.0  # inside
    assert np.isnan(out[2])  # after the grid (the TSA-dropped partial revolution)


def test_fill_edges_rejects_an_unknown_mode():
    with pytest.raises(ValueError):
        broadcast_to_spiral(
            np.arange(3.0), np.arange(3.0), np.arange(3.0), fill_edges="hold"
        )


def test_float32_angular_grid_at_high_rev_collapses_but_float64_reconstruction_does_not():
    """Regression for force_orchestrator's Phase G call: a long/fast cut's angular grid
    (r0 + arange(n)/spr), once run_recipe has cast it to float32, has consecutive values that
    collapse to equal float32 numbers at high rev magnitude -- the float32 ULP there reaches
    the 1/spr grid spacing. Re-widening that with .astype(float64) does NOT recover the bits,
    so broadcast_to_spiral's strict-ascending guard raises and the whole bake fails.
    Reconstructing the grid in float64 from (r0, n, spr) -- what force_orchestrator now does --
    keeps it strictly ascending.
    """
    spr = 256
    r0 = 3.5
    # Past rev ~65536 the float32 spacing exceeds 1/spr (2^-8), so grid points must collapse;
    # 100k revs (~28 min at 3500 rpm, or ~10 min at 10000 rpm) is a realistic long cut.
    n = 100_000 * spr
    grid_f64 = r0 + np.arange(n, dtype=np.float64) / spr
    grid_f32_rewidened = grid_f64.astype(np.float32).astype(np.float64)

    # The float32 round-trip really does collapse consecutive values here.
    assert np.any(np.diff(grid_f32_rewidened) <= 0)

    vals = np.zeros(n)
    revs_full = np.linspace(r0, grid_f64[-1], n // 4)
    with pytest.raises(ValueError, match="strictly ascending"):
        broadcast_to_spiral(grid_f32_rewidened, vals, revs_full)

    # The float64 reconstruction is fine.
    out = broadcast_to_spiral(grid_f64, vals, revs_full)
    assert out.shape == revs_full.shape
