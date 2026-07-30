"""RecordingSession — owns one run's lifecycle: source → ring → consumers → live frames, then
finalize on stop/completion. State machine: idle → recording → finalizing → done (or error)."""
from __future__ import annotations

import json
import os
import threading
import time
import uuid
from typing import Optional

import numpy as np
from scipy import signal as ssig

from .acquisition.consumers import Decimator, FrmIntegrator
from .acquisition.ring import Ring
from .config import RecordConfig
from .d1rw import RawWriter
from .dsp import sum_axes, tacho_column
from .finalize import finalize
from .stream.broadcast import Broadcaster
from .stream.frame import encode_frame


class RecordingSession:
    def __init__(self, cfg: RecordConfig, captures_root: str, source,
                 broadcaster: Optional[Broadcaster] = None):
        self.cfg = cfg
        self.id = time.strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:6]
        self.dir = os.path.join(captures_root, self.id)
        os.makedirs(self.dir, exist_ok=True)
        self.broadcaster = broadcaster
        self.state = "idle"
        self.error: Optional[str] = None
        self.summary: Optional[dict] = None
        self.n_total = 0
        self.peaks = [0.0, 0.0, 0.0]
        self._t_last = 0.0

        self.source = source  # SimSource or ReplaySource (any AcquisitionSource)
        self.ring = Ring(maxsize=128)
        self.raw = RawWriter(os.path.join(self.dir, "raw.d1raw"),
                             n_cols=1 + len(self.source.channels), rate=self.source.rate,
                             start_unix=time.time())
        self.decimator = Decimator(bins=2)
        self.frm = FrmIntegrator(cfg)
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

        # Rolling window of the FRM axis (summed) for a live FFT, plus a wall-clock throttle.
        self._fft_axis = cfg.axis if cfg.axis in ("Fx", "Fy", "Fz") else "Fz"
        self._fft_buf = np.zeros(0, dtype=np.float64)
        self._fft_cap = int(max(2048, min(200_000, self.source.rate)))  # ~1 s, bounded
        self._fft_last = 0.0

    # ---- lifecycle ----
    def start(self) -> None:
        self.state = "recording"
        self._thread = threading.Thread(target=self._run, name=f"rec-{self.id}", daemon=True)
        self._thread.start()

    def stop(self, wait: bool = True, timeout: float = 30.0) -> None:
        self._stop.set()
        self.source.stop()
        if wait and self._thread:
            self._thread.join(timeout)

    # ---- worker ----
    def _run(self) -> None:
        consumer = threading.Thread(target=self._consume, name=f"rec-consume-{self.id}", daemon=True)
        try:
            self.source.start()
            consumer.start()
            while not self._stop.is_set():
                chunk = self.source.read()
                if chunk is None:
                    break
                if not self.ring.put(chunk[0], chunk[1], timeout=5.0):
                    self.error = "consumer overrun"
                    break
        except Exception as e:  # pragma: no cover - defensive
            self.error = f"acquisition error: {e}"
        finally:
            self.ring.close()
            consumer.join(timeout=10.0)
            self.raw.close()
            try:
                self.state = "finalizing"
                self.summary = finalize(self.dir, self.cfg)
                self.state = "error" if self.error else "done"
            except Exception as e:
                self.error = f"finalize error: {e}"
                self.state = "error"
            self._publish_control({"type": "done", "id": self.id, "state": self.state,
                                   "error": self.error, "summary": self.summary})

    def _consume(self) -> None:
        seq = 0
        while True:
            item = self.ring.get()
            if item is None:
                break
            t, data = item
            self.raw.append(t, data)                  # never dropped — source of truth
            axes = sum_axes(data)
            for i, ax in enumerate(("Fx", "Fy", "Fz")):
                self.peaks[i] = max(self.peaks[i], float(np.max(np.abs(axes[ax]))))
            trace = self.decimator.process(t, axes)
            pts, rpm = self.frm.process(t, axes, tacho_column(data))
            self.n_total += t.size
            self._t_last = float(t[-1])
            if self.broadcaster is not None:
                frame = encode_frame(seq, self._t_last, rpm, tuple(self.peaks), self.n_total, trace, pts)
                self.broadcaster.publish(frame)
            self._update_fft(axes)
            seq += 1

    def _update_fft(self, axes: dict) -> None:
        """Maintain a rolling window of the FRM axis and publish a Welch spectrum a few times a
        second (a JSON control message) for the live FFT view."""
        if self.broadcaster is None:
            return
        y = axes.get(self._fft_axis)
        if y is None:
            return
        self._fft_buf = np.concatenate([self._fft_buf, y])[-self._fft_cap:]
        now = time.perf_counter()
        if now - self._fft_last < 0.3 or self._fft_buf.size < 256:
            return
        self._fft_last = now
        fs = float(self.source.rate)
        nper = int(min(self._fft_buf.size, 4096))
        f, p = ssig.welch(self._fft_buf, fs=fs, nperseg=nper)
        amp = np.sqrt(p)
        step = max(1, f.size // 240)
        self._publish_control({"type": "fft", "axis": self._fft_axis,
                               "f": f[::step].round(2).tolist(), "amp": amp[::step].tolist()})

    def _publish_control(self, msg: dict) -> None:
        if self.broadcaster is not None:
            self.broadcaster.publish(json.dumps(msg))

    # ---- status ----
    def status(self) -> dict:
        return {
            "id": self.id, "state": self.state, "error": self.error,
            "elapsed_sec": round(self._t_last, 3), "n_total": self.n_total,
            "peaks": {"Fx": self.peaks[0], "Fy": self.peaks[1], "Fz": self.peaks[2]},
            "config": self.cfg.model_dump(),
        }
