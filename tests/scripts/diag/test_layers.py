import os
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", "scripts"))

from diag.layers import rasterize_polygons, validate_geometry


def _square(cx, cy, half):
    return [
        [cx - half, cy - half],
        [cx + half, cy - half],
        [cx + half, cy + half],
        [cx - half, cy + half],
    ]


def test_rasterize_marks_points_inside_a_single_polygon():
    geom = {"polygons": [_square(0.0, 0.0, 1.0)]}
    x = np.array([0.0, 0.5, 2.0, -0.9])
    y = np.array([0.0, 0.5, 2.0, 0.9])
    assert rasterize_polygons(geom, x, y).tolist() == [True, True, False, True]


def test_rasterize_is_the_union_of_multiple_polygons():
    geom = {"polygons": [_square(-5.0, 0.0, 1.0), _square(5.0, 0.0, 1.0)]}
    x = np.array([-5.0, 0.0, 5.0])
    y = np.array([0.0, 0.0, 0.0])
    assert rasterize_polygons(geom, x, y).tolist() == [True, False, True]


def test_rasterize_is_resolution_independent():
    # The SAME polygon must select the SAME physical region regardless of how densely the
    # grid is sampled -- the property that justifies storing geometry over indices.
    geom = {"polygons": [_square(3.0, -2.0, 1.5)]}
    rng = np.random.default_rng(0)

    def fraction_inside(n):
        x = rng.uniform(-10, 10, n)
        y = rng.uniform(-10, 10, n)
        return rasterize_polygons(geom, x, y).mean()

    assert abs(fraction_inside(20_000) - fraction_inside(200_000)) < 0.01


def test_validate_geometry_rejects_malformed_shapes():
    for bad in [
        {},
        {"polygons": "x"},
        {"polygons": [[[0.0]]]},
        {"polygons": [[[0.0, 0.0], [1.0, 0.0]]]},  # < 3 vertices
    ]:
        with pytest.raises(ValueError):
            validate_geometry(bad)


def test_rasterize_empty_geometry_selects_nothing():
    assert rasterize_polygons({"polygons": []}, np.zeros(5), np.zeros(5)).tolist() == [False] * 5
