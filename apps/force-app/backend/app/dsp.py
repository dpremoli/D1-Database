"""Shared signal math for the recording pipeline — channel summing, tacho→RPM, and the FRM
spiral geometry. Mirrors scripts/matlab/process_force.m and the MATLAB app's LiveFRMPlot so the
live spiral and the finalized live_cache use identical geometry. Pure NumPy (2a); the hot paths
can move to abfp_core later without changing these signatures.
"""
from __future__ import annotations

import numpy as np

from .config import AXIS_SUM, SIGNAL_CHANNELS


def sum_axes(signals: np.ndarray) -> dict[str, np.ndarray]:
    """signals: (n, len(SIGNAL_CHANNELS)) → {'Fx','Fy','Fz'} summed sub-channels."""
    idx = {name: i for i, name in enumerate(SIGNAL_CHANNELS)}
    out: dict[str, np.ndarray] = {}
    for axis, parts in AXIS_SUM.items():
        out[axis] = np.sum(signals[:, [idx[p] for p in parts]], axis=1)
    return out


def tacho_column(signals: np.ndarray) -> np.ndarray:
    return signals[:, SIGNAL_CHANNELS.index("Tacho")]


def rpm_from_tacho(tacho: np.ndarray, fs: float, ppr: int, fallback: float = 0.0) -> np.ndarray:
    """Per-sample RPM from a tacho pulse train, by timing rising edges (a simplified tachorpm).

    Rising edges are detected on a mid-level threshold; instantaneous RPM between consecutive edges
    is 60 / (ppr · Δt), then interpolated to every sample. With <2 edges we return the fallback
    (last-known / configured RPM), so short live chunks degrade gracefully.
    """
    n = tacho.size
    if n == 0:
        return np.zeros(0, dtype=np.float64)
    lo, hi = float(np.min(tacho)), float(np.max(tacho))
    if hi - lo < 1e-9:
        return np.full(n, fallback, dtype=np.float64)
    thr = lo + 0.5 * (hi - lo)
    above = tacho > thr
    edges = np.flatnonzero((~above[:-1]) & (above[1:])) + 1  # rising-edge sample indices
    if edges.size < 2:
        return np.full(n, fallback, dtype=np.float64)
    edge_t = edges / fs
    inst = 60.0 / (ppr * np.diff(edge_t))  # RPM on each inter-edge interval
    # Sample-time RPM: hold each interval's value across it; extend the ends.
    rpm = np.interp(np.arange(n) / fs, edge_t[1:], inst, left=inst[0], right=inst[-1])
    return rpm


def frm_spiral(
    t: np.ndarray,
    rpm: np.ndarray,
    feed: float,
    axis_force: np.ndarray,
    diam: float,
    inner_diam: float = 0.0,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Integrate the FRM fingerprint spiral (mm) from per-sample RPM + feed.

    θ accumulates spindle angle (rpm·2π/60·dt); ρ winds inward by feed per rev
    (−feed/10·rpm/60·dt), offset so the spiral starts at the outer radius. Returns (x, y, revs_cum).
    Matches process_force.m lines ~168-178 and the app's LiveFRMPlot.
    """
    dt = np.gradient(t) if t.size > 1 else np.array([0.0])
    dtheta = rpm * (2.0 * np.pi / 60.0) * dt
    theta = np.cumsum(dtheta)
    revs_cum = theta / (2.0 * np.pi)
    drho = -(feed / 10.0) * (rpm / 60.0) * dt
    rho = np.cumsum(drho)
    r_outer = diam / 2.0
    rho = r_outer + rho  # start at the rim, spiral inward
    if inner_diam > 0:
        rho = np.maximum(rho, inner_diam / 2.0)
    x = rho * np.cos(theta)
    y = rho * np.sin(theta)
    return x, y, revs_cum
