"""POST /storage/config guards (#101): the recording folder can be any folder the operator picks,
so the backend has to refuse the ones that would break a recording."""

from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

from app import main, storage
from app.main import app


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "CAPTURES_ROOT", str(tmp_path / "current"))
    monkeypatch.setattr(main, "STORAGE_CONFIG_PATH", str(tmp_path / "cfg" / "storage_config.json"))
    monkeypatch.setattr(main, "_session", None)
    with TestClient(app) as c:
        yield c


def test_any_writable_folder_is_accepted_and_the_probe_leaves_nothing_behind(client, tmp_path):
    target = tmp_path / "My Recordings" / "rig 2"
    res = client.post("/storage/config", json={"captures_root": str(target)})

    assert res.status_code == 200
    assert res.json()["captures_root"] == str(target)
    assert main.CAPTURES_ROOT == str(target)
    assert os.listdir(target) == []  # the write test removed its own file


def test_refused_while_a_recording_is_in_progress_or_saving(client, tmp_path, monkeypatch):
    monkeypatch.setattr(main, "_busy", lambda: True)
    before = main.CAPTURES_ROOT
    res = client.post("/storage/config", json={"captures_root": str(tmp_path / "elsewhere")})

    assert res.status_code == 409
    assert "in progress" in res.json()["detail"]
    assert main.CAPTURES_ROOT == before
    assert not (tmp_path / "elsewhere").exists()


def test_refused_when_the_folder_cannot_be_written(client, tmp_path, monkeypatch):
    # Stands in for a read-only share or a write-protected drive: makedirs succeeds on a folder
    # that already exists, and only an actual write shows the problem.
    monkeypatch.setattr(storage, "writable_error", lambda _p: "[Errno 13] Permission denied")
    before = main.CAPTURES_ROOT
    res = client.post("/storage/config", json={"captures_root": str(tmp_path / "ro")})

    assert res.status_code == 400
    assert "cannot write to" in res.json()["detail"]
    assert "Permission denied" in res.json()["detail"]
    assert main.CAPTURES_ROOT == before


def test_a_recording_that_starts_during_the_folder_check_blocks_the_change(client, tmp_path, monkeypatch):
    busy = {"now": False}
    real = storage.writable_error

    def probe_then_start_recording(p):
        busy["now"] = True  # /record/start lands while the write test is running
        return real(p)

    monkeypatch.setattr(main, "_busy", lambda: busy["now"])
    monkeypatch.setattr(storage, "writable_error", probe_then_start_recording)
    before = main.CAPTURES_ROOT
    res = client.post("/storage/config", json={"captures_root": str(tmp_path / "late")})

    assert res.status_code == 409
    assert main.CAPTURES_ROOT == before


def test_a_refused_folder_that_the_request_created_is_removed_again(client, tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "writable_error", lambda _p: "[Errno 13] Permission denied")
    res = client.post("/storage/config", json={"captures_root": str(tmp_path / "a" / "b")})

    assert res.status_code == 400
    assert not (tmp_path / "a").exists()


def test_a_refused_folder_that_already_existed_is_left_alone(client, tmp_path, monkeypatch):
    existing = tmp_path / "keep"
    existing.mkdir()
    monkeypatch.setattr(storage, "writable_error", lambda _p: "[Errno 13] Permission denied")
    res = client.post("/storage/config", json={"captures_root": str(existing / "sub")})

    assert res.status_code == 400
    assert existing.exists() and not (existing / "sub").exists()


def test_relative_paths_are_refused(client):
    res = client.post("/storage/config", json={"captures_root": "captures"})
    assert res.status_code == 400
    assert "full folder path" in res.json()["detail"]


def test_writable_error_reports_a_missing_folder(tmp_path):
    assert storage.writable_error(str(tmp_path)) is None
    assert storage.writable_error(str(tmp_path / "missing")) is not None
