"""Cluster boundaries must follow the data, not the reduction grid.

`_op_hdbscan` clusters a grid-reduced point set and then has to get those labels back onto
every full-resolution point. `assign_from_grid` did that by giving each point its own cell's
label, which quantizes every boundary to one cell. Because `grid_reduce` sizes its grid for a
target CELL COUNT (~141x141 at the default grid_target=20000) rather than a physical cell
size, that quantization is the same fraction of the view at every zoom level -- the analyst's
"very blocky segments", unfixable by any parameter.

`assign_by_neighbours` replaces the broadcast with an inverse-distance-weighted vote over the
k nearest reduced centroids, so a boundary can fall anywhere between them.
"""

from __future__ import annotations

import numpy as np
import pytest
from diag.spatial import assign_by_neighbours, assign_from_grid, grid_reduce


def test_a_boundary_between_two_centroids_falls_between_them_not_on_a_cell_edge():
    # Two reduced centroids either side of x = 0, labelled differently. Points sampled
    # densely across the gap must switch label near the midpoint, at a resolution finer than
    # the centroid spacing -- which is exactly what the grid broadcast could not do.
    xr = np.array([-1.0, 1.0])
    yr = np.array([0.0, 0.0])
    labels = np.array([0.0, 1.0])
    glosh = np.array([0.0, 0.0])

    x = np.linspace(-1.0, 1.0, 201)
    y = np.zeros_like(x)

    out, _ = assign_by_neighbours(x, y, xr, yr, labels, glosh, k=2)

    # Everything left of the midpoint is class 0, everything right is class 1.
    assert np.all(out[x < -0.02] == 0.0)
    assert np.all(out[x > 0.02] == 1.0)
    # And the crossing is a single transition, not a staircase.
    transitions = int(np.count_nonzero(np.diff(out) != 0))
    assert transitions == 1


def test_noise_is_a_real_label_so_noise_regions_stay_noise():
    # -1 must win a vote it deserves. If it were treated as "no opinion", every noise point
    # adjacent to a cluster would be absorbed into it and the noise region would vanish.
    xr = np.array([0.0, 0.1, 0.2, 5.0])
    yr = np.zeros(4)
    labels = np.array([-1.0, -1.0, -1.0, 3.0])
    glosh = np.zeros(4)

    out, _ = assign_by_neighbours(
        np.array([0.1]), np.array([0.0]), xr, yr, labels, glosh, k=3
    )
    assert out[0] == -1.0


def test_a_point_coincident_with_a_centroid_takes_that_centroid_label_exactly():
    # Inverse-distance weighting divides by zero at distance zero; the implementation must
    # give the coincident centroid all the weight rather than emitting nan.
    xr = np.array([0.0, 1.0])
    yr = np.array([0.0, 0.0])
    labels = np.array([7.0, 2.0])
    glosh = np.array([0.25, 0.75])

    out, gl = assign_by_neighbours(
        np.array([0.0]), np.array([0.0]), xr, yr, labels, glosh, k=2
    )
    assert out[0] == 7.0
    assert gl[0] == pytest.approx(0.25)
    assert np.isfinite(gl).all()


def test_a_point_coincident_with_two_differently_labelled_centroids_takes_the_nearest_returned():
    # grid_reduce can round two nearby clusters' centroids to the same coords with different
    # labels. Splitting the vote evenly between them would let argmax break the tie on label
    # id (array order), not the data. The point must take ONE definite label (the first the
    # kNN query returns), and its glosh comes from that same centroid, not a blend.
    xr = np.array([0.0, 0.0, 5.0])
    yr = np.array([0.0, 0.0, 0.0])
    labels = np.array([3.0, 8.0, 1.0])
    glosh = np.array([0.1, 0.9, 0.0])

    out, gl = assign_by_neighbours(
        np.array([0.0]), np.array([0.0]), xr, yr, labels, glosh, k=3
    )
    assert out[0] in (3.0, 8.0)  # a real coincident label, not label 1
    assert gl[0] in (
        pytest.approx(0.1),
        pytest.approx(0.9),
    )  # that centroid's glosh, not ~0.5
    assert np.isfinite(gl).all()


def test_many_labels_do_not_allocate_a_full_scores_matrix():
    # Regression for the /viewport MemoryError: the assignment used to build an
    # (n_points, n_labels) float64 matrix. With many labels and many points that is gigabytes.
    # This exercises a wide label set over a non-trivial point count and just checks it
    # completes with a sane result -- the streaming argmax keeps peak memory O(n_points).
    rng = np.random.default_rng(3)
    n_labels = 300
    xr = rng.uniform(-10, 10, n_labels)
    yr = rng.uniform(-10, 10, n_labels)
    labels = np.arange(n_labels, dtype=np.float64)
    glosh = rng.uniform(0, 1, n_labels)

    x = rng.uniform(-10, 10, 50_000)
    y = rng.uniform(-10, 10, 50_000)
    out, gl = assign_by_neighbours(x, y, xr, yr, labels, glosh, k=4)
    assert out.shape == x.shape
    assert set(np.unique(out)).issubset(set(labels))
    assert np.isfinite(gl).all()


def test_k_larger_than_the_centroid_count_degrades_instead_of_raising():
    xr = np.array([0.0, 1.0])
    yr = np.array([0.0, 0.0])
    labels = np.array([0.0, 1.0])
    glosh = np.zeros(2)

    out, gl = assign_by_neighbours(
        np.array([0.4]), np.array([0.0]), xr, yr, labels, glosh, k=50
    )
    assert out[0] in (0.0, 1.0)
    assert np.isfinite(gl).all()


def test_a_single_centroid_labels_everything_as_itself():
    out, gl = assign_by_neighbours(
        np.array([0.0, 9.0]),
        np.array([0.0, 9.0]),
        np.array([1.0]),
        np.array([1.0]),
        np.array([4.0]),
        np.array([0.5]),
        k=4,
    )
    assert out.tolist() == [4.0, 4.0]
    assert gl.tolist() == pytest.approx([0.5, 0.5])


def test_glosh_is_interpolated_rather_than_stepped():
    # glosh is a continuous outlier score, so a point between a 0.0 centroid and a 1.0 one
    # should read as intermediate -- the grid broadcast made it piecewise-constant.
    xr = np.array([-1.0, 1.0])
    yr = np.array([0.0, 0.0])
    labels = np.array([0.0, 1.0])
    glosh = np.array([0.0, 1.0])

    _, gl = assign_by_neighbours(
        np.array([0.0]), np.array([0.0]), xr, yr, labels, glosh, k=2
    )
    assert 0.0 < gl[0] < 1.0


def test_it_disagrees_with_the_grid_broadcast_only_near_boundaries():
    # The whole point: same clusters, better edges. Deep inside a cluster the two agree; the
    # differences are confined to points near a label change.
    rng = np.random.default_rng(0)
    x = rng.uniform(-5, 5, 4000)
    y = rng.uniform(-5, 5, 4000)
    v = np.where(x < 0, -1.0, 1.0) + rng.normal(0, 0.05, 4000)

    xr, yr, vr, cell_id = grid_reduce(x, y, v, target_n=64)
    labels = np.where(vr < 0, 0.0, 1.0)
    glosh = np.zeros_like(labels)

    grid_out, _ = assign_from_grid(cell_id, labels, glosh)
    knn_out, _ = assign_by_neighbours(x, y, xr, yr, labels, glosh, k=4)

    # Same label set, and agreement almost everywhere...
    assert set(np.unique(knn_out)) == set(np.unique(grid_out))
    assert (knn_out == grid_out).mean() > 0.9
    # ...but the points they disagree about are the ones near the true x = 0 boundary.
    disagree = knn_out != grid_out
    assert disagree.any()
    assert np.abs(x[disagree]).mean() < np.abs(x).mean()


# --- pipeline level ---------------------------------------------------------------------
#
# The golden fixtures used to be the only pin on cluster_id. They were recaptured at v9
# (see regenerate_goldens.py), so from here on they can only prove the pipeline still
# reproduces ITSELF -- they cannot catch a future regression back to grid-quantized
# boundaries. These cases assert the properties the change actually claims, against the same
# synthetic cut, and survive any later recapture.

from conftest import cache_of, synthetic_cut  # noqa: E402
from diag.pipeline import analyse  # noqa: E402
from diag.spatial import assign_from_grid as _assign_from_grid  # noqa: E402


def _standard_cut():
    t, fx, fy, fz, rpm, revs, x, y, fs, hit = synthetic_cut()
    return cache_of(t, fx, fy, fz, rpm, revs, fs), x, y, hit


def test_the_pipeline_still_finds_the_implanted_anomaly_as_its_own_class():
    # The whole point of the clustering: the implanted 30 N step at revolution 25 must not be
    # swallowed into the bulk class. A boundary change that lost it would be a real regression.
    cache, x, y, hit = _standard_cut()
    cols, _ = analyse(cache, x, y, samples_per_rev=256)
    cluster_id = cols["cluster_id"]

    bulk = np.bincount((cluster_id[cluster_id >= 0]).astype(int)).argmax()
    # Points at the anomaly are not simply the bulk class.
    anomaly_labels = (
        cluster_id[: hit.size][hit[: cluster_id.size]] if hit.size else np.array([])
    )
    assert anomaly_labels.size > 0
    assert not np.all(anomaly_labels == bulk)


def test_cluster_boundaries_are_not_quantized_to_the_reduction_grid():
    # The regression gate for the blockiness. Reproduce the op's own reduction, then compare
    # the neighbour vote against the old per-cell broadcast: they must agree in the interior
    # and differ only near boundaries. If someone reinstates assign_from_grid in the op, the
    # two become identical and this fails.
    from diag.spatial import assign_by_neighbours as _abn
    from diag.spatial import cluster_hdbscan, grid_reduce

    cache, x, y, _hit = _standard_cut()
    cols, _ = analyse(cache, x, y, samples_per_rev=256)

    z = cols["resid_z"].astype(np.float64)
    fin = np.isfinite(z)
    gx = cols["x"][fin].astype(np.float64)
    gy = cols["y"][fin].astype(np.float64)
    xr, yr, vr, cell_id = grid_reduce(gx, gy, z[fin], target_n=20_000)
    labels, gl = cluster_hdbscan(xr, yr, vr, min_cluster_size=10)

    grid_out, _ = _assign_from_grid(cell_id, labels, gl)
    knn_out, _ = _abn(gx, gy, xr, yr, labels, gl)

    # The op ships the neighbour vote, not the broadcast.
    np.testing.assert_array_equal(cols["cluster_id"][fin].astype(np.float64), knn_out)
    # Same clusters found...
    assert set(np.unique(knn_out)) == set(np.unique(grid_out))
    # ...mostly the same assignment...
    assert (knn_out == grid_out).mean() > 0.95
    # ...but genuinely different, which is the fix.
    assert (knn_out != grid_out).any()


def test_glosh_is_no_longer_piecewise_constant_across_the_cut():
    # Under the grid broadcast every point in a cell shared one glosh value, so the column
    # took only as many distinct values as there were occupied cells. The weighted mean makes
    # it continuous -- far more distinct values than clusters.
    cache, x, y, _hit = _standard_cut()
    cols, _ = analyse(cache, x, y, samples_per_rev=256)
    glosh = cols["glosh"]
    assert np.unique(glosh).size > 100
    assert np.isfinite(glosh).all()
