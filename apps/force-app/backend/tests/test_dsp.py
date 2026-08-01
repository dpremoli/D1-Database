"""Signal math: channel summing, tacho→RPM, FRM spiral."""

import numpy as np

from app.config import SIGNAL_CHANNELS
from app.dsp import frm_spiral, rpm_from_tacho, sum_axes


def test_sum_axes():
    n = 100
    sig = np.zeros((n, len(SIGNAL_CHANNELS)))
    col = {c: i for i, c in enumerate(SIGNAL_CHANNELS)}
    sig[:, col["Fx1"]] = 1.0
    sig[:, col["Fx2"]] = 2.0
    sig[:, col["Fz1"]] = sig[:, col["Fz2"]] = sig[:, col["Fz3"]] = sig[:, col["Fz4"]] = 5.0
    axes = sum_axes(sig)
    assert np.allclose(axes["Fx"], 3.0) and np.allclose(axes["Fz"], 20.0)


def test_rpm_from_tacho_constant():
    fs, rpm_true, ppr, dur = 20_000.0, 1500.0, 1, 1.0
    n = int(fs * dur)
    t = np.arange(n) / fs
    pulse_f = rpm_true * ppr / 60.0
    tacho = ((pulse_f * t) % 1.0 < 0.15).astype(float) * 5.0
    rpm = rpm_from_tacho(tacho, fs, ppr, fallback=0.0)
    # steady-state RPM should recover the truth within ~2%
    assert abs(np.median(rpm) - rpm_true) / rpm_true < 0.02


def test_rpm_fallback_when_flat():
    rpm = rpm_from_tacho(np.zeros(50), 1000.0, 1, fallback=999.0)
    assert np.allclose(rpm, 999.0)


def test_frm_spiral_revs():
    fs, rpm_val, dur = 10_000.0, 1200.0, 2.0
    n = int(fs * dur)
    t = np.arange(n) / fs
    rpm = np.full(n, rpm_val)
    x, y, revs = frm_spiral(t, rpm, feed=0.05, axis_force=np.zeros(n), diam=80.0)
    assert abs(revs[-1] - rpm_val / 60.0 * dur) / (rpm_val / 60.0 * dur) < 0.01
    # spiral radius stays within the disc and winds inward from the rim
    r = np.hypot(x, y)
    assert r.max() <= 40.0 + 1e-6 and r[-1] < r[0]
