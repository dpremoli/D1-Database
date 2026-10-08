"""#184: POST /record/cut-start starts the live FRM by hand when the causal cut detector never
fires. It sets the origin at the latest sample through the detector's own path, refuses (409) when
idle or already started, and the source lands in summary.json."""

from __future__ import annotations

import json
import time

import pytest
from fastapi.testclient import TestClient

from app import main
from app.main import app

# A cut the detector cannot see: no force at all, and an absolute floor nothing reaches.
NO_FORCE = {
    "sample_rate": 2000,
    "duration_sec": 6.0,
    "rpm": 1200,
    "mean_fx": 0.0,
    "mean_fy": 0.0,
    "mean_fz": 0.0,
    "cut_detect_force": 1e6,
}
# A cut it does see (the sim default force), so the detector fires on its own.
WITH_FORCE = {"sample_rate": 2000, "duration_sec": 3.0, "rpm": 1200, "cut_detect_force": 50.0}


class Tap:
    """Stands in for the WS broadcaster: keeps the control messages the clients would get."""

    def __init__(self):
        self.control: list[dict] = []

    def publish(self, msg):
        if isinstance(msg, str):
            self.control.append(json.loads(msg))


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "CAPTURES_ROOT", str(tmp_path))
    monkeypatch.setattr(main, "_session", None)
    tap = Tap()
    with TestClient(app) as c:
        monkeypatch.setattr(main, "_broadcaster", tap)  # after the lifespan builds the real one
        c.tap = tap
        yield c
        if main._session is not None and main._session.state == "recording":
            c.post("/record/stop")
            main._session.join_finalize(30)


def _wait(pred, timeout=10.0):
    end = time.time() + timeout
    while time.time() < end:
        if pred():
            return True
        time.sleep(0.05)
    return False


def _recording(client, body):
    assert client.post("/record/start", json=body).status_code == 200
    assert _wait(lambda: client.get("/record/status").json()["n_total"] > 400)


def test_409_when_nothing_is_recording(client):
    r = client.post("/record/cut-start")
    assert r.status_code == 409
    assert "no recording" in r.json()["detail"]


def test_manual_mark_sets_the_origin_and_the_frm_and_stream_see_it(client):
    _recording(client, NO_FORCE)
    s = main._session
    assert client.get("/record/status").json()["cut_start_sec"] is None
    assert s.frm._active is False  # frm_from_cut: held at the origin, waiting
    n_before = s.n_total

    r = client.post("/record/cut-start")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["source"] == "manual"
    assert body["sample"] >= n_before - 1  # at the latest acquired sample, not the beginning
    assert s.frm._active is True  # the FRM integrator was re-origined, as the detector does
    assert s.cut.detected is True  # and the detector will not fire a second origin
    st = client.get("/record/status").json()
    assert st["cut_start_sec"] == body["t"] and st["cut_start_source"] == "manual"
    cutstart = [m for m in client.tap.control if m.get("type") == "cutstart"]
    assert cutstart == [{"type": "cutstart", "t": body["t"], "source": "manual"}]


def test_409_when_a_manual_start_is_already_set(client):
    _recording(client, NO_FORCE)
    first = client.post("/record/cut-start").json()
    r = client.post("/record/cut-start")
    assert r.status_code == 409
    assert "already set" in r.json()["detail"]
    assert main._session.cut_started_t == first["t"]  # not re-origined


def test_409_when_the_detector_already_fired(client):
    _recording(client, WITH_FORCE)
    assert _wait(lambda: client.get("/record/status").json()["cut_start_sec"] is not None)
    t_auto = main._session.cut_started_t
    assert main._session.cut_start_source == "auto"
    r = client.post("/record/cut-start")
    assert r.status_code == 409
    assert main._session.cut_started_t == t_auto
    assert main._session.cut_start_source == "auto"


def _finish(client):
    assert client.post("/record/stop").status_code == 200
    s = main._session
    s.join_finalize(30)
    assert s.state == "done", s.error
    return json.load(open(f"{s.dir}/summary.json"))


def test_summary_json_carries_the_manual_source(client):
    _recording(client, NO_FORCE)
    body = client.post("/record/cut-start").json()
    summ = _finish(client)
    assert summ["cut_start_source"] == "manual"
    assert summ["cut_start_sample"] == body["sample"]
    assert summ["cut_start_sec"] == body["t"]


def test_summary_json_carries_the_auto_source(client):
    _recording(client, WITH_FORCE)
    assert _wait(lambda: client.get("/record/status").json()["cut_start_sec"] is not None)
    summ = _finish(client)
    assert summ["cut_start_source"] == "auto"
    assert summ["cut_start_sample"] > 0 and summ["cut_start_sec"] > 0


def test_summary_json_source_is_null_when_the_cut_never_started(client):
    _recording(client, NO_FORCE)
    summ = _finish(client)
    assert summ["cut_start_source"] is None and summ["cut_start_sample"] is None
