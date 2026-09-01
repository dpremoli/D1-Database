import os
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", "scripts"))

SPR = 256


def synthetic_cut(n_rev=40, spr=SPR, anomaly_rev=25.0, anomaly_span=0.05):
    """A clean spiral with one implanted force anomaly at a known revolution.

    Seeded (default_rng(7)) so the golden reference is reproducible. Identical to the
    fixture test_pipeline.py used privately before this was extracted.
    """
    n = n_rev * spr
    revs = np.arange(n, dtype=np.float64) / spr
    fs = 25_000.0
    t = revs * 60.0 / 1200.0
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


def cache_of(t, fx, fy, fz, rpm, revs, fs):
    return {
        "n": t.size, "fs": fs, "feed": 0.05, "diam": 80.0,
        "cs_sec": 0.0, "ce_sec": float(t[-1]),
        "t": t, "fx": fx, "fy": fy, "fz": fz, "rpm": rpm, "revs": revs,
    }


@pytest.fixture
def standard_cut():
    """(cache, x, y) for the 40-revolution reference cut."""
    t, fx, fy, fz, rpm, revs, x, y, fs, _ = synthetic_cut()
    return cache_of(t, fx, fy, fz, rpm, revs, fs), x, y
