"""Optional drift compensation (finalize) + causal live cut-start detection + FRM deferral."""

import os

import numpy as np

from app import d1lc
from app.acquisition.consumers import CutDetector, FrmIntegrator
from app.config import SIGNAL_CHANNELS, RecordConfig
from app.d1rw import RawWriter
from app.dsp import drift_check, order_spectrum_quick
from app.finalize import finalize


def _write_raw(tmp_path, n, fs, fz_per_chan):
    """Write a raw file with a given per-sample Fz sub-channel signal (cols Fz1..Fz4)."""
    p = str(tmp_path)
    os.makedirs(p, exist_ok=True)
    w = RawWriter(
        os.path.join(p, "raw.d1raw"), n_cols=1 + len(SIGNAL_CHANNELS), rate=fs, start_unix=0.0
    )
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
    # Fz = a strong linear drift + a constant cutting force; each of the 4 Fz sub-channels gets /4.
    fz_full = 5.0 + 40.0 * t  # N, big upward drift
    d = _write_raw(tmp_path, n, fs, fz_full / 4.0)
    cfg = RecordConfig(sample_rate=fs, feed=0.05, diam=80)

    finalize(d, cfg)  # no drift comp
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
    # Regression: local_diag.drift is a diagnostic on the RAW signal, independent of whether
    # drift_comp correction is enabled -- it must still report the real drift here even though
    # drift_comp has just flattened the corrected output above.
    assert summ["local_diag"]["drift"]["Fz"]["detected"] is True


def test_cut_detector_absolute():
    cfg = RecordConfig(sample_rate=1000, cut_detect_force=15.0)
    det = CutDetector(cfg, fs=1000)
    t1 = np.arange(0, 100) / 1000.0
    assert det.update(t1, np.full(100, 2.0)) is None  # below threshold
    t2 = np.arange(100, 200) / 1000.0
    fz = np.concatenate([np.full(50, 3.0), np.full(50, 30.0)])  # ramps above 15 mid-chunk
    ct = det.update(t2, fz)
    assert ct is not None and abs(ct - t2[50]) < 1e-6
    assert det.update(t2, fz) is None  # fires once


def test_cut_detector_adaptive():
    cfg = RecordConfig(sample_rate=2000, cut_detect_force=0.0)  # adaptive
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
    d = _write_raw(tmp_path, n, fs, np.ones(n))  # Fz1..Fz4 = 1.0 each
    gains = [0.0, 0.0, 0.0, 0.0, 25.0, 25.0, 25.0, 25.0]  # only Fz channels calibrated here
    cfg = RecordConfig(sample_rate=fs, feed=0.05, diam=80, dyno_gains=gains)
    finalize(d, cfg)
    fz = d1lc.parse_d1lc(open(f"{d}/live_cache.bin", "rb").read())["fz"]
    assert abs(float(np.median(fz)) - 100.0) < 1e-3  # 4 channels × 1 V × 25 N/V


def test_frm_defer_until_cut():
    cfg = RecordConfig(sample_rate=4000, feed=0.05, diam=80, frm_from_cut=True)
    frm = FrmIntegrator(cfg)
    n = 400
    t = np.arange(n) / 4000.0
    axes = {"Fx": np.zeros(n), "Fy": np.zeros(n), "Fz": np.full(n, 100.0)}
    tacho = ((np.cumsum(np.full(n, 1200 / 60.0 / 4000)) % 1.0) < 0.15) * 5.0
    pts, _, _ = frm.process(t, axes, tacho)
    assert pts.shape[0] == 0  # deferred — no spiral before cut start
    frm.mark_cut_start()
    pts2, _, _ = frm.process(t, axes, tacho)
    assert pts2.shape[0] > 0  # accumulates after cut start


def test_drift_check_flags_a_strong_linear_trend():
    fs, n = 4000, 8000
    t = np.arange(n) / fs
    axes = {
        "Fx": np.full(n, 40.0),
        "Fy": np.full(n, 60.0),
        "Fz": 5.0 + 40.0 * t,  # same strong drift as test_drift_comp_removes_linear_trend
    }
    result = drift_check(t, axes)
    assert result["Fz"]["detected"] is True
    assert result["detected"] is True
    assert result["Fx"]["detected"] is False


def test_drift_check_clean_signal_not_flagged():
    fs, n = 4000, 8000
    t = np.arange(n) / fs
    rng = np.random.default_rng(3)
    axes = {
        "Fx": 40.0 + rng.normal(scale=1.0, size=n),
        "Fy": 60.0 + rng.normal(scale=1.0, size=n),
        "Fz": 120.0 + rng.normal(scale=1.0, size=n),
    }
    result = drift_check(t, axes)
    assert result["detected"] is False


def test_local_diag_drift_check_ignores_air_cut_lead_in(tmp_path):
    """Regression: local_diag.drift must be restricted to the detected cut window
    (cs_sec..ce_sec), not the whole record -- otherwise a quiet air-cut lead-in followed by a
    steady, genuinely non-drifting cut reads as one large linear "drift" via np.polyfit over
    the step between the two, a false positive on a cut with no real drift.
    """
    fs, n_air, n_cut = 4000, 4000, 4000  # 1s quiet air-cut, then 1s of a steady cut
    n = n_air + n_cut
    fz_full = np.concatenate([np.full(n_air, 1.0), np.full(n_cut, 120.0)])
    d = _write_raw(tmp_path, n, fs, fz_full / 4.0)
    cfg = RecordConfig(sample_rate=fs, feed=0.05, diam=80)
    summ = finalize(d, cfg)
    assert summ["local_diag"]["drift"]["Fz"]["detected"] is False


def test_order_spectrum_quick_recovers_known_order():
    # 5 revolutions/sec worth of angle, a force with a clean 3rd-order component.
    spr = 64
    n_rev = 40
    revs = np.arange(n_rev * spr, dtype=np.float64) / spr
    sig = 100.0 + 8.0 * np.sin(2 * np.pi * 3.0 * revs)  # order 3
    orders, amp = order_spectrum_quick(revs, sig, samples_per_rev=spr)
    orders = np.asarray(orders)
    amp = np.asarray(amp)
    mask = orders > 0.5  # drop DC
    orders_f, amp_f = orders[mask], amp[mask]
    peak_idx = np.argmax(amp_f)
    peak_order = orders_f[peak_idx]
    assert abs(peak_order - 3.0) < 0.2
    # Amplitude, not just location: regression for the un-doubled/unwindowed normalization
    # that read exactly half the true 8.0 N amplitude (scripts/diag/angular.py's
    # order_spectrum, which this claims consistency with, uses Hann + 2/sum(w) -- an
    # unwindowed |spec|/N recovers only A/2 for a pure sinusoid).
    assert abs(amp_f[peak_idx] - 8.0) < 1.5
