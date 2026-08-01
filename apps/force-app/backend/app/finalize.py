"""Finalize a capture: read the raw memmap in constant memory, sum + gain the dyno channels,
derive RPM + cumulative revs + cut window, and write the deliverables — a .mat (v1.0 layout), a
live_cache.bin (D1LC, so the plotting UI renders it directly), and summary.json.

The .mat DATA layout is [Time, Fx1,Fx2,Fy1,Fy2,Fz1,Fz2,Fz3,Fz4, Tacho] (v1.0), identical to what
the MATLAB app writes, so downstream tooling (process_force.m, the Directus crawler) is unchanged.
"""
from __future__ import annotations

import json
import os

import numpy as np
from scipy.io import savemat
from scipy.signal import detrend

from .config import RecordConfig, SIGNAL_CHANNELS
from .d1lc import write_d1lc
from .d1rw import memmap_rows, read_header
from .dsp import rpm_from_tacho, sum_axes, tacho_column

VAR_NAMES = ["Time"] + SIGNAL_CHANNELS  # 10 columns
LIVE_CACHE_TARGET = 300_000  # decimate the cache to ~this many points for the client


def _cut_window(fz: np.ndarray, t: np.ndarray, frac: float = 0.2) -> tuple[float, float]:
    """First/last time |Fz| exceeds `frac` of its peak — the active-cut window."""
    a = np.abs(fz)
    if a.size == 0 or a.max() <= 0:
        return (float(t[0]) if t.size else 0.0, float(t[-1]) if t.size else 0.0)
    thr = frac * a.max()
    on = np.flatnonzero(a > thr)
    return (float(t[on[0]]), float(t[on[-1]])) if on.size else (float(t[0]), float(t[-1]))


def finalize(capture_dir: str, cfg: RecordConfig, gain: float = 1.0) -> dict:
    raw_path = os.path.join(capture_dir, "raw.d1raw")
    hdr = read_header(raw_path)
    fs = float(hdr["rate"])
    rows = memmap_rows(raw_path)  # (n, 10) memmap
    n = rows.shape[0]
    t = np.asarray(rows[:, 0], dtype=np.float64)
    signals = np.asarray(rows[:, 1:], dtype=np.float64)  # (n, 9) in SIGNAL_CHANNELS order
    signals = signals.copy()
    # Apply volts→N gain to the 8 charge channels (Tacho is the last column — leave it). Per-channel
    # gains (from the amp's auto-ranged ranges) calibrate each channel independently; otherwise the
    # scalar gain applies (sim/replay data is already in N, so gain 1).
    gains = list(cfg.dyno_gains or [])
    if len(gains) >= 8:
        for i in range(8):
            signals[:, i] *= float(gains[i])
    else:
        signals[:, :8] *= gain

    # Optional linear drift compensation on the 8 dyno channels (like the MATLAB app's driftComp).
    # Only affects the derived outputs (.mat DATA + live_cache); the raw .d1raw is never touched.
    if cfg.drift_comp and n > 1:
        signals[:, :8] = detrend(signals[:, :8], axis=0, type="linear")

    axes = sum_axes(signals)
    tacho = tacho_column(signals)
    rpm = rpm_from_tacho(tacho, fs, cfg.ppr, fallback=cfg.rpm)
    dt = 1.0 / fs
    revs_cum = np.cumsum(rpm / 60.0 * dt)
    cs_sec, ce_sec = _cut_window(axes["Fz"], t)

    # --- .mat (v1.0), full resolution ---
    data = np.empty((n, 10), dtype=np.float64)
    data[:, 0] = t
    data[:, 1:] = signals
    metadata = {
        "fileVersion": 1.0,
        "SampleName": cfg.sample_name,
        "Rate": fs,
        "CutDiameter": cfg.diam,
        "InnerDiameter": cfg.inner_diam,
        "Feed": cfg.feed,
        "MaxRPM": cfg.rpm,
        "SurfaceSpeed": np.pi * cfg.diam * cfg.rpm / 1000.0,  # m/min
        "PulsesPerRev": cfg.ppr,
        "Source": "force-app 2a",
    }
    # Stamp any UI-compiled metadata (sample/insert/tool/etc.) into the .mat struct.
    for k, v in (cfg.extra_metadata or {}).items():
        if k not in metadata and v not in (None, ""):
            metadata[str(k)] = v
    savemat(
        os.path.join(capture_dir, "capture.mat"),
        {"DATA": data, "metadata": metadata, "VariableNames": np.array(VAR_NAMES, dtype=object)},
        do_compression=True,
    )

    # --- live_cache.bin (D1LC), decimated for the client ---
    stride = max(1, n // LIVE_CACHE_TARGET)
    sl = slice(None, None, stride)
    fs_eff = fs / stride
    write_d1lc(
        os.path.join(capture_dir, "live_cache.bin"),
        t[sl].astype(np.float32), axes["Fx"][sl].astype(np.float32),
        axes["Fy"][sl].astype(np.float32), axes["Fz"][sl].astype(np.float32),
        rpm[sl].astype(np.float32), revs_cum[sl].astype(np.float32),
        fs=fs_eff, feed=cfg.feed, diam=cfg.diam, cs_sec=cs_sec, ce_sec=ce_sec,
    )

    summary = {
        "sample_name": cfg.sample_name,
        "fs": fs,
        "n": int(n),
        "duration_sec": float(t[-1] - t[0]) if n > 1 else 0.0,
        "channels": VAR_NAMES,
        "peaks": {ax: float(np.max(np.abs(axes[ax]))) for ax in ("Fx", "Fy", "Fz")},
        "cut_window_sec": [cs_sec, ce_sec],
        "drift_comp": bool(cfg.drift_comp),
        "metadata": cfg.extra_metadata or {},
        "config": cfg.model_dump(),
        "files": {"mat": "capture.mat", "live_cache": "live_cache.bin", "raw": "raw.d1raw"},
    }
    with open(os.path.join(capture_dir, "summary.json"), "w") as f:
        json.dump(summary, f, indent=2)
    return summary
