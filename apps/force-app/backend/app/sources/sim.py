"""SimSource — a synthetic turning cut with the same 9-channel raw layout as the NI-DAQ.

It emits fixed-size chunks paced to wall-clock so the stream feels live. The force profile is
air-cut → ramp-up → steady cut (mean per axis + gaussian noise + a tooth-passing ripple so the FRM
spiral shows structure) → ramp-down. The tacho is a real pulse train at rpm·ppr/60, so the
downstream rpm-from-tacho + FRM path is exercised exactly as it will be with real hardware.

Each summed axis is split evenly across its sub-channels (Fx→Fx1,Fx2; Fz→Fz1..Fz4) so summing
reconstructs the intended axis force.
"""

from __future__ import annotations

import threading
import time

import numpy as np

from ..config import SIGNAL_CHANNELS, RecordConfig


class SimSource:
    def __init__(self, cfg: RecordConfig, realtime: bool = True, chunk_sec: float = 0.02):
        self.cfg = cfg
        self.channels = list(SIGNAL_CHANNELS)
        self.rate = float(cfg.sample_rate)
        self.realtime = realtime
        self.chunk = max(1, int(round(self.rate * chunk_sec)))
        self.total = int(round(self.rate * cfg.duration_sec))
        self._i = 0
        self._t0 = 0.0
        self._stop = threading.Event()
        self._rng = np.random.default_rng(12345)
        # Phase boundaries (fractions of the run): air, ramp-up, steady, ramp-down.
        self._air, self._up, self._down = 0.05, 0.12, 0.85

    def start(self) -> None:
        self._t0 = time.perf_counter()
        self._i = 0
        self._stop.clear()

    def stop(self) -> None:
        self._stop.set()

    def _envelope(self, frac: np.ndarray) -> np.ndarray:
        """0 during air, linear ramp up, 1 in steady, linear ramp down."""
        e = np.ones_like(frac)
        e = np.where(frac < self._air, 0.0, e)
        m = (frac >= self._air) & (frac < self._up)
        e = np.where(m, (frac - self._air) / max(1e-9, self._up - self._air), e)
        m = frac >= self._down
        e = np.where(m, np.clip((1.0 - frac) / max(1e-9, 1.0 - self._down), 0.0, 1.0), e)
        return e

    def read(self) -> tuple[np.ndarray, np.ndarray] | None:
        if self._stop.is_set() or self._i >= self.total:
            return None
        n = min(self.chunk, self.total - self._i)
        idx = np.arange(self._i, self._i + n)
        t = idx / self.rate
        frac = idx / max(1, self.total)
        env = self._envelope(frac)

        # Tooth-passing ripple gives the spiral radial structure; a slow drift adds realism.
        rev_phase = 2.0 * np.pi * (self.cfg.rpm / 60.0) * t
        ripple = 0.15 * np.sin(4.0 * rev_phase)
        means = {"Fx": self.cfg.mean_fx, "Fy": self.cfg.mean_fy, "Fz": self.cfg.mean_fz}
        data = np.zeros((n, len(self.channels)), dtype=np.float64)
        col = {name: i for i, name in enumerate(self.channels)}
        for axis, parts in (
            ("Fx", ["Fx1", "Fx2"]),
            ("Fy", ["Fy1", "Fy2"]),
            ("Fz", ["Fz1", "Fz2", "Fz3", "Fz4"]),
        ):
            axis_force = (
                env * means[axis] * (1.0 + ripple) + self._rng.normal(0, self.cfg.noise, n) * env
            )
            share = axis_force / len(parts)
            for p in parts:
                data[:, col[p]] = share
        # Tacho: a 0/1 pulse train at rpm·ppr/60 (short high duty per pulse).
        pulse_f = self.cfg.rpm * self.cfg.ppr / 60.0
        phase = (pulse_f * t) % 1.0
        data[:, col["Tacho"]] = (phase < 0.15).astype(np.float64) * 5.0  # 0..5 V pulses

        self._i += n
        if self.realtime:
            target = self._t0 + (self._i / self.rate)
            dt = target - time.perf_counter()
            if dt > 0:
                # Cap sleeps so stop() stays responsive.
                time.sleep(min(dt, 0.1))
        return t, data
