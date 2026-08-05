"""Tests for the backup server: ingest flow, session listing, purge, health."""

import json
import os
import struct
import time

import pytest


def _make_header() -> bytes:
    """Create a minimal D1RW header."""
    head = struct.pack("<4sIIfd", b"D1RW", 1, 10, 2000.0, 1700000000.0)
    return head + b"\x00" * (32 - len(head))


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("BACKUP_STORAGE", str(tmp_path))
    monkeypatch.setenv("BACKUP_RETENTION_HOURS", "12")
    # Re-import after env is set
    import importlib
    import server as srv
    monkeypatch.setattr(srv, "STORAGE", str(tmp_path))
    monkeypatch.setattr(srv, "RETENTION_HOURS", 12.0)

    from fastapi.testclient import TestClient
    with TestClient(srv.app) as c:
        yield c


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    assert "disk_free_gb" in data


def test_ingest_start_chunk_finish(client, tmp_path):
    header = _make_header()

    # Start
    r = client.post("/ingest/start", json={
        "session_id": "test-001",
        "header_hex": header.hex(),
        "config": {"sample_name": "TEST"},
    })
    assert r.status_code == 200
    assert r.json()["ok"] is True

    # Send chunks
    chunk1 = os.urandom(400)  # 10 float32 rows
    r = client.post("/ingest/chunk", content=chunk1, headers={
        "X-Session-ID": "test-001",
        "Content-Type": "application/octet-stream",
    })
    assert r.status_code == 200
    assert r.json()["appended"] == 400

    chunk2 = os.urandom(200)
    r = client.post("/ingest/chunk", content=chunk2, headers={
        "X-Session-ID": "test-001",
        "Content-Type": "application/octet-stream",
    })
    assert r.status_code == 200

    # Finish
    r = client.post("/ingest/finish", json={"session_id": "test-001"})
    assert r.status_code == 200

    # Verify raw file
    raw_path = os.path.join(str(tmp_path), "test-001", "raw.d1rw")
    assert os.path.isfile(raw_path)
    data = open(raw_path, "rb").read()
    assert data[:4] == b"D1RW"
    assert len(data) == 32 + 400 + 200  # header + chunks


def test_ingest_chunk_without_start_returns_404(client):
    r = client.post("/ingest/chunk", content=b"\x00" * 100, headers={
        "X-Session-ID": "nonexistent",
        "Content-Type": "application/octet-stream",
    })
    assert r.status_code == 404


def test_ingest_chunk_without_session_header_returns_400(client):
    r = client.post("/ingest/chunk", content=b"\x00" * 100, headers={
        "Content-Type": "application/octet-stream",
    })
    assert r.status_code == 400


def test_sessions_list(client, tmp_path):
    header = _make_header()
    # Create two sessions
    for sid in ("sess-a", "sess-b"):
        client.post("/ingest/start", json={"session_id": sid, "header_hex": header.hex()})
        client.post("/ingest/chunk", content=os.urandom(400), headers={
            "X-Session-ID": sid, "Content-Type": "application/octet-stream"
        })

    r = client.get("/sessions")
    assert r.status_code == 200
    sessions = r.json()["sessions"]
    assert len(sessions) == 2
    ids = {s["id"] for s in sessions}
    assert "sess-a" in ids and "sess-b" in ids


def test_session_info(client, tmp_path):
    header = _make_header()
    client.post("/ingest/start", json={"session_id": "info-test", "header_hex": header.hex()})
    # Write 10 rows of 10 float32 columns = 400 bytes
    client.post("/ingest/chunk", content=os.urandom(400), headers={
        "X-Session-ID": "info-test", "Content-Type": "application/octet-stream"
    })
    client.post("/ingest/finish", json={"session_id": "info-test"})

    r = client.get("/sessions/info-test/info")
    assert r.status_code == 200
    info = r.json()
    assert info["id"] == "info-test"
    assert info["n_rows"] == 10
    assert info["rate"] == 2000.0
    assert info["state"] == "complete"


def test_session_raw_download(client, tmp_path):
    header = _make_header()
    client.post("/ingest/start", json={"session_id": "dl-test", "header_hex": header.hex()})
    chunk = os.urandom(800)
    client.post("/ingest/chunk", content=chunk, headers={
        "X-Session-ID": "dl-test", "Content-Type": "application/octet-stream"
    })

    r = client.get("/sessions/dl-test/raw")
    assert r.status_code == 200
    assert r.content[:4] == b"D1RW"
    assert len(r.content) == 32 + 800


def test_session_delete(client, tmp_path):
    header = _make_header()
    client.post("/ingest/start", json={"session_id": "del-test", "header_hex": header.hex()})

    r = client.delete("/sessions/del-test")
    assert r.status_code == 200
    assert r.json()["deleted"] is True

    r = client.get("/sessions/del-test/info")
    assert r.status_code == 404


def test_session_not_found(client):
    assert client.get("/sessions/ghost/info").status_code == 404
    assert client.get("/sessions/ghost/raw").status_code == 404
    assert client.delete("/sessions/ghost").status_code == 404


def test_purge_expired(client, tmp_path, monkeypatch):
    import server as srv
    monkeypatch.setattr(srv, "RETENTION_HOURS", 0.0001)  # ~0.36 seconds

    header = _make_header()
    client.post("/ingest/start", json={"session_id": "old-sess", "header_hex": header.hex()})

    # Backdate the meta
    meta_path = os.path.join(str(tmp_path), "old-sess", "meta.json")
    with open(meta_path) as f:
        meta = json.load(f)
    meta["updated_at"] = time.time() - 3600  # 1 hour ago
    with open(meta_path, "w") as f:
        json.dump(meta, f)

    srv._purge_expired()

    assert not os.path.exists(os.path.join(str(tmp_path), "old-sess"))
