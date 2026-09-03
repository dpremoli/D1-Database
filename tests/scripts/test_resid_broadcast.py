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
