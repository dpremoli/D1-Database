"""Unit tests for the filter chain + D1LC round-trip."""
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.d1lc import Cache, parse, serialise               # noqa: E402
from app.filters import ChainError, apply_chain            # noqa: E402

FS = 25600.0
RPM = 1500.0


def synth(n=200_000, seed=3):
    """Synthetic force: baseline + drift + spindle tone (1x) + HF noise + spikes."""
    rng = np.random.default_rng(seed)
    t = np.arange(n) / FS
    f0 = RPM / 60
    clean = 50 + 0.5 * np.sin(2 * np.pi * 0.7 * t)                 # slow content to keep
    drift = 3.0 * t / t[-1]                                        # linear drift
    tone = 2.0 * np.sin(2 * np.pi * f0 * t)                        # spindle 1x
    noise = 0.3 * rng.standard_normal(n)                           # broadband
    x = clean + drift + tone + noise
    spikes = rng.choice(n, 40, replace=False)
    x[spikes] += rng.choice([-1, 1], 40) * 30
    return t, x, clean, spikes


def test_despike_removes_spikes():
    _, x, _, spikes = synth()
    out, sk = apply_chain({"Fz": x}, FS, RPM, {"despike": {"on": True, "window": 11, "sigma": 5}})
    assert not sk
    assert np.max(np.abs(out["Fz"][spikes] - x[spikes])) > 20      # spikes actually replaced
    assert np.abs(out["Fz"] - x).mean() < 0.1                      # everything else untouched


def test_notch_kills_spindle_tone():
    t, x, _, _ = synth()
    f0 = RPM / 60
    out, sk = apply_chain({"Fz": x}, FS, RPM, {"notch": {"on": True, "harmonics": [1], "q": 30}})
    assert not sk
    # project onto the tone: amplitude at f0 should collapse
    proj = lambda y: 2 * np.abs(np.mean((y - y.mean()) * np.exp(-2j * np.pi * f0 * t)))
    assert proj(x) > 1.5
    assert proj(out["Fz"]) < 0.15


def test_highpass_removes_drift_keeps_ac():
    t, x, _, _ = synth()
    out, _ = apply_chain({"Fz": x}, FS, RPM, {"detrend": {"on": True, "mode": "highpass", "cutoff_hz": 5}})
    y = out["Fz"]
    # drift + DC gone (mean ~0, ends not offset), 25Hz tone retained
    assert abs(y.mean()) < 0.05
    f0 = RPM / 60
    proj = 2 * np.abs(np.mean(y * np.exp(-2j * np.pi * f0 * t)))
    assert proj > 1.5


def test_preview_nyquist_skip():
    _, x, _, _ = synth(n=50_000)
    out, sk = apply_chain({"Fz": x}, 1000.0, RPM, {"lowpass": {"on": True, "cutoff_hz": 2000, "order": 4}})
    assert len(sk) == 1 and "Nyquist" in sk[0]
    assert np.array_equal(out["Fz"], x)                            # skipped = untouched


def test_validation_errors():
    x = np.zeros(100)
    with pytest.raises(ChainError):
        apply_chain({"Fz": x}, FS, RPM, {"despike": {"on": True, "window": 10, "sigma": 5}})
    with pytest.raises(ChainError):
        apply_chain({"Fz": x}, FS, RPM, {"notch": {"on": True, "harmonics": [], "q": 30}})


def test_d1lc_roundtrip_and_stride():
    n = 1000
    c = Cache(FS, 0.1, 80.0, 1.0, 2.0,
              *(np.arange(n, dtype=np.float32) + k for k in range(6)))
    buf = serialise(c, 1)
    c2 = parse(buf)
    assert c2.n == n and c2.fs == FS and np.allclose(c2.fz, c.fz)
    c3 = parse(serialise(c, 3))
    assert c3.n == len(range(0, n, 3)) and np.allclose(c3.t, c.t[::3])
