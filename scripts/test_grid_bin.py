"""Unit tests for the D1GR reader + int16 LAS round-trip used by the grid-octree handler."""
import struct
import numpy as np
import force_orchestrator as fo


def _write_d1gr(path, x, y, fx, fy, fz, fidelity, arm_ratio, cell_mm):
    n = len(x)
    with open(path, "wb") as f:
        f.write(struct.pack("<II", 0x44314752, n))
        f.write(struct.pack("<fff", fidelity, arm_ratio, cell_mm))
        for arr in (x, y, fx, fy, fz):
            f.write(np.asarray(arr, dtype="<f4").tobytes())


def test_read_grid_bin_roundtrip(tmp_path):
    p = tmp_path / "grid.bin"
    x = [0.0, 1.0, 2.0]; y = [3.0, 4.0, 5.0]
    fx = [10.0, 11.0, 12.0]; fy = [1.0, 2.0, 3.0]; fz = [20.0, 21.0, 22.0]
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


def test_int16_extra_dim_roundtrip(tmp_path):
    """laspy int16-scaled extra dim reconstructs Newton values within one quantisation step."""
    import laspy
    fz = np.linspace(-120.0, 340.0, 5000).astype(np.float64)
    lo, hi = float(fz.min()), float(fz.max())
    scale = (hi - lo) / 65000.0 or 1.0          # int16 spans ~65k codes
    offset = (hi + lo) / 2.0
    h = laspy.LasHeader(point_format=3)
    h.offsets = [0.0, 0.0, 0.0]; h.scales = [0.001, 0.001, 0.001]
    h.add_extra_dim(laspy.ExtraBytesParams(name="Fz", type=np.int16, scales=[scale], offsets=[offset]))
    las = laspy.LasData(h)
    las.x = np.zeros(fz.size); las.y = np.zeros(fz.size); las.z = np.zeros(fz.size)
    las.Fz = fz
    p = tmp_path / "q.las"; las.write(str(p))
    back = laspy.read(str(p)).Fz
    assert np.max(np.abs(back - fz)) <= scale * 1.5     # within one code
