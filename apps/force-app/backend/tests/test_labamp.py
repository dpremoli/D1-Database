"""LabAmp client (real, against a mocked transport) + MockLabAmp behaviour."""

import json

import httpx
import pytest

from app.labamp import LabAmpClient, LabAmpError, MockLabAmp


def _handler(request: httpx.Request) -> httpx.Response:
    path = request.url.path
    body = json.loads(request.content or b"{}")
    if path == "/api/$/operationMode/set":
        assert body["mode"] in ("MEASURE", "RESET")
        return httpx.Response(200, json={"result": 0, "data": {}})
    if path == "/api/$/operationMode/get":
        return httpx.Response(200, json={"result": 0, "data": {"mode": "MEASURE"}})
    if path == "/api/param/get":
        params = body["params"]
        return httpx.Response(
            200,
            json={
                "result": 0,
                "data": {"params": [{"name": p, "value": p.split("/")[-1]} for p in params]},
            },
        )
    if path == "/api/param/export":
        return httpx.Response(200, json={"result": 0, "data": {"device": "5167A81"}})
    if path == "/api/$/signal/get":
        return httpx.Response(
            200, json={"result": 0, "data": {"items": [{"channel": 1, "live": [1.0]}]}}
        )
    return httpx.Response(200, json={"result": 7, "data": {}})  # unknown -> error result


def _client() -> LabAmpClient:
    return LabAmpClient("http://169.254.143.59", transport=httpx.MockTransport(_handler))


def test_operation_mode_roundtrip():
    c = _client()
    c.set_operation_mode("MEASURE")  # no raise
    assert c.get_operation_mode() == "MEASURE"
    assert c.ping() is True


def test_bad_mode_rejected():
    with pytest.raises(LabAmpError):
        _client().set_operation_mode("BOGUS")


def test_error_result_raises():
    c = _client()
    with pytest.raises(LabAmpError):
        c._post("/api/unknown", {})  # handler returns result=7


def test_sensor_table_parsing():
    rows = _client().sensor_table(8)
    assert len(rows) == 8
    assert rows[0]["channel"] == 1
    # value echoes the leaf name in the mock handler
    assert rows[0]["name"] == "name" and rows[0]["range"] == "range"


def test_unreachable_ping_false():
    def boom(request):
        raise httpx.ConnectError("no route", request=request)

    c = LabAmpClient("http://10.255.255.1", transport=httpx.MockTransport(boom))
    assert c.ping() is False


def test_amp_url_validation():
    from fastapi import HTTPException

    from app.main import _validate_amp_url

    # link-local amp address is allowed (that's the legitimate target)
    assert _validate_amp_url("http://169.254.143.59") == "http://169.254.143.59"
    assert _validate_amp_url("http://192.168.1.50:80").startswith("http://")
    for bad in (
        "file:///etc/passwd",
        "gopher://x",
        "http://",
        "http://169.254.169.254",
        "http://metadata.google.internal",
    ):
        with pytest.raises(HTTPException):
            _validate_amp_url(bad)


def test_mock_labamp():
    m = MockLabAmp()
    assert m.mock is True and m.ping() is True
    assert m.get_operation_mode() == "RESET"
    m.set_operation_mode("MEASURE")
    assert m.get_operation_mode() == "MEASURE"
    rows = m.sensor_table(8)
    assert len(rows) == 8 and rows[4]["physicalQuantity"] == "Force"
    assert "device" in m.export_params()
    assert m.signal_get([1, 2])[0]["channel"] == 1
