import os
import struct
import sys
import zipfile
from io import BytesIO

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "scripts"))

import fast_his as fh


def _make_emd(matrix: np.ndarray) -> bytes:
    """Build a fake .EMD zip whose .HIS holds a 14-byte header + row-major float32 matrix."""
    n, C = matrix.shape
    body = bytes([1, 0, C, 0]) + b"\x00" * 10  # 14-byte header like the real files
    body += struct.pack(f"<{n * C}f", *matrix.astype("<f4").ravel().tolist())
    buf = BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("V01_TEST.HIS", body)
        zf.writestr("V01_TEST.ERG", b"")
    return buf.getvalue()


def _canonical_71(nsamples=300) -> np.ndarray:
    a = np.zeros((nsamples, 71), dtype=np.float64)
    ramp = np.concatenate([np.linspace(20, 1500, nsamples // 2), np.linspace(1500, 800, nsamples - nsamples // 2)])
    a[:, 0] = ramp                                   # pyrometer -> peak 1500
    a[:, 8] = np.clip(ramp / 30, 0, 50)              # force -> peak 50
    a[:, 13] = 1013.0                                # pressure abs (constant-ish, still kept via map)
    a[:, 20] = 1500.0                                # temp setpoint
    a[:, 23] = 50.0                                  # force setpoint
    a[:, 40] = 8.6e5                                 # uninitialised-memory garbage column
    return a


def test_decode_identifies_pyro_and_force_peaks():
    res = fh.decode_emd(_make_emd(_canonical_71()))
    assert res["format"] == "25"
    assert abs(res["summary"]["peak_temp_c"] - 1500) < 1
    assert abs(res["summary"]["peak_force_kn"] - 50) < 1
    keys = {c["key"] for c in res["columns"]}
    assert "pyro_top" in keys and "force" in keys


def test_decode_drops_garbage_columns():
    res = fh.decode_emd(_make_emd(_canonical_71()))
    # The ±1e5+ uninitialised column must never surface as a series.
    assert all(abs(c["max"]) < 1e5 for c in res["columns"])
    assert "ch40" not in {c["key"] for c in res["columns"]}


def test_decode_time_axis_is_2s_interval():
    res = fh.decode_emd(_make_emd(_canonical_71(nsamples=100)))
    assert res["n_rows"] == 100
    assert abs(res["duration_s"] - 99 * fh.SAMPLE_INTERVAL_S) < 1e-6
    assert res["csv_text"].splitlines()[0].startswith("time_s [s],")
