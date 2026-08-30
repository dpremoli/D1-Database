import os
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", "scripts"))

from diag.frames import frame_transform


def test_zero_mount_angle_is_identity():
    fx = np.array([1.0, 2.0, 3.0])
    fy = np.array([4.0, 5.0, 6.0])
    fz = np.array([7.0, 8.0, 9.0])
    fc, ff, fp = frame_transform(fx, fy, fz, mount_deg=0.0)
    np.testing.assert_allclose(fc, fx)
    np.testing.assert_allclose(ff, fy)
    np.testing.assert_allclose(fp, fz)


def test_ninety_degrees_swaps_axes():
    fx = np.array([1.0, 0.0])
    fy = np.array([0.0, 1.0])
    fz = np.zeros(2)
    fc, ff, fp = frame_transform(fx, fy, fz, mount_deg=90.0)
    # Fc =  fx cos + fy sin ;  Ff = -fx sin + fy cos
    np.testing.assert_allclose(fc, [0.0, 1.0], atol=1e-12)
    np.testing.assert_allclose(ff, [-1.0, 0.0], atol=1e-12)
    np.testing.assert_allclose(fp, fz)


def test_rotation_preserves_planar_magnitude():
    rng = np.random.default_rng(1)
    fx, fy = rng.normal(size=256), rng.normal(size=256)
    fz = np.zeros(256)
    fc, ff, _ = frame_transform(fx, fy, fz, mount_deg=37.5)
    np.testing.assert_allclose(fc**2 + ff**2, fx**2 + fy**2, rtol=1e-12)


def test_milling_angle_rotates_per_sample():
    fx = np.array([1.0, 1.0])
    fy = np.array([0.0, 0.0])
    fz = np.zeros(2)
    ang = np.array([0.0, np.pi / 2])
    fc, ff, _ = frame_transform(fx, fy, fz, mount_deg=0.0, angle_rad=ang)
    np.testing.assert_allclose(fc, [1.0, 0.0], atol=1e-12)
    np.testing.assert_allclose(ff, [0.0, -1.0], atol=1e-12)


def test_angle_length_must_match():
    with pytest.raises(ValueError, match="angle_rad"):
        frame_transform(
            np.zeros(4), np.zeros(4), np.zeros(4), 0.0, angle_rad=np.zeros(3)
        )
