"""NidaqSource — real NI-DAQ continuous acquisition (slice 2b), following the MATLAB app's method
(a continuous voltage AI task over the 8 Kistler dyno channels + tacho, read in chunks). Implements
the same AcquisitionSource contract as SimSource/ReplaySource, so the whole downstream pipeline is
unchanged — only the source swaps.

Built from the MATLAB `ABetterFactoryPlusApp` acquisition path + the nidaqmx docs. It is UNIT-TESTED
with a fake task/reader; it must be VALIDATED ON THE RIG (a working NI-DAQmx runtime + the dynamometer
or an NI-MAX simulated device) — this dev machine has no functional DAQmx runtime.

nidaqmx is imported lazily (only when a real task is built), so the backend runs fine without the NI
driver for the sim/replay paths.
"""
from __future__ import annotations

import threading
from typing import Optional

import numpy as np

from ..config import DEFAULT_NIDAQ_CHANNELS, RecordConfig, SIGNAL_CHANNELS


class NidaqUnavailable(Exception):
    """NI-DAQmx runtime / python package not available on this host."""


def _import_nidaqmx():
    try:
        import nidaqmx  # noqa: WPS433
        from nidaqmx import constants  # noqa: WPS433
        from nidaqmx.stream_readers import AnalogMultiChannelReader  # noqa: WPS433
        return nidaqmx, constants, AnalogMultiChannelReader
    except Exception as e:  # ImportError, or DAQmx DLL load failure
        raise NidaqUnavailable(f"NI-DAQmx not available: {e}") from e


def nidaq_available() -> bool:
    """True if the nidaqmx package + DAQmx runtime can be imported (does not prove a device exists)."""
    try:
        _import_nidaqmx()
        return True
    except NidaqUnavailable:
        return False


class NidaqSource:
    def __init__(self, cfg: RecordConfig, physical_channels: Optional[list[str]] = None,
                 chunk_sec: float = 0.05, _task=None, _reader=None):
        self.channels = list(SIGNAL_CHANNELS)
        self.rate = float(cfg.sample_rate)
        self.physical = list(physical_channels) if physical_channels else list(DEFAULT_NIDAQ_CHANNELS)
        if len(self.physical) != len(self.channels):
            raise ValueError(f"expected {len(self.channels)} NI-DAQ channels, got {len(self.physical)}")
        self.chunk = max(1, int(round(self.rate * chunk_sec)))
        # Injected for tests; built from nidaqmx in start() otherwise.
        self._task = _task
        self._reader = _reader
        self._buf = np.zeros((len(self.channels), self.chunk), dtype=np.float64)
        self._i = 0
        self._stop = threading.Event()

    def start(self) -> None:
        self._stop.clear()
        self._i = 0
        if self._task is None:
            nidaqmx, constants, ReaderCls = _import_nidaqmx()
            task = nidaqmx.Task()
            for ch in self.physical:
                task.ai_channels.add_ai_voltage_chan(ch)
            # Continuous hardware-timed sampling at the configured rate; a generous buffer avoids
            # overruns while the consumer keeps up.
            task.timing.cfg_samp_clk_timing(
                self.rate,
                sample_mode=constants.AcquisitionType.CONTINUOUS,
                samps_per_chan=max(self.chunk * 8, 100_000),
            )
            self._reader = ReaderCls(task.in_stream)
            self._task = task
        self._task.start()

    def read(self) -> Optional[tuple[np.ndarray, np.ndarray]]:
        if self._stop.is_set():
            return None
        try:
            # Blocking read of one chunk (hardware-paced). Reader fills (n_channels, chunk).
            self._reader.read_many_sample(self._buf, number_of_samples_per_channel=self.chunk, timeout=10.0)
        except Exception:
            # A stop() during a blocking read aborts the task; treat as end-of-stream.
            if self._stop.is_set():
                return None
            raise
        n = self.chunk
        idx = np.arange(self._i, self._i + n)
        self._i += n
        t = idx / self.rate
        return t, self._buf.T.copy()

    def stop(self) -> None:
        self._stop.set()
        task = self._task
        if task is not None:
            try:
                task.stop()
                task.close()
            except Exception:
                pass
            self._task = None
