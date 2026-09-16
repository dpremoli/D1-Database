"""#33: writing to the amp's live hardware state (mode, ranges, calibration, or rebuilding the amp
client entirely) must be refused while a recording is in progress -- the amp's analog outputs feed
straight into the NI-DAQ channels a live capture is sampling, so any of these mid-recording would
corrupt the in-progress capture, not just the next one.
"""

from fastapi.testclient import TestClient

import app.main as main
from app.main import app as fastapi_app


class _StubSession:
    id = "20260101-000000-abc123"
    state = "recording"


def test_labamp_mode_refused_while_recording(monkeypatch, tmp_path):
    monkeypatch.setattr(main, "CAPTURES_ROOT", str(tmp_path))
    main._rebuild_labamp()
    monkeypatch.setattr(main, "_session", _StubSession())
    with TestClient(fastapi_app) as client:
        r = client.post("/labamp/mode", json={"mode": "RESET"})
        assert r.status_code == 409


def test_labamp_config_refused_while_recording(monkeypatch, tmp_path):
    monkeypatch.setattr(main, "CAPTURES_ROOT", str(tmp_path))
    main._rebuild_labamp()
    monkeypatch.setattr(main, "_session", _StubSession())
    with TestClient(fastapi_app) as client:
        r = client.post("/labamp/config", json={"channels": 8})
        assert r.status_code == 409


def test_labamp_autorange_apply_refused_while_recording(monkeypatch, tmp_path):
    monkeypatch.setattr(main, "CAPTURES_ROOT", str(tmp_path))
    main._rebuild_labamp()
    monkeypatch.setattr(main, "_session", _StubSession())
    with TestClient(fastapi_app) as client:
        r = client.post("/labamp/autorange/apply", json={"headroom": 1.5})
        assert r.status_code == 409


def test_labamp_autorange_converge_apply_refused_while_recording(monkeypatch, tmp_path):
    monkeypatch.setattr(main, "CAPTURES_ROOT", str(tmp_path))
    main._rebuild_labamp()
    monkeypatch.setattr(main, "_session", _StubSession())
    with TestClient(fastapi_app) as client:
        r = client.post(
            "/labamp/autorange/converge",
            json={"peaks": [40] * 8, "apply": True},
        )
        assert r.status_code == 409


def test_labamp_autorange_converge_preview_still_allowed_while_recording(monkeypatch, tmp_path):
    # Computing recommendations without writing them to the amp is pure math -- no live-hardware
    # write happens, so this must stay usable mid-recording (e.g. previewing the next cut's ranges).
    monkeypatch.setattr(main, "CAPTURES_ROOT", str(tmp_path))
    main._rebuild_labamp()
    monkeypatch.setattr(main, "_session", _StubSession())
    with TestClient(fastapi_app) as client:
        r = client.post(
            "/labamp/autorange/converge",
            json={"peaks": [40] * 8},
        )
        assert r.status_code == 200
        assert r.json()["applied"] is False


def test_labamp_sensors_write_refused_while_recording(monkeypatch, tmp_path):
    monkeypatch.setattr(main, "CAPTURES_ROOT", str(tmp_path))
    main._rebuild_labamp()
    monkeypatch.setattr(main, "_session", _StubSession())
    with TestClient(fastapi_app) as client:
        r = client.post(
            "/labamp/sensors/write",
            json={"updates": [{"channel": 1, "sensitivity": 10.0}]},
        )
        assert r.status_code == 409


def test_labamp_writes_still_allowed_when_idle(monkeypatch, tmp_path):
    monkeypatch.setattr(main, "CAPTURES_ROOT", str(tmp_path))
    main._rebuild_labamp()
    with TestClient(fastapi_app) as client:
        r = client.post("/labamp/mode", json={"mode": "RESET"})
        assert r.status_code == 200
