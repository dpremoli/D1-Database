"""Unit tests for the D1GR reader used by the grid-octree handler."""

import struct

import force_orchestrator as fo
import numpy as np


def _write_d1gr(path, x, y, fx, fy, fz, fidelity, arm_ratio, cell_mm):
    n = len(x)
    with open(path, "wb") as f:
        f.write(struct.pack("<II", 0x44314752, n))
        f.write(struct.pack("<fff", fidelity, arm_ratio, cell_mm))
        for arr in (x, y, fx, fy, fz):
            f.write(np.asarray(arr, dtype="<f4").tobytes())


def test_read_grid_bin_roundtrip(tmp_path):
    p = tmp_path / "grid.bin"
    x = [0.0, 1.0, 2.0]
    y = [3.0, 4.0, 5.0]
    fx = [10.0, 11.0, 12.0]
    fy = [1.0, 2.0, 3.0]
    fz = [20.0, 21.0, 22.0]
    _write_d1gr(p, x, y, fx, fy, fz, 0.97, 4.2, 0.031)
    n, fid, ratio, cell, rx, ry, rfx, rfy, rfz = fo._read_grid_bin(str(p))
    assert n == 3
    assert abs(fid - 0.97) < 1e-6
    assert abs(ratio - 4.2) < 1e-6
    assert abs(cell - 0.031) < 1e-6
    assert np.allclose(rx, x) and np.allclose(rfz, fz)


def test_read_grid_bin_nan_fidelity(tmp_path):
    p = tmp_path / "grid.bin"
    _write_d1gr(p, [0.0], [0.0], [1.0], [1.0], [1.0], float("nan"), float("nan"), 0.5)
    n, fid, ratio, cell, *_ = fo._read_grid_bin(str(p))
    assert n == 1 and fid is None and ratio is None and abs(cell - 0.5) < 1e-6
