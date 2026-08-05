"""API endpoint tests for recovery, backup config, and storage features."""

import json
import os
import time

import numpy as np
from fastapi.testclient import TestClient

import app.main as main
from app.d1rw import RawWriter
from app.main import app as fastapi_app
from app.recovery import write_manifest
from app.config import RecordConfig


def _make_raw(capture_dir: str, n_rows: int = 200, rate: float = 2000.0) -> None:
    os.makedirs(capture_dir, exist_ok=True)
    raw_path = os.path.join(capture_dir, "raw.d1raw")
    w = RawWriter(raw_path, n_cols=10, rate=rate, start_unix=1700000000.0)
    rng = np.random.default_rng(42)
    for i in range(0, n_rows, 50):
        n = min(50, n_rows - i)
        t = np.arange(i, i + n, dtype=np.float64) / rate
        data = rng.normal(size=(n, 9)).astype(np.float64)
        w.append(t, data)
    w.close()


# ---- Recovery API ----

def test_recovery_check_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "CAPTURES_ROOT", str(tmp_path))
    with TestClient(fastapi_app) as client:
        r = client.get("/recovery/check")
        assert r.status_code == 200
        assert r.json()["incomplete"] == []


def test_recovery_check_finds_incomplete(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "CAPTURES_ROOT", str(tmp_path))
    sid = "20240101-120000-abc123"
    _make_raw(str(tmp_path / sid), n_rows=300)

    with TestClient(fastapi_app) as client:
        r = client.get("/recovery/check")
        assert r.status_code == 200
        items = r.json()["incomplete"]
        assert len(items) == 1
        assert items[0]["id"] == sid
        assert items[0]["raw"]["n_rows"] == 300


def test_recovery_recover_success(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "CAPTURES_ROOT", str(tmp_path))
    sid = "20240101-120000-rec001"
    d = str(tmp_path / sid)
    _make_raw(d, n_rows=500)
    cfg = RecordConfig(sample_name="RECOVER-API", sample_rate=2000)
    write_manifest(d, "recording", cfg)

    with TestClient(fastapi_app) as client:
        r = client.post(f"/recovery/recover/{sid}")
        assert r.status_code == 200
        data = r.json()
        assert data["recovered"] is True
        assert data["summary"]["n"] == 500
        assert data["summary"]["sample_name"] == "RECOVER-API"

        # Now should not appear in incomplete list
        r2 = client.get("/recovery/check")
        assert len(r2.json()["incomplete"]) == 0


def test_recovery_recover_404_for_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "CAPTURES_ROOT", str(tmp_path))
    with TestClient(fastapi_app) as client:
        r = client.post("/recovery/recover/nonexistent-session")
        assert r.status_code == 404


def test_recovery_recover_400_for_already_finalized(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "CAPTURES_ROOT", str(tmp_path))
    sid = "20240101-120000-alrfin"
    d = str(tmp_path / sid)
    _make_raw(d, n_rows=100)
    with open(os.path.join(d, "summary.json"), "w") as f:
        json.dump({"n": 100}, f)

    with TestClient(fastapi_app) as client:
        r = client.post(f"/recovery/recover/{sid}")
        assert r.status_code == 400


def test_recovery_discard_success(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "CAPTURES_ROOT", str(tmp_path))
    sid = "20240101-120000-disc01"
    _make_raw(str(tmp_path / sid), n_rows=100)

    with TestClient(fastapi_app) as client:
        r = client.post(f"/recovery/discard/{sid}")
        assert r.status_code == 200
        assert r.json()["discarded"] is True
        assert not os.path.exists(str(tmp_path / sid))


def test_recovery_discard_404_for_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "CAPTURES_ROOT", str(tmp_path))
    with TestClient(fastapi_app) as client:
        r = client.post("/recovery/discard/ghost-session")
        assert r.status_code == 404


# ---- Manifest written during recording lifecycle ----

def test_session_writes_manifest_on_start_and_done(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "CAPTURES_ROOT", str(tmp_path))
    with TestClient(fastapi_app) as client:
        r = client.post("/record/start", json={"sample_rate": 2000, "duration_sec": 0.3})
        assert r.status_code == 200
        cid = r.json()["id"]

        # Manifest should exist immediately
        manifest_path = os.path.join(str(tmp_path), cid, "manifest.json")
        assert os.path.isfile(manifest_path)
        with open(manifest_path) as f:
            m = json.load(f)
        assert m["state"] in ("recording", "finalizing", "done")

        # Wait for completion
        for _ in range(100):
            st = client.get("/record/status").json()
            if st["state"] in ("done", "error"):
                break
            time.sleep(0.1)

        # Manifest updated to final state
        with open(manifest_path) as f:
            m = json.load(f)
        assert m["state"] == "done"


# ---- Backup config API ----

def test_backup_config_defaults(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "CAPTURES_ROOT", str(tmp_path))
    with TestClient(fastapi_app) as client:
        r = client.get("/backup/config")
        assert r.status_code == 200
        cfg = r.json()
        assert cfg["enabled"] is False
        assert cfg["server_url"] == ""


def test_backup_config_save_and_load(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "CAPTURES_ROOT", str(tmp_path))
    with TestClient(fastapi_app) as client:
        r = client.post("/backup/config", json={
            "enabled": True,
            "server_url": "http://backuphost:8210",
            "retention_hours": 24,
        })
        assert r.status_code == 200
        cfg = r.json()
        assert cfg["enabled"] is True
        assert cfg["server_url"] == "http://backuphost:8210"
        assert cfg["retention_hours"] == 24

        # Verify persisted
        r2 = client.get("/backup/config")
        cfg2 = r2.json()
        assert cfg2["enabled"] is True


def test_backup_status_no_active_session(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "CAPTURES_ROOT", str(tmp_path))
    with TestClient(fastapi_app) as client:
        r = client.get("/backup/status")
        assert r.status_code == 200
        data = r.json()
        assert data["active"] is None


# ---- Storage API ----

def test_storage_config_get(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "CAPTURES_ROOT", str(tmp_path))
    with TestClient(fastapi_app) as client:
        r = client.get("/storage/config")
        assert r.status_code == 200
        data = r.json()
        assert "free_gb" in data
        assert "total_gb" in data
        assert "captures_root" in data


def test_storage_drives_list(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "CAPTURES_ROOT", str(tmp_path))
    with TestClient(fastapi_app) as client:
        r = client.get("/storage/drives")
        assert r.status_code == 200
        data = r.json()
        assert "drives" in data
        assert "current" in data


# ---- Finalize file_sizes_mb ----

def test_finalize_includes_file_sizes(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "CAPTURES_ROOT", str(tmp_path))
    with TestClient(fastapi_app) as client:
        r = client.post("/record/start", json={"sample_rate": 2000, "duration_sec": 0.3})
        assert r.status_code == 200
        cid = r.json()["id"]

        for _ in range(100):
            st = client.get("/record/status").json()
            if st["state"] in ("done", "error"):
                break
            time.sleep(0.1)
        assert st["state"] == "done"

        summ = client.get(f"/captures/{cid}/summary").json()
        assert "file_sizes_mb" in summ
        assert "raw.d1raw" in summ["file_sizes_mb"]
        assert summ["file_sizes_mb"]["raw.d1raw"] > 0
