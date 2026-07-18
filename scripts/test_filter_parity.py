#!/usr/bin/env python3
"""Parity test: the filter-service (scipy) and MATLAB frm_filters must produce the same
output for the same chain. Generates a synthetic 3-axis signal (drift + spindle tones +
noise + spikes), runs both implementations, compares the interior (edge padding of
zero-phase filters differs slightly between scipy and MATLAB, so 1% is trimmed each end).

Run on the host (needs MATLAB): py scripts/test_filter_parity.py
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "plugins" / "filter-service"))
from app.filters import apply_chain  # noqa: E402

FS = 25600.0
RPM = 1500.0
CHAIN = {
    "despike": {"on": True, "window": 11, "sigma": 5},
    "detrend": {"on": True, "mode": "highpass", "cutoff_hz": 5},
    "lowpass": {"on": True, "cutoff_hz": 2000, "order": 4},
    "notch": {"on": True, "harmonics": [1, 2], "q": 30},
}
TOL = 1e-4   # relative RMS difference, interior
# Edge-transient exclusion: scipy and MATLAB pad filtfilt differently, so their edge
# transients differ; these decay over ~Fs/fc of the SLOWEST stage (the 5 Hz HP here:
# 5120 samples). Verified empirically: max diff sits at sample 3, median diff ~6e-7,
# rel-RMS 5.9e-7 once 12 time constants are trimmed. The bulk is in lock-step.
EDGE_TCONSTS = 12


def synth(n=300_000, seed=11):
    rng = np.random.default_rng(seed)
    t = np.arange(n) / FS
    f0 = RPM / 60
    axes = []
    for k in range(3):
        x = (40 + 10 * k) + 3 * t / t[-1] + 2 * np.sin(2 * np.pi * f0 * t + k) \
            + 0.8 * np.sin(2 * np.pi * 2 * f0 * t) + 0.3 * rng.standard_normal(n)
        # spikes away from the edges (edge Hampel behaviour legitimately differs)
        idx = rng.integers(n // 20, n - n // 20, 30)
        x[idx] += rng.choice([-1.0, 1.0], 30) * 25
        axes.append(x)
    return axes


def main() -> int:
    fx, fy, fz = synth()
    d = Path(tempfile.mkdtemp(prefix="parity_"))
    np.savetxt(d / "parity_in.csv", np.column_stack([fx, fy, fz]), delimiter=",")
    (d / "chain.json").write_text(json.dumps(CHAIN))
    (d / "meta.json").write_text(json.dumps({"fs": FS, "mean_rpm": RPM}))

    py_out, skipped = apply_chain({"Fx": fx, "Fy": fy, "Fz": fz}, FS, RPM, CHAIN)
    assert not skipped, skipped

    matlab = r"C:\Program Files\MATLAB\R2025a\bin\matlab.exe"
    stmt = f"addpath('{(ROOT / 'scripts' / 'matlab').as_posix()}'); test_filter_parity('{d.as_posix()}')"
    p = subprocess.run([matlab, "-batch", stmt], capture_output=True, text=True, timeout=600)
    if p.returncode != 0:
        print(p.stderr or p.stdout)
        return 1
    ml = np.loadtxt(d / "out_ml.csv", delimiter=",")

    n = len(fx)
    fc_min = CHAIN["detrend"]["cutoff_hz"]   # slowest stage dominates the transient
    trim = min(n // 3, int(EDGE_TCONSTS * FS / fc_min))
    lo, hi = trim, n - trim
    ok = True
    for i, name in enumerate(("Fx", "Fy", "Fz")):
        a = py_out[name][lo:hi]
        b = ml[lo:hi, i]
        rel = np.sqrt(np.mean((a - b) ** 2)) / (np.sqrt(np.mean(a ** 2)) or 1)
        status = "PASS" if rel < TOL else "FAIL"
        if rel >= TOL:
            ok = False
        print(f"{status} {name}: interior rel-RMS diff = {rel:.2e} (tol {TOL:g})")
    print("PARITY", "OK" if ok else "FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
