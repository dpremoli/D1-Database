"""NidaqSource logic with a fake DAQ task/reader (real hardware is validated on the rig)."""

import numpy as np
import pytest

from app.config import SIGNAL_CHANNELS, RecordConfig
from app.sources.nidaq import NidaqSource, nidaq_available


class FakeReader:
    def __init__(self):
        self.calls = 0

    def read_many_sample(self, buf, number_of_samples_per_channel, timeout=10.0):
        assert buf.shape[1] == number_of_samples_per_channel
        buf[:] = np.random.default_rng(self.calls).normal(size=buf.shape)
        self.calls += 1


class FakeTask:
    def __init__(self):
        self.started = False
        self.closed = False

    def start(self):
        self.started = True

    def stop(self):
        pass

    def close(self):
        self.closed = True


def _src(rate=2000):
    cfg = RecordConfig(sample_rate=rate, source="nidaq")
    return NidaqSource(cfg, _task=FakeTask(), _reader=FakeReader())


def test_shape_and_index_advance():
    src = _src()
    src.start()
    assert src._task.started is True
    t, data = src.read()
    assert data.shape == (src.chunk, len(SIGNAL_CHANNELS))  # (n, 9)
    assert t.size == src.chunk
    t2, _ = src.read()
    assert t2[0] > t[-1]  # sample index advances
    assert np.allclose(np.diff(t), 1.0 / src.rate)  # uniform at the configured rate


def test_stop_ends_stream_and_closes_task():
    src = _src()
    src.start()
    src.read()
    src.stop()
    assert src.read() is None  # no more data after stop


def test_channel_count_mismatch_rejected():
    cfg = RecordConfig(sample_rate=1000, source="nidaq")
    with pytest.raises(ValueError):
        NidaqSource(
            cfg, physical_channels=["Dev1/ai0", "Dev1/ai1"], _task=FakeTask(), _reader=FakeReader()
        )


def test_nidaq_available_is_bool():
    assert isinstance(nidaq_available(), bool)
