"""API endpoint tests for recovery, backup config, and storage features."""

import json
import os
import time

import numpy as np
import pytest
from fastapi.testclient import TestClient

import app.main as main
from app.config import RecordConfig
from app.d1rw import RawWriter
from app.main import app as fastapi_app
from app.recovery import write_manifest


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
    # The endpoint returns as soon as the delete is scheduled, not once it finishes (see
    # recovery_discard in main.py — a large raw.d1raw shouldn't hang the request), so the directory
    # removal is asserted with a short poll rather than immediately after the response.
    monkeypatch.setattr(main, "CAPTURES_ROOT", str(tmp_path))
    sid = "20240101-120000-disc01"
    _make_raw(str(tmp_path / sid), n_rows=100)

    with TestClient(fastapi_app) as client:
        r = client.post(f"/recovery/discard/{sid}")
        assert r.status_code == 200
        assert r.json()["discarded"] is True
        deadline = time.time() + 5
        while os.path.exists(str(tmp_path / sid)) and time.time() < deadline:
            time.sleep(0.05)
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
        r = client.post(
            "/backup/config",
            json={
                "enabled": True,
                "server_url": "http://backuphost:8210",
                "retention_hours": 24,
            },
        )
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


def test_disk_usage_reports_none_when_stat_fails(monkeypatch):
    """A failed stat must read as UNKNOWN, not as a full disk.

    Returning 0 here made `Session._watch_disk` force-stop a healthy recording over one transient
    error — the exact recordings the disk guard exists to protect.
    """
    from app import storage

    def _boom(_path):
        raise OSError("drive disconnected")

    monkeypatch.setattr(storage.shutil, "disk_usage", _boom)
    usage = storage.disk_usage_for("D:\\nonexistent")
    assert usage["free_gb"] is None
    assert usage["total_gb"] is None


def test_watch_disk_ignores_unknown_free_space(tmp_path, monkeypatch):
    """An unreadable drive must not trip the forced-stop path."""
    from app import session as session_mod

    monkeypatch.setattr(session_mod, "disk_usage_for", lambda _p: {"free_gb": None})

    class _FakeSession:
        state = "recording"
        captures_root = str(tmp_path)
        backup = None
        disk_action = None
        error = None
        stopped = False

        def stop(self, wait=True):
            self.stopped = True

        def _publish_control(self, msg):
            pass

        def _enable_backup_now(self):
            return False

    s = _FakeSession()
    # Pre-set the stop event so the watcher takes exactly one pass and exits.
    import threading

    s._stop = threading.Event()

    def _wait(_timeout):
        s._stop.set()
        return True

    s._stop.wait = _wait  # type: ignore[method-assign]
    session_mod.RecordingSession._watch_disk(s)  # type: ignore[arg-type]

    assert s.stopped is False, "unknown free space must not force-stop the recording"
    assert s.disk_action is None
    assert s.error is None


def test_estimate_recording_size_uses_float32_rows():
    """The raw writer emits float32 — assuming float64 doubled every size estimate."""
    from app import storage

    # 1000 Hz * 10 s * 10 cols * 4 bytes = 400_000 bytes
    assert storage.estimate_recording_size_gb(1000, 10, 10) == pytest.approx(400_000 / 1e9)


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


# ---- Connectivity Doctor: NI-DAQ runtime finding ----
#
# nidaq_available() is mocked here rather than relying on ambient host state: unlike the design
# doc's assumption of a driver-less dev machine, this build machine has NI-DAQmx 26.0 actually
# installed (from earlier NI-DAQ acquisition work this session), so leaving it unmocked would make
# the warn-path assertion flaky/host-dependent. Mocking both branches exercises the actual
# health_doctor() code path deterministically, same as the other isolation done in this file.


def test_health_doctor_reports_nidaq_runtime_status(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "CAPTURES_ROOT", str(tmp_path))
    monkeypatch.setattr(main, "nidaq_available", lambda: False)
    with TestClient(fastapi_app) as client:
        r = client.post("/health/doctor", json={})
        assert r.status_code == 200, r.text
        findings = r.json()["findings"]
        nidaq = next(f for f in findings if f["service"] == "NI-DAQ runtime")
        # No NI-DAQmx driver available, so the finding must warn, not silently pass as "ok" —
        # that's the whole point of the check.
        assert nidaq["status"] == "warn"
        assert "NI-DAQmx" in nidaq["message"]


def test_health_doctor_reports_nidaq_runtime_ok_when_available(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "CAPTURES_ROOT", str(tmp_path))
    monkeypatch.setattr(main, "nidaq_available", lambda: True)
    with TestClient(fastapi_app) as client:
        r = client.post("/health/doctor", json={})
        assert r.status_code == 200, r.text
        findings = r.json()["findings"]
        nidaq = next(f for f in findings if f["service"] == "NI-DAQ runtime")
        assert nidaq["status"] == "ok"
