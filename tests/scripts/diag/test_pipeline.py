import os
import struct
import sys

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", "scripts"))

from diag.pipeline import analyse, read_d1lc

SPR = 256


def _write_d1lc(path, t, fx, fy, fz, rpm, revs, fs):
    head = struct.pack(
        "<IIIfffff", 0x44314C43, 1, t.size, float(fs), 0.05, 80.0, 0.0, float(t[-1])
    )
    with open(path, "wb") as f:
        f.write(head)
        for a in (t, fx, fy, fz, rpm, revs):
            f.write(np.ascontiguousarray(a, dtype="<f4").tobytes())


def _synthetic_cut(n_rev=40, spr=SPR, anomaly_rev=25.0, anomaly_span=0.05):
    """A clean spiral with one implanted force anomaly at a known revolution."""
    n = n_rev * spr
    revs = np.arange(n, dtype=np.float64) / spr
    fs = 25_000.0
    t = revs * 60.0 / 1200.0
    # repeatable per-rev signature + noise
    phase = 2 * np.pi * revs
    fz = 120.0 + 4.0 * np.sin(phase) + 1.5 * np.sin(3 * phase)
    rng = np.random.default_rng(7)
    fz = fz + rng.normal(scale=0.4, size=n)
    hit = np.abs(revs - anomaly_rev) < anomaly_span
    fz[hit] += 30.0
    fx = np.zeros(n)
    fy = np.zeros(n)
    rpm = np.full(n, 1200.0)
    rho = 40.0 - 0.05 * revs
    x, y = rho * np.cos(phase), rho * np.sin(phase)
    return t, fx, fy, fz, rpm, revs, x, y, fs, hit


def test_d1lc_round_trip(tmp_path):
    t, fx, fy, fz, rpm, revs, _, _, fs, _ = _synthetic_cut(n_rev=4)
    p = str(tmp_path / "c.bin")
    _write_d1lc(p, t, fx, fy, fz, rpm, revs, fs)
    c = read_d1lc(p)
    assert c["n"] == t.size
    np.testing.assert_allclose(c["fz"], fz.astype(np.float32), rtol=1e-6)


def test_pipeline_recovers_implanted_anomaly_location():
    """The test that validates the science: an anomaly implanted at a known revolution
    must come back as the strongest residual at that same revolution."""
    t, fx, fy, fz, rpm, revs, x, y, fs, hit = _synthetic_cut()
    cache = {
        "n": t.size,
        "fs": fs,
        "feed": 0.05,
        "diam": 80.0,
        "cs_sec": 0.0,
        "ce_sec": float(t[-1]),
        "t": t,
        "fx": fx,
        "fy": fy,
        "fz": fz,
        "rpm": rpm,
        "revs": revs,
    }
    cols, metrics = analyse(cache, x, y, samples_per_rev=SPR)
    peak_rev = cols["rev"][int(np.argmax(np.abs(cols["resid_z"])))]
    assert abs(peak_rev - 25.0) < 0.2
    assert metrics["n_points"] == cols["resid_z"].size


def test_pipeline_columns_are_aligned_and_finite():
    t, fx, fy, fz, rpm, revs, x, y, fs, _ = _synthetic_cut(n_rev=8)
    cache = {
        "n": t.size,
        "fs": fs,
        "feed": 0.05,
        "diam": 80.0,
        "cs_sec": 0.0,
        "ce_sec": float(t[-1]),
        "t": t,
        "fx": fx,
        "fy": fy,
        "fz": fz,
        "rpm": rpm,
        "revs": revs,
    }
    cols, _ = analyse(cache, x, y, samples_per_rev=SPR)
    sizes = {k: v.size for k, v in cols.items()}
    assert len(set(sizes.values())) == 1, sizes
    for k, v in cols.items():
        assert np.all(np.isfinite(v)), k
        assert v.dtype == np.float32, k


def test_pipeline_columns_include_spatial_coordinates():
    t, fx, fy, fz, rpm, revs, x, y, fs, _ = _synthetic_cut(n_rev=8)
    cache = {
        "n": t.size,
        "fs": fs,
        "feed": 0.05,
        "diam": 80.0,
        "cs_sec": 0.0,
        "ce_sec": float(t[-1]),
        "t": t,
        "fx": fx,
        "fy": fy,
        "fz": fz,
        "rpm": rpm,
        "revs": revs,
    }
    cols, _ = analyse(cache, x, y, samples_per_rev=SPR)
    assert set(cols) == {"t", "rev", "x", "y", "tsa_resid", "resid_z"}
    # x/y must land on the same radius the spiral actually has at that revolution --
    # not just be finite/present. rho = 40.0 - 0.05*revs in _synthetic_cut.
    r = np.hypot(cols["x"], cols["y"])
    expected_r = 40.0 - 0.05 * cols["rev"]
    np.testing.assert_allclose(r, expected_r, atol=0.05)


def test_metrics_record_effective_nyquist_and_validity():
    t, fx, fy, fz, rpm, revs, x, y, fs, _ = _synthetic_cut(n_rev=8)
    cache = {
        "n": t.size,
        "fs": fs,
        "feed": 0.05,
        "diam": 80.0,
        "cs_sec": 0.0,
        "ce_sec": float(t[-1]),
        "t": t,
        "fx": fx,
        "fy": fy,
        "fz": fz,
        "rpm": rpm,
        "revs": revs,
    }
    _, metrics = analyse(cache, x, y, samples_per_rev=SPR, fn_hz=2300.0)
    assert metrics["effective_fs_hz"] > 0
    assert metrics["effective_nyquist_hz"] == metrics["effective_fs_hz"] / 2
    # Kistler's own guidance: valid quantitative range is fn/5.
    assert abs(metrics["quantitative_limit_hz"] - 460.0) < 1e-6
