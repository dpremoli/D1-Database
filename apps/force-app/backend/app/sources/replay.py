"""ReplaySource — stream a REAL recorded cut (a D1LC live_cache.bin) through the live pipeline as
if it were being captured now. It reconstructs the NI-DAQ's 9-channel raw layout from the cache's
summed axes + rpm (splits Fx/Fy/Fz back across their sub-channels, synthesises a tacho pulse train
from the per-sample rpm), so it satisfies the same AcquisitionSource contract as SimSource and
everything downstream is unchanged. Great as a real-data test / demo of the acquisition path.
"""
from __future__ import annotations

import threading
import time
from typing import Optional

import numpy as np

from ..config import SIGNAL_CHANNELS
from ..d1lc import parse_d1lc


class ReplaySource:
    def __init__(self, cache_bytes: bytes, ppr: int = 1, realtime: bool = True, speed: float = 1.0,
                 chunk_sec: float = 0.02):
        c = parse_d1lc(cache_bytes)
        self.channels = list(SIGNAL_CHANNELS)
        self.rate = float(c["fs"]) if c["fs"] > 0 else 1000.0
        self.feed = float(c["feed"])
        self.diam = float(c["diam"])
        self.ppr = max(1, int(ppr))
        # speed>1 fast-forwards the replay (a real cut may be minutes long); speed<=0 = as-fast-as-
        # possible. realtime=False also disables pacing (used by tests).
        self.realtime = realtime and speed > 0
        self.speed = speed if speed > 0 else 1.0
        self.chunk = max(1, int(round(self.rate * chunk_sec)))
        self.total = int(c["t"].size)

        # Reconstruct the 9 raw channels (n, 9) in SIGNAL_CHANNELS order.
        n = self.total
        data = np.zeros((n, len(self.channels)), dtype=np.float64)
        col = {name: i for i, name in enumerate(self.channels)}
        data[:, col["Fx1"]] = data[:, col["Fx2"]] = c["fx"] / 2.0
        data[:, col["Fy1"]] = data[:, col["Fy2"]] = c["fy"] / 2.0
        for p in ("Fz1", "Fz2", "Fz3", "Fz4"):
            data[:, col[p]] = c["fz"] / 4.0
        # Synthesise a tacho pulse train from the per-sample rpm: phase winds at rpm·ppr/60,
        # emit a short pulse each cycle. Downstream rpm_from_tacho recovers ~the same rpm.
        dt = 1.0 / self.rate
        phase = np.cumsum(np.clip(c["rpm"], 0, None) * self.ppr / 60.0 * dt)
        data[:, col["Tacho"]] = ((phase % 1.0) < 0.15).astype(np.float64) * 5.0
        self._data = data
        self._t = c["t"].astype(np.float64)

        self._i = 0
        self._t0 = 0.0
        self._stop = threading.Event()

    def start(self) -> None:
        self._t0 = time.perf_counter()
        self._i = 0
        self._stop.clear()

    def stop(self) -> None:
        self._stop.set()

    def read(self) -> Optional[tuple[np.ndarray, np.ndarray]]:
        if self._stop.is_set() or self._i >= self.total:
            return None
        n = min(self.chunk, self.total - self._i)
        # Re-base time to start at 0 so live readouts read elapsed seconds.
        t = (self._t[self._i:self._i + n] - self._t[0])
        data = self._data[self._i:self._i + n]
        self._i += n
        if self.realtime:
            target = self._t0 + float(t[-1]) / self.speed
            dt = target - time.perf_counter()
            if dt > 0:
                time.sleep(min(dt, 0.1))
        return t, data
