"""Tests for the bug-report relay: config gating, token caching, issue creation."""

import httpx
import pytest
from fastapi.testclient import TestClient

import server as srv


@pytest.fixture(autouse=True)
def _reset_cache():
    srv._token_cache.token = ""
    srv._token_cache.expires_at = 0.0
    yield


@pytest.fixture
def client():
    return TestClient(srv.app)


def test_health_reports_unconfigured_by_default(client, monkeypatch):
    monkeypatch.delenv("GITHUB_APP_ID", raising=False)
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["configured"] is False


def test_report_fails_closed_when_not_configured(client, monkeypatch):
    monkeypatch.delenv("GITHUB_APP_ID", raising=False)
    r = client.post("/report", json={"title": "t", "body": "b"})
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is False
    assert "not configured" in data["reason"]


def test_report_requires_title(client, monkeypatch):
    monkeypatch.setattr(srv, "configured", lambda: True)
    r = client.post("/report", json={"title": "  ", "body": "b"})
    assert r.json() == {"ok": False, "reason": "A title is required."}


def test_report_creates_issue(client, monkeypatch):
    monkeypatch.setattr(srv, "configured", lambda: True)

    async def fake_get_token(self):
        return "installation-token"

    monkeypatch.setattr(srv._TokenCache, "get", fake_get_token)

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Bearer installation-token"
        return httpx.Response(201, json={"html_url": "https://github.com/x/y/issues/1", "number": 1})

    real_async_client = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: real_async_client(transport=httpx.MockTransport(handler), **{k: v for k, v in kw.items() if k != "transport"}))

    r = client.post("/report", json={"title": "Bug", "body": "Body text", "labels": ["force-app"]})
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    assert data["url"] == "https://github.com/x/y/issues/1"
    assert data["number"] == 1


def test_report_surfaces_github_rejection(client, monkeypatch):
    monkeypatch.setattr(srv, "configured", lambda: True)

    async def fake_get_token(self):
        return "installation-token"

    monkeypatch.setattr(srv._TokenCache, "get", fake_get_token)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(422, json={"message": "Validation failed"})

    real_async_client = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: real_async_client(transport=httpx.MockTransport(handler), **{k: v for k, v in kw.items() if k != "transport"}))

    r = client.post("/report", json={"title": "Bug", "body": "Body text"})
    data = r.json()
    assert data["ok"] is False
    assert "422" in data["reason"]
    assert "Validation failed" in data["reason"]
