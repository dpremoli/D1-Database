"""Stream-1 review nits: /labamp/config validates channels and mode; the Doctor guards a
client-supplied directus_url like the filter/octree URLs."""

import pytest
from fastapi.testclient import TestClient

import app.main as main
from app.main import app as fastapi_app


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setattr(main, "CAPTURES_ROOT", str(tmp_path))
    monkeypatch.setattr(main, "_session", None)
    with TestClient(fastapi_app) as c:
        yield c


@pytest.mark.parametrize("channels", [0, -1, 65, "8", "abc", 8.5, None, True, [8], {"n": 8}])
def test_labamp_config_rejects_bad_channels(client, channels):
    before = dict(main._labamp_cfg)
    r = client.post("/labamp/config", json={"channels": channels})
    assert r.status_code == 400, r.text
    assert main._labamp_cfg == before  # nothing persisted


@pytest.mark.parametrize("mode", ["MOCK", "demo", "", None, 1, ["real"]])
def test_labamp_config_rejects_bad_mode(client, mode):
    before = dict(main._labamp_cfg)
    r = client.post("/labamp/config", json={"mode": mode})
    assert r.status_code == 400, r.text
    assert main._labamp_cfg == before


def test_labamp_config_a_bad_field_saves_none_of_the_request(client):
    before = dict(main._labamp_cfg)
    r = client.post("/labamp/config", json={"channels": 4, "mode": "bogus"})
    assert r.status_code == 400
    assert main._labamp_cfg == before


def test_labamp_config_accepts_valid_values(client):
    r = client.post("/labamp/config", json={"channels": 4, "mode": "mock"})
    assert r.status_code == 200
    assert r.json()["channels"] == 4 and r.json()["mode"] == "mock"
    r = client.post("/labamp/config", json={"channels": 8})
    assert r.status_code == 200


@pytest.mark.parametrize(
    "url", ["http://169.254.169.254/latest/meta-data", "file:///etc/passwd", "ftp://x/", "http://"]
)
def test_doctor_does_not_probe_a_disallowed_directus_url(client, url):
    r = client.post("/health/doctor", json={"directus_url": url})
    assert r.status_code == 200, r.text
    f = next(x for x in r.json()["findings"] if x["service"] == "Directus")
    assert f["status"] == "fail"
    assert "invalid or not allowed" in f["diagnosis"]
