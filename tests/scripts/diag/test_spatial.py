import os
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", "scripts"))

from diag.spatial import (
    assign_from_grid,
    benjamini_hochberg,
    cluster_hdbscan,
    getis_ord_gi_star,
    grid_reduce,
)


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


def test_grid_reduce_every_point_gets_a_valid_cell():
    rng = np.random.default_rng(2)
    n = 5000
    x = rng.uniform(0, 100, n)
    y = rng.uniform(0, 100, n)
    v = rng.normal(size=n)
    xr, yr, vr, cell_id = grid_reduce(x, y, v, target_n=500)
    assert xr.shape == yr.shape == vr.shape
    assert cell_id.shape == (n,)
    assert cell_id.min() >= 0
    assert cell_id.max() < xr.size
    # target_n is a target, not an exact count (only occupied cells are kept), but the
    # reduction should be in the right ballpark and never expand the point count.
    assert 0 < xr.size <= n


def test_grid_reduce_cell_representative_is_the_mean_of_its_points():
    # Two points sharing one cell (grid coarse enough): the representative must be their mean.
    x = np.array([0.0, 0.0, 10.0])
    y = np.array([0.0, 0.0, 10.0])
    v = np.array([2.0, 4.0, 100.0])
    xr, yr, vr, cell_id = grid_reduce(x, y, v, target_n=2)
    assert cell_id[0] == cell_id[1]
    assert cell_id[2] != cell_id[0]
    i = cell_id[0]
    assert vr[i] == 3.0  # mean of 2.0 and 4.0


def test_cluster_hdbscan_separates_two_well_separated_blobs():
    rng = np.random.default_rng(3)
    blob_a = rng.normal(loc=(0, 0), scale=0.5, size=(200, 2))
    blob_b = rng.normal(loc=(50, 50), scale=0.5, size=(200, 2))
    xy = np.vstack([blob_a, blob_b])
    v = rng.normal(size=400)
    labels, glosh = cluster_hdbscan(xy[:, 0], xy[:, 1], v, min_cluster_size=10)
    assert labels.shape == (400,)
    assert glosh.shape == (400,)
    # at least two distinct non-noise clusters found
    assert len(set(labels[labels >= 0].tolist())) >= 2
    # the two blobs must not share a cluster label
    labels_a = set(labels[:200][labels[:200] >= 0].tolist())
    labels_b = set(labels[200:][labels[200:] >= 0].tolist())
    assert labels_a.isdisjoint(labels_b)
    assert np.all(glosh >= 0.0) and np.all(glosh <= 1.0)


def test_assign_from_grid_broadcasts_by_cell():
    cell_id = np.array([0, 0, 1, 2])
    labels_reduced = np.array([5.0, -1.0, 7.0])
    glosh_reduced = np.array([0.1, 0.9, 0.3])
    cluster_id, glosh = assign_from_grid(cell_id, labels_reduced, glosh_reduced)
    np.testing.assert_array_equal(cluster_id, [5.0, 5.0, -1.0, 7.0])
    np.testing.assert_array_equal(glosh, [0.1, 0.1, 0.9, 0.3])
