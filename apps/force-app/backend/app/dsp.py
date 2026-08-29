"""Shared signal math for the recording pipeline — channel summing, tacho→RPM, and the FRM
spiral geometry. Mirrors scripts/matlab/process_force.m and the MATLAB app's LiveFRMPlot so the
live spiral and the finalized live_cache use identical geometry. Pure NumPy (2a); the hot paths
can move to abfp_core later without changing these signatures.
"""

from __future__ import annotations

import numpy as np
from scipy import signal as ssig

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


def tacho_rising_edges(
    tacho: np.ndarray, prev_above: bool | None = None, thr: float | None = None
) -> tuple[np.ndarray, bool | None]:
    """Rising-edge sample indices in one chunk, continuing across chunk boundaries.

    Returns `(edge_indices, last_above)`; pass `last_above` back in as `prev_above` next chunk so an
    edge falling exactly on the seam is not missed or double-counted.

    Needed because a live chunk is short relative to the pulse period: the sim emits 20 ms chunks
    and a 1500 RPM / 1 PPR tacho pulses every 40 ms, so NO chunk ever contains two edges. Timing
    edges within a chunk therefore never measures anything at all — the interval that matters is
    the one from the last edge of the previous chunk to the first edge of this one.

    `thr` defaults to this chunk's own mid-level, which is only meaningful when the chunk actually
    contains a transition; callers tracking a pulse train across chunks should pass a stable
    threshold so a chunk sitting entirely at the high or low level doesn't invent one.
    """
    n = tacho.size
    if n == 0:
        return np.zeros(0, dtype=np.int64), prev_above
    if thr is None:
        lo, hi = float(np.min(tacho)), float(np.max(tacho))
        if hi - lo < 1e-9:
            # Flat chunk: no transition to threshold against. Report the level so the caller can
            # still track continuity, but find no edges.
            return np.zeros(0, dtype=np.int64), prev_above
        thr = lo + 0.5 * (hi - lo)
    above = tacho > thr
    # Prepend the previous chunk's final level so a low->high transition straddling the seam counts.
    prior = above[0] if prev_above is None else prev_above
    joined = np.concatenate(([prior], above))
    edges = np.flatnonzero((~joined[:-1]) & joined[1:]).astype(np.int64)
    return edges, bool(above[-1])


def rpm_from_tacho(tacho: np.ndarray, fs: float, ppr: int) -> tuple[np.ndarray, bool]:
    """Per-sample RPM from a tacho pulse train, by timing rising edges (a simplified tachorpm).

    Returns `(rpm, measured)`. Rising edges are detected on a mid-level threshold; instantaneous RPM
    between consecutive edges is 60 / (ppr · Δt), then interpolated to every sample. Fewer than two
    edges means there is no interval to time, so there is no rate to report: the result is zeros and
    `measured` is False. Callers must not substitute a guess for it — see below.

    This deliberately takes no `fallback`. It used to, and both callers seeded that fallback with
    the CONFIGURED spindle speed, so a tacho with no pulses reported the nominal RPM as though it
    had been measured. On the rig that produced a bit-exact, unvarying 1200.000 (and 777.000 once
    the configured value was changed) while the hall-effect sensor sat motionless on the bench —
    a fabricated reading indistinguishable from a healthy one, in the saved .mat as well as live.
    Holding the LAST MEASURED value across a short chunk is legitimate and belongs to the caller
    (FrmIntegrator does it, bounded by a staleness window); inventing a never-measured one is not.
    """
    n = tacho.size
    if n == 0:
        return np.zeros(0, dtype=np.float64), False
    lo, hi = float(np.min(tacho)), float(np.max(tacho))
    if hi - lo < 1e-9:
        return np.zeros(n, dtype=np.float64), False
    thr = lo + 0.5 * (hi - lo)
    above = tacho > thr
    edges = np.flatnonzero((~above[:-1]) & (above[1:])) + 1  # rising-edge sample indices
    if edges.size < 2:
        return np.zeros(n, dtype=np.float64), False
    edge_t = edges / fs
    inst = 60.0 / (ppr * np.diff(edge_t))  # RPM on each inter-edge interval
    # Sample-time RPM: hold each interval's value across it; extend the ends.
    rpm = np.interp(np.arange(n) / fs, edge_t[1:], inst, left=inst[0], right=inst[-1])
    return rpm, True


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


def welch_spectra(
    bufs: dict[str, np.ndarray],
    fs: float,
    nperseg: int,
    min_samples: int = 256,
    max_bins: int = 240,
) -> tuple[list[float] | None, dict[str, list[float]]]:
    """Welch AMPLITUDE spectra for a set of named channel buffers, decimated for the wire.

    One implementation shared by the live recording path (session._update_fft) and the
    /dsp/spectrum endpoint that playback calls, so a replayed cut's FFT cannot drift from a
    live one's. Buffers shorter than `min_samples` are skipped rather than erroring, since
    live chunks arrive before the rolling window has filled.

    Returns (f, {name: amp}) with f decimated to at most `max_bins` points, or (None, {}) if
    no buffer was long enough.
    """
    f: np.ndarray | None = None
    psd: dict[str, np.ndarray] = {}
    for name, buf in bufs.items():
        if buf.size < min_samples:
            continue
        f, p = ssig.welch(buf, fs=fs, nperseg=min(int(nperseg), buf.size))
        psd[name] = p
    if f is None:
        return None, {}
    step = max(1, f.size // max_bins)
    fout = f[::step].round(2).tolist()
    return fout, {n: np.sqrt(p[::step]).round(4).tolist() for n, p in psd.items()}
