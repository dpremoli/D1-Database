"""Streaming consumers: min/max decimation for the rolling plot, and the stateful FRM spiral
integrator for the live fingerprint. Both operate per chunk; the RawWriter (app/d1rw.py) is the
third consumer and is driven directly by the session so raw data is never dropped."""

from __future__ import annotations

import numpy as np

from ..config import RecordConfig
from ..dsp import tacho_rising_edges


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

    def force_start(self, cut_t: float) -> None:
        """The operator marked the cut start by hand (#184): count it as detected at `cut_t`, so
        the detector never fires a second, re-origining time."""
        self.detected = True
        self.cut_t = float(cut_t)

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

    def process_cols(self, t: np.ndarray, cols: np.ndarray) -> np.ndarray:
        """Per-column min/max envelope over the same bins as `process` — used to stream each dyno
        sub-channel live. `cols` is (n, k); returns (bins, k*2) as [min0,max0, min1,max1, …]."""
        n = t.size
        b = min(self.bins, n)
        edges = np.linspace(0, n, b + 1).astype(int)
        k = cols.shape[1]
        out = np.empty((b, k * 2), dtype=np.float32)
        for i in range(b):
            s, e = edges[i], max(edges[i] + 1, edges[i + 1])
            seg = cols[s:e]
            out[i, 0::2] = seg.min(axis=0)
            out[i, 1::2] = seg.max(axis=0)
        return out


class FrmIntegrator:
    """Accumulate the FRM spiral across chunks. Carries θ/ρ between calls so the fingerprint winds
    continuously. RPM is derived from the tacho pulse train each chunk (real path), holding the last
    MEASURED rate when a chunk is too short to time an edge pair, and reporting no-signal once that
    has gone on longer than TACHO_STALE_SEC — measured from the last successful edge, or from
    recording start if there has never been one, so a tacho that's silent from the very beginning is
    judged by the same rule as one that goes silent partway through, not flagged instantly on the
    first chunk. It never substitutes the configured spindle speed."""

    # How long to keep reporting the last measured rate before declaring the tacho lost. This is a
    # floor on measurable speed as well as a fault timeout: pulses arrive every 2 s at 30 RPM / 1
    # PPR, so anything slower than that reads as no-signal. Machining spindles run far above it, and
    # the alternative — a longer window — means an operator keeps seeing a plausible number for
    # seconds after the sensor dies.
    TACHO_STALE_SEC = 2.0

    def __init__(
        self, cfg: RecordConfig, *, fs: float | None = None, max_points_per_frame: int = 300
    ):
        self.cfg = cfg
        self.max_pts = max_points_per_frame
        # The rate data ACTUALLY arrives at, which is not always cfg.sample_rate: a ReplaySource
        # decimates a long cut and streams at fs/stride, so reading cfg.sample_rate here reported
        # RPM high by exactly that stride. Callers that genuinely acquire at cfg.sample_rate can
        # omit it. CutDetector and session._update_fft already take source.rate for this reason.
        self.fs = float(cfg.sample_rate if fs is None else fs)
        self.r_outer = cfg.diam / 2.0
        self.r_inner = cfg.inner_diam / 2.0 if cfg.inner_diam > 0 else 0.0
        self._theta = 0.0  # accumulated spindle angle (rad)
        self._rho_off = 0.0  # accumulated inward wind (mm, negative)
        # Seeded at 0 (= "nothing measured yet"), NOT cfg.rpm. Seeding from the configured spindle
        # speed meant a tacho that never produced a pulse reported the nominal forever: the value
        # was handed to rpm_from_tacho as its fallback, came straight back, and was written to
        # _last_rpm again each chunk. See test_frm_integrator_reports_zero_rpm_for_a_stationary_tacho.
        self._last_rpm = 0.0
        # None = not yet known (warm-up: timing an edge-pair takes at least one pulse period, which
        # almost always spans a chunk boundary, so there is genuinely nothing to report yet).
        # Seeding this False meant the very first chunk of every real recording reported "no
        # signal" before there had been any chance to measure a pulse — see
        # test_frm_integrator_does_not_flag_a_healthy_tacho_during_warm_up.
        self._tacho_ok: bool | None = None
        # Cross-chunk edge timing state. A chunk is typically far shorter than the pulse period
        # (20 ms chunks vs a 40 ms period at 1500 RPM), so the interval that yields the rate almost
        # always spans a chunk boundary — these carry it. `_thr` is latched from the first chunk
        # that actually shows a transition, so a chunk sitting wholly high or wholly low is measured
        # against the real pulse levels instead of its own noise.
        self._prev_above: bool | None = None
        self._last_edge_t: float | None = None
        self._thr: float | None = None
        # When frm_from_cut, the spiral is held at the origin until the cut start is detected, so
        # air-cut revolutions don't offset the geometry (the FRM assumes the cut starts at the rim).
        self._active = not cfg.frm_from_cut

    def mark_cut_start(self) -> None:
        """Reset the spiral origin (θ=0, ρ=r_outer) at the detected cut start, then accumulate."""
        self._theta = 0.0
        self._rho_off = 0.0
        self._active = True

    def _rpm_for_chunk(self, t: np.ndarray, tacho: np.ndarray) -> np.ndarray:
        """Per-sample RPM for this chunk, timing rising edges across chunk boundaries.

        Each edge is timed against the PREVIOUS edge wherever that fell — usually in an earlier
        chunk. The rate then steps at each edge and holds between them. Sets `_tacho_ok`/`_last_rpm`
        as a side effect; `_last_rpm` stays 0 and `_tacho_ok` stays None (not yet known) until a
        real interval has been timed, so an absent pulse train can never be reported as the
        configured spindle speed.
        """
        n = t.size
        if n == 0:
            return np.zeros(0, dtype=np.float64)

        # Latch a stable threshold from the first chunk that contains a genuine transition. Without
        # it, a chunk resting entirely at one level would threshold against its own noise floor and
        # manufacture edges out of it.
        lo, hi = float(np.min(tacho)), float(np.max(tacho))
        if self._thr is None and hi - lo > 1e-9:
            self._thr = lo + 0.5 * (hi - lo)

        edges, last_above = tacho_rising_edges(tacho, self._prev_above, thr=self._thr)
        self._prev_above = last_above

        rpm = np.full(n, self._last_rpm, dtype=np.float64)
        for idx in edges:
            edge_t = float(t[idx])
            if self._last_edge_t is not None:
                dt_edge = edge_t - self._last_edge_t
                if dt_edge > 0:
                    self._last_rpm = 60.0 / (self.cfg.ppr * dt_edge)
                    self._tacho_ok = True
            self._last_edge_t = edge_t
            rpm[idx:] = self._last_rpm

        # No edge for longer than the stale window => the tacho is not reporting. Zero it rather
        # than holding the last good value: a stale-but-plausible readout is what made the original
        # fault invisible, and the high-RPM alarm compares against this number.
        #
        # The reference point is the last successful edge, OR t=0 if there has never been one —
        # deliberately the SAME rule for "never measured yet" as for "was measuring, then went
        # silent". A tacho that hasn't produced a single pulse in the first TACHO_STALE_SEC of a
        # recording is exactly as untrustworthy as one that stops partway through; treating
        # "just started, still warming up" as an instant confirmed fault (the previous behaviour —
        # this branch used to require `_last_edge_t is not None`, so a never-measured tacho was
        # `_tacho_ok = False` from the very first chunk) raised a spurious alarm on every single
        # healthy nidaq recording.
        reference_t = self._last_edge_t if self._last_edge_t is not None else 0.0
        if n and float(t[-1]) - reference_t > self.TACHO_STALE_SEC:
            self._tacho_ok = False
            self._last_rpm = 0.0
            rpm[:] = 0.0
        return rpm

    def process(self, t: np.ndarray, axes: dict[str, np.ndarray], tacho: np.ndarray):
        """Returns (points: (k,5) float32 [x,y,cx,cy,cz], mean_rpm) for the NEW samples in this
        chunk. All three axis forces stream with every point — not just cfg.axis — so the client
        can switch the FRM colour axis at any time and instantly recolour the whole accumulated
        spiral, live points included, rather than only points drawn after the switch."""
        n = t.size
        rpm = self._rpm_for_chunk(t, tacho)
        if not self._active:
            # pre-cut: no spiral yet
            return np.empty((0, 5), dtype=np.float32), self._last_rpm, self._tacho_ok
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
        stride = max(1, n // self.max_pts)
        pts = np.empty((x[::stride].size, 5), dtype=np.float32)
        pts[:, 0] = x[::stride]
        pts[:, 1] = y[::stride]
        pts[:, 2] = axes["Fx"][::stride]
        pts[:, 3] = axes["Fy"][::stride]
        pts[:, 4] = axes["Fz"][::stride]
        return pts, self._last_rpm, self._tacho_ok
