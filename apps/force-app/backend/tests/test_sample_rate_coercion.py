"""#199: an NI 9234 only samples at 51,200 / n Hz and DAQmx moves any other request to the next
rate it can produce without an error. The capture is stamped with the configured rate, so
/record/start must settle on the rate really used before a session exists."""

import os
import types

import pytest
from fastapi.testclient import TestClient

import app.main as main
import app.sources.nidaq as nidaq_mod
from app import nidaq_enum
from app.config import DEFAULT_NIDAQ_CHANNELS, RecordConfig

from .test_clipping import _RailSource


class _Source(_RailSource):
    def __init__(self, cfg=None, physical_channels=None, extra_channels=None):
        super().__init__()
        self.rate = float(cfg.sample_rate)


def test_coerced_rate_problem():
    assert main.coerced_rate_problem(25_600, 25_600.0) is None
    assert main.coerced_rate_problem(25_000, None) is None  # nothing to ask: keep the request
    assert main.coerced_rate_problem(17_067, 51_200 / 3) is None  # the same rate, rounded
    problem = main.coerced_rate_problem(25_000, 25_600.0)
    assert problem["field"] == "sample_rate"
    assert problem["suggested"] == 25_600.0
    assert "25,000 Hz" in problem["message"] and "25,600 Hz" in problem["message"]


def test_no_daqmx_runtime_means_no_answer():
    assert nidaq_enum.coerced_sample_rate(list(DEFAULT_NIDAQ_CHANNELS), 25_000) is None
    assert nidaq_enum.coerced_sample_rate([], 25_000) is None


@pytest.fixture
def nidaq_client(monkeypatch, tmp_path):
    monkeypatch.setattr(nidaq_mod, "nidaq_available", lambda: True)
    monkeypatch.setattr(nidaq_mod, "NidaqSource", _Source)
    monkeypatch.setattr(main.nidaq_enum, "sample_rate_limits", lambda _c: {})
    monkeypatch.setattr(main, "CAPTURES_ROOT", str(tmp_path))
    monkeypatch.setattr(main, "_session", None)
    with TestClient(main.app) as client:
        yield client
    monkeypatch.setattr(main, "_session", None)


def _start(client, rate):
    body = {"source": "nidaq", "sample_rate": rate, "duration_sec": 0.3, "dyno_gains": [1.0] * 8}
    return client.post("/record/start", json=body)


def test_start_refuses_a_rate_the_driver_would_change(nidaq_client, monkeypatch, tmp_path):
    monkeypatch.setattr(main.nidaq_enum, "coerced_sample_rate", lambda _c, _r: 25_600.0)
    res = _start(nidaq_client, 25_000)
    assert res.status_code == 400
    detail = res.json()["detail"]
    assert (detail["field"], detail["suggested"]) == ("sample_rate", 25_600.0)
    assert main._session is None and os.listdir(tmp_path) == []  # nothing was created


def test_start_records_with_the_exact_hardware_rate(nidaq_client, monkeypatch):
    exact = 51_200 / 3
    monkeypatch.setattr(main.nidaq_enum, "coerced_sample_rate", lambda _c, _r: exact)
    res = _start(nidaq_client, 17_067)
    assert res.status_code == 200
    sess = main._session
    sess._thread.join(15)
    sess.join_finalize(30)
    assert sess.cfg.sample_rate == exact
    assert sess.summary["fs"] == pytest.approx(exact)


def test_start_keeps_the_request_when_the_driver_cannot_be_asked(nidaq_client, monkeypatch):
    monkeypatch.setattr(main.nidaq_enum, "coerced_sample_rate", lambda _c, _r: None)
    res = _start(nidaq_client, 1000)
    assert res.status_code == 200
    sess = main._session
    sess._thread.join(15)
    sess.join_finalize(30)
    assert sess.cfg.sample_rate == 1000


def test_source_refuses_to_start_at_a_rate_other_than_its_own(monkeypatch):
    closed = []

    class _Task:
        ai_channels = types.SimpleNamespace(add_ai_voltage_chan=lambda ch: None)
        in_stream = object()

        def __init__(self):
            self.timing = types.SimpleNamespace(
                cfg_samp_clk_timing=lambda *a, **k: None, samp_clk_rate=25_600.0
            )

        def start(self):
            raise AssertionError("must not start")

        def close(self):
            closed.append(True)

    fake = types.SimpleNamespace(Task=_Task)
    constants = types.SimpleNamespace(AcquisitionType=types.SimpleNamespace(CONTINUOUS=1))
    monkeypatch.setattr(nidaq_mod, "_import_nidaqmx", lambda: (fake, constants, lambda s: object()))
    src = nidaq_mod.NidaqSource(RecordConfig(sample_rate=25_000))
    with pytest.raises(ValueError, match="25,600.0 Hz, not the requested 25,000.0 Hz"):
        src.start()
    assert closed == [True]
