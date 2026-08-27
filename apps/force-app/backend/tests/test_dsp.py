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


def test_welch_spectra_peaks_at_the_input_frequency():
    import numpy as np

    from app.dsp import welch_spectra

    fs, n, f0 = 2000.0, 4096, 120.0
    t = np.arange(n) / fs
    bufs = {
        "Fz": np.sin(2 * np.pi * f0 * t),
        "Fx": np.zeros(n),
        "Short": np.zeros(10),  # below min_samples — must be dropped, not crash
    }
    f, spectra = welch_spectra(bufs, fs=fs, nperseg=1024)

    assert f is not None
    assert "Short" not in spectra
    assert set(spectra) == {"Fz", "Fx"}
    # step = f.size // max_bins is a floor division (matching the pre-existing
    # session._update_fft formula this preserves), so the sliced result can land a little
    # over max_bins rather than exactly at or under it — bound generously, not exactly.
    assert len(f) == len(spectra["Fz"]) <= 260
    peak_hz = f[int(np.argmax(spectra["Fz"]))]
    assert abs(peak_hz - f0) < 10.0, f"peak at {peak_hz} Hz, expected ~{f0}"


def test_welch_spectra_empty_when_all_buffers_too_short():
    import numpy as np

    from app.dsp import welch_spectra

    f, spectra = welch_spectra({"Fz": np.zeros(4)}, fs=1000.0, nperseg=256)
    assert f is None and spectra == {}
