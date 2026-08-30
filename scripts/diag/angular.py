"""Angular-domain (order) analysis.

Resampling to equal angular increments makes everything spindle-synchronous stationary
regardless of speed variation, which matters because face turning changes cutting speed
continuously as the radius falls. Two things fall out of it:

  * order spectrum — insert-passing harmonics land in fixed integer bins, so chatter shows
    up as NON-integer orders rather than as a peak you have to interpret;
  * time-synchronous averaging — the per-revolution mean is the repeatable signature (tool
    geometry, runout, fixture), and the residual is what does not repeat. The residual is
    the anomaly substrate every downstream statistic runs on.

`revs_cum` is already integrated from the tacho by process_force.m and carried in the D1LC
cache, so resampling is one np.interp and costs almost nothing.
"""

from __future__ import annotations

import numpy as np


def angular_resample(
    revs_cum: np.ndarray, sig: np.ndarray, samples_per_rev: int
) -> tuple[np.ndarray, np.ndarray]:
    """Resample `sig` onto a uniform grid of shaft revolutions.

    Returns (rev_grid, resampled). `revs_cum` must be non-decreasing — it is a cumulative
    angle, so a decrease means the tacho integration is corrupt and interpolating through it
    would silently fabricate samples.
    """
    revs_cum = np.asarray(revs_cum, dtype=np.float64)
    sig = np.asarray(sig, dtype=np.float64)
    if revs_cum.shape != sig.shape:
        raise ValueError(
            f"revs_cum shape {revs_cum.shape} does not match sig shape {sig.shape}"
        )
    if revs_cum.size < 2:
        raise ValueError("need at least two samples to resample")
    if np.any(np.diff(revs_cum) < 0):
        raise ValueError("revs_cum must be monotonic non-decreasing")
    if samples_per_rev < 1:
        raise ValueError("samples_per_rev must be >= 1")
    r0, r1 = float(revs_cum[0]), float(revs_cum[-1])
    n = int(np.floor((r1 - r0) * samples_per_rev))
    if n < 1:
        raise ValueError("span covers less than one resampled step")
    grid = r0 + np.arange(n, dtype=np.float64) / samples_per_rev
    return grid, np.interp(grid, revs_cum, sig)


def tsa(resampled: np.ndarray, samples_per_rev: int) -> tuple[np.ndarray, np.ndarray]:
    """Time-synchronous average over whole revolutions.

    Returns (signature, residual). `signature` is the per-revolution mean of length
    `samples_per_rev`; `residual` is the input minus that signature, truncated to whole
    revolutions (so it is shorter than the input whenever the cut does not end on a
    revolution boundary — callers must use the returned length, not the input's).
    """
    resampled = np.asarray(resampled, dtype=np.float64)
    n_rev = resampled.size // samples_per_rev
    if n_rev < 1:
        raise ValueError("need at least one full revolution for TSA")
    block = resampled[: n_rev * samples_per_rev].reshape(n_rev, samples_per_rev)
    signature = block.mean(axis=0)
    return signature, (block - signature).ravel()


def order_spectrum(
    resampled: np.ndarray, samples_per_rev: int
) -> tuple[np.ndarray, np.ndarray]:
    """Single-sided amplitude spectrum in orders (cycles per revolution)."""
    resampled = np.asarray(resampled, dtype=np.float64)
    n = resampled.size
    if n < 2:
        raise ValueError("need at least two samples for a spectrum")
    w = np.hanning(n)
    spec = np.abs(np.fft.rfft((resampled - resampled.mean()) * w))
    amp = spec * (2.0 / w.sum())
    orders = np.fft.rfftfreq(n, d=1.0 / samples_per_rev)
    return orders, amp
