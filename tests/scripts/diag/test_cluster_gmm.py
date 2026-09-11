"""cluster_gmm: unsupervised Gaussian-mixture segmentation over (x, y, v), the counterpart
to grow_segmentation that needs no painted seeds.

Unlike cluster_hdbscan, GMM assigns every point to a component -- there is no noise class
-- and it hands back a genuine per-point confidence (the responsibility of the assigned
component), which is exactly what makes it worth having alongside HDBSCAN.
"""

import os
import sys

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", "scripts"))

from diag.spatial import cluster_gmm


def test_shapes_and_ranges():
    rng = np.random.default_rng(0)
    n = 300
    x, y, v = rng.normal(size=n), rng.normal(size=n), rng.normal(size=n)
    labels, prob = cluster_gmm(x, y, v, n_components=3, random_state=0)
    assert labels.shape == (n,)
    assert prob.shape == (n,)
    assert set(np.unique(labels)) <= {0.0, 1.0, 2.0}
    assert np.all(prob >= 0.0) and np.all(prob <= 1.0 + 1e-9)


def test_separates_two_well_separated_blobs():
    rng = np.random.default_rng(3)
    blob_a = rng.normal(loc=(0, 0), scale=0.5, size=(200, 2))
    blob_b = rng.normal(loc=(50, 50), scale=0.5, size=(200, 2))
    xy = np.vstack([blob_a, blob_b])
    v = rng.normal(size=400)
    labels, prob = cluster_gmm(xy[:, 0], xy[:, 1], v, n_components=2, random_state=0)
    labels_a = set(labels[:200].tolist())
    labels_b = set(labels[200:].tolist())
    assert labels_a.isdisjoint(labels_b)
    # well-separated blobs should be assigned with high confidence
    assert np.median(prob) > 0.9


def test_every_point_gets_a_label_no_noise_class():
    # The whole point of offering GMM alongside HDBSCAN: nothing is ever -1.
    rng = np.random.default_rng(1)
    n = 150
    x, y, v = rng.uniform(-10, 10, n), rng.uniform(-10, 10, n), rng.normal(size=n)
    labels, _ = cluster_gmm(x, y, v, n_components=4, random_state=0)
    assert np.all(labels >= 0)


def test_deterministic_given_the_same_random_state():
    rng = np.random.default_rng(2)
    n = 200
    x, y, v = rng.normal(size=n), rng.normal(size=n), rng.normal(size=n)
    l1, p1 = cluster_gmm(x, y, v, n_components=3, random_state=7)
    l2, p2 = cluster_gmm(x, y, v, n_components=3, random_state=7)
    np.testing.assert_array_equal(l1, l2)
    np.testing.assert_array_equal(p1, p2)


def test_attr_weight_changes_which_axis_dominates_the_partition():
    # With attr_weight ~0, GMM effectively partitions on (x, y) alone -- v is drowned out.
    # With attr_weight large, a strong v-based split should override weak spatial structure.
    rng = np.random.default_rng(4)
    n = 400
    x = rng.uniform(-1, 1, n)  # narrow spatial spread: little spatial structure to find
    y = rng.uniform(-1, 1, n)
    v = np.where(x + y > 0, 10.0, -10.0) + rng.normal(0, 0.1, n)  # strong v-based split

    labels_lo, _ = cluster_gmm(
        x, y, v, n_components=2, attr_weight=1e-6, random_state=0
    )
    labels_hi, _ = cluster_gmm(
        x, y, v, n_components=2, attr_weight=50.0, random_state=0
    )

    true_split = v > 0

    # Rebuild a boolean partition from each labelling and compare agreement with the true
    # v-based split (label identity is arbitrary, so check both orientations).
    def agreement(labels):
        a = labels == labels[0]
        return max((a == true_split).mean(), (a != true_split).mean())

    assert agreement(labels_hi) > agreement(labels_lo)


def test_covariance_type_is_accepted():
    rng = np.random.default_rng(5)
    n = 100
    x, y, v = rng.normal(size=n), rng.normal(size=n), rng.normal(size=n)
    for cov in ("full", "tied", "diag", "spherical"):
        labels, prob = cluster_gmm(
            x, y, v, n_components=2, covariance_type=cov, random_state=0
        )
        assert labels.shape == (n,)
        assert np.isfinite(prob).all()


def test_n_components_larger_than_point_count_degrades_rather_than_raising():
    x = np.array([0.0, 1.0, 2.0])
    y = np.array([0.0, 1.0, 0.0])
    v = np.array([1.0, 2.0, 3.0])
    labels, prob = cluster_gmm(x, y, v, n_components=10, random_state=0)
    assert labels.shape == (3,)
    assert np.isfinite(prob).all()
