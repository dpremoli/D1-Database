"""Streaming consumers: min/max decimation for the rolling plot, and the stateful FRM spiral
integrator for the live fingerprint. Both operate per chunk; the RawWriter (app/d1rw.py) is the
third consumer and is driven directly by the session so raw data is never dropped."""

from __future__ import annotations

import numpy as np

from ..config import RecordConfig
from ..dsp import rpm_from_tacho


class CutDetector:
    """Causal (real-time) cut-start detection on |Fz|. Unlike the offline detector (which uses a
    fraction of the FULL-signal peak), this can't see the future — so it uses a short leading
    baseline (assumed air-cut) to set an adaptive threshold, or an absolute force floor. Once."""

    def __init__(
        self,
        cfg: RecordConfig,
        fs: float,
        baseline_sec: float = 0.15,
        margin_std: float = 6.0,
        margin_abs: float = 8.0,
    ):
        self.floor = float(cfg.cut_detect_force)  # >0 => absolute threshold
        self.baseline_target = int(max(1, baseline_sec * fs))
        self.margin_std = margin_std
        self.margin_abs = margin_abs
        self._bn = 0
        self._bsum = 0.0
        self._bsq = 0.0
        self._thr: float | None = None
        self.detected = False
        self.cut_t: float | None = None

    def update(self, t: np.ndarray, fz_abs: np.ndarray) -> float | None:
        """Feed one chunk; returns the cut time (s) if detected this call, else None."""
        if self.detected or fz_abs.size == 0:
            return None
        thr = self.floor if self.floor > 0 else self._thr
        if thr is None:
            # Build the adaptive baseline from the leading samples, then set the threshold.
            take = min(self.baseline_target - self._bn, fz_abs.size)
            seg = fz_abs[:take]
            self._bsum += float(seg.sum())
            self._bsq += float(np.dot(seg, seg))
            self._bn += take
            if self._bn >= self.baseline_target:
                mean = self._bsum / self._bn
                std = (max(0.0, self._bsq / self._bn - mean * mean)) ** 0.5
                self._thr = mean + max(self.margin_abs, self.margin_std * std)
            return None  # don't detect while/just as baseline forms
        exceed = np.flatnonzero(fz_abs > thr)
        if exceed.size:
            self.detected = True
            self.cut_t = float(t[int(exceed[0])])
            return self.cut_t
        return None


class Decimator:
    """Min/max envelope of the summed axes, so the rolling plot shows peaks regardless of Fs.

    Per chunk, split into `bins` windows and emit, per window, the min and max of Fx/Fy/Fz plus the
    window centre time. Output is a (bins, 7) float32 array: [t, fxminmax, fyminmax, fzminmax].
    """

    def __init__(self, bins: int = 2):
        self.bins = max(1, bins)

    def process(self, t: np.ndarray, axes: dict[str, np.ndarray]) -> np.ndarray:
        n = t.size
        b = min(self.bins, n)
        edges = np.linspace(0, n, b + 1).astype(int)
        out = np.empty((b, 7), dtype=np.float32)
        for i in range(b):
            s, e = edges[i], max(edges[i] + 1, edges[i + 1])
            out[i, 0] = 0.5 * (t[s] + t[e - 1])
            for j, ax in enumerate(("Fx", "Fy", "Fz")):
                seg = axes[ax][s:e]
                out[i, 1 + 2 * j] = seg.min()
                out[i, 2 + 2 * j] = seg.max()
        return out


class FrmIntegrator:
    """Accumulate the FRM spiral across chunks. Carries θ/ρ between calls so the fingerprint winds
    continuously. RPM is derived from the tacho pulse train each chunk (real path), falling back to
    the last-known RPM when a chunk is too short to time an edge."""

    def __init__(self, cfg: RecordConfig, max_points_per_frame: int = 300):
        self.cfg = cfg
        self.max_pts = max_points_per_frame
        self.fs = float(cfg.sample_rate)
        self.r_outer = cfg.diam / 2.0
        self.r_inner = cfg.inner_diam / 2.0 if cfg.inner_diam > 0 else 0.0
        self._theta = 0.0  # accumulated spindle angle (rad)
        self._rho_off = 0.0  # accumulated inward wind (mm, negative)
        self._last_rpm = cfg.rpm
        # When frm_from_cut, the spiral is held at the origin until the cut start is detected, so
        # air-cut revolutions don't offset the geometry (the FRM assumes the cut starts at the rim).
        self._active = not cfg.frm_from_cut

    def mark_cut_start(self) -> None:
        """Reset the spiral origin (θ=0, ρ=r_outer) at the detected cut start, then accumulate."""
        self._theta = 0.0
        self._rho_off = 0.0
        self._active = True

    def process(self, t: np.ndarray, axes: dict[str, np.ndarray], tacho: np.ndarray):
        """Returns (points: (k,3) float32 [x,y,c], mean_rpm) for the NEW samples in this chunk."""
        n = t.size
        rpm = rpm_from_tacho(tacho, self.fs, self.cfg.ppr, fallback=self._last_rpm)
        self._last_rpm = float(np.mean(rpm)) if n else self._last_rpm
        if not self._active:
            return np.empty((0, 3), dtype=np.float32), self._last_rpm  # pre-cut: no spiral yet
        dt = 1.0 / self.fs
        theta = self._theta + np.cumsum(rpm * (2.0 * np.pi / 60.0) * dt)
        rho_off = self._rho_off + np.cumsum(-(self.cfg.feed / 10.0) * (rpm / 60.0) * dt)
        self._theta = float(theta[-1])
        self._rho_off = float(rho_off[-1])
        rho = self.r_outer + rho_off
        if self.r_inner > 0:
            rho = np.maximum(rho, self.r_inner)
        x = rho * np.cos(theta)
        y = rho * np.sin(theta)
        c = axes[self.cfg.axis]  # colour by the chosen axis force (frontend normalises)
        stride = max(1, n // self.max_pts)
        pts = np.empty((x[::stride].size, 3), dtype=np.float32)
        pts[:, 0] = x[::stride]
        pts[:, 1] = y[::stride]
        pts[:, 2] = c[::stride]
        return pts, self._last_rpm
