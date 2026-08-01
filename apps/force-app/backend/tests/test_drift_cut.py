"""Optional drift compensation (finalize) + causal live cut-start detection + FRM deferral."""
import os

import numpy as np

from app import d1lc
from app.acquisition.consumers import CutDetector, FrmIntegrator
from app.config import RecordConfig, SIGNAL_CHANNELS
from app.d1rw import RawWriter
from app.dsp import sum_axes
from app.finalize import finalize


def _write_raw(tmp_path, n, fs, fz_per_chan):
    """Write a raw file with a given per-sample Fz sub-channel signal (cols Fz1..Fz4)."""
    p = str(tmp_path)
    os.makedirs(p, exist_ok=True)
    w = RawWriter(os.path.join(p, "raw.d1raw"), n_cols=1 + len(SIGNAL_CHANNELS), rate=fs, start_unix=0.0)
    t = np.arange(n) / fs
    data = np.zeros((n, len(SIGNAL_CHANNELS)))
    for c in (4, 5, 6, 7):  # Fz1..Fz4
        data[:, c] = fz_per_chan
    # a tacho pulse train so rpm derivation works
    data[:, 8] = ((np.cumsum(np.full(n, 1200 / 60.0 / fs)) % 1.0) < 0.15) * 5.0
    w.append(t, data)
    w.close()
    return p


def test_drift_comp_removes_linear_trend(tmp_path):
    fs, n = 4000, 8000
    t = np.arange(n) / fs
    # Fz = a strong linear drift + a constant cutting force; each of the 4 Fz sub-channels carries /4.
    fz_full = (5.0 + 40.0 * t)  # N, big upward drift
    d = _write_raw(tmp_path, n, fs, fz_full / 4.0)
    cfg = RecordConfig(sample_rate=fs, feed=0.05, diam=80)

    finalize(d, cfg)  # no drift comp
    raw = np.frombuffer(open(f"{d}/live_cache.bin", "rb").read(), dtype="<f4")
    fz_plain = d1lc.parse_d1lc(open(f"{d}/live_cache.bin", "rb").read())["fz"]
    slope_plain = np.polyfit(np.arange(fz_plain.size), fz_plain, 1)[0]

    cfg2 = RecordConfig(sample_rate=fs, feed=0.05, diam=80, drift_comp=True)
    finalize(d, cfg2)
    parsed = d1lc.parse_d1lc(open(f"{d}/live_cache.bin", "rb").read())
    fz_dc = parsed["fz"]
    slope_dc = abs(np.polyfit(np.arange(fz_dc.size), fz_dc, 1)[0])
    # drift comp should flatten the trend to ~0
    assert slope_dc < abs(slope_plain) * 0.05
    import json
    summ = json.load(open(f"{d}/summary.json"))
    assert summ["drift_comp"] is True


def test_cut_detector_absolute():
    cfg = RecordConfig(sample_rate=1000, cut_detect_force=15.0)
    det = CutDetector(cfg, fs=1000)
    t1 = np.arange(0, 100) / 1000.0
    assert det.update(t1, np.full(100, 2.0)) is None            # below threshold
    t2 = np.arange(100, 200) / 1000.0
    fz = np.concatenate([np.full(50, 3.0), np.full(50, 30.0)])  # ramps above 15 mid-chunk
    ct = det.update(t2, fz)
    assert ct is not None and abs(ct - t2[50]) < 1e-6
    assert det.update(t2, fz) is None                            # fires once


def test_cut_detector_adaptive():
    cfg = RecordConfig(sample_rate=2000, cut_detect_force=0.0)   # adaptive
    det = CutDetector(cfg, fs=2000, baseline_sec=0.1)
    rng = np.random.default_rng(0)
    # ~0.1s quiet baseline (low noise) then a clear jump
    for k in range(4):
        t = np.arange(k * 100, (k + 1) * 100) / 2000.0
        det.update(t, np.abs(rng.normal(0, 1.0, 100)))
    t = np.arange(400, 500) / 2000.0
    ct = det.update(t, np.full(100, 120.0))
    assert ct is not None


def test_per_channel_gain(tmp_path):
    # Raw Fz sub-channels carry 1.0 V each -> summed Fz = 4 V. With per-channel gain 25 N/V on the
    # Fz channels, the finalized Fz = 4 V × 25 = 100 N (Fx/Fy gains here are 0 so those sum to 0).
    fs, n = 4000, 4000
    d = _write_raw(tmp_path, n, fs, np.ones(n))          # Fz1..Fz4 = 1.0 each
    gains = [0.0, 0.0, 0.0, 0.0, 25.0, 25.0, 25.0, 25.0]  # only Fz channels calibrated here
    cfg = RecordConfig(sample_rate=fs, feed=0.05, diam=80, dyno_gains=gains)
    finalize(d, cfg)
    fz = d1lc.parse_d1lc(open(f"{d}/live_cache.bin", "rb").read())["fz"]
    assert abs(float(np.median(fz)) - 100.0) < 1e-3       # 4 channels × 1 V × 25 N/V


def test_frm_defer_until_cut():
    cfg = RecordConfig(sample_rate=4000, feed=0.05, diam=80, frm_from_cut=True)
    frm = FrmIntegrator(cfg)
    n = 400
    t = np.arange(n) / 4000.0
    axes = {"Fx": np.zeros(n), "Fy": np.zeros(n), "Fz": np.full(n, 100.0)}
    tacho = ((np.cumsum(np.full(n, 1200 / 60.0 / 4000)) % 1.0) < 0.15) * 5.0
    pts, _ = frm.process(t, axes, tacho)
    assert pts.shape[0] == 0                 # deferred — no spiral before cut start
    frm.mark_cut_start()
    pts2, _ = frm.process(t, axes, tacho)
    assert pts2.shape[0] > 0                  # accumulates after cut start
