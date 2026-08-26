"""POST /dsp/spectrum — the stateless Welch endpoint playback uses for its FFT panel."""

import numpy as np
from fastapi.testclient import TestClient

from app.dsp import welch_spectra
from app.main import app

client = TestClient(app)


def _body(*channels: np.ndarray) -> bytes:
    return np.concatenate(channels).astype("<f4").tobytes()


def test_spectrum_peaks_at_the_input_frequency():
    fs, n, f0 = 2000.0, 4096, 120.0
    t = np.arange(n) / fs
    fz = np.sin(2 * np.pi * f0 * t)
    res = client.post(
        "/dsp/spectrum",
        params={"fs": fs, "names": "Fz", "nperseg": 1024},
        content=_body(fz),
        headers={"Content-Type": "application/octet-stream"},
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["fs"] == fs
    peak_hz = body["f"][int(np.argmax(body["spectra"]["Fz"]))]
    assert abs(peak_hz - f0) < 10.0


def test_spectrum_matches_welch_spectra_exactly():
    """The endpoint and the live path must not drift — same input, same numbers."""
    fs, n = 2000.0, 4096
    rng = np.random.default_rng(0)
    fx = rng.standard_normal(n).astype("<f4")
    fz = rng.standard_normal(n).astype("<f4")
    res = client.post(
        "/dsp/spectrum",
        params={"fs": fs, "names": "Fx,Fz", "nperseg": 1024},
        content=_body(fx, fz),
        headers={"Content-Type": "application/octet-stream"},
    )
    assert res.status_code == 200, res.text
    body = res.json()
    f_ref, spec_ref = welch_spectra(
        {"Fx": fx.astype(np.float64), "Fz": fz.astype(np.float64)}, fs=fs, nperseg=1024
    )
    assert body["f"] == f_ref
    assert body["spectra"] == spec_ref


def test_spectrum_rejects_a_body_that_is_not_a_multiple_of_the_channel_count():
    res = client.post(
        "/dsp/spectrum",
        params={"fs": 1000.0, "names": "Fx,Fz"},
        content=np.zeros(101, dtype="<f4").tobytes(),
        headers={"Content-Type": "application/octet-stream"},
    )
    assert res.status_code == 422


def test_spectrum_reports_no_bins_when_the_window_is_too_short():
    res = client.post(
        "/dsp/spectrum",
        params={"fs": 1000.0, "names": "Fz"},
        content=np.zeros(8, dtype="<f4").tobytes(),
        headers={"Content-Type": "application/octet-stream"},
    )
    assert res.status_code == 200
    assert res.json() == {"fs": 1000.0, "f": [], "spectra": {}}
