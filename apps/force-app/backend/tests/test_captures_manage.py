"""Tests for the local capture browse/delete endpoints behind Settings > Local Captures."""

from __future__ import annotations

import json
import os

import pytest
from fastapi.testclient import TestClient

from app import main
from app.main import app


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "CAPTURES_ROOT", str(tmp_path))
    monkeypatch.setattr(main, "_session", None)
    with TestClient(app) as c:
        yield c


# Sizes are reported in MB rounded to 2dp, so fixtures use realistic (MB-scale) raw files —
# a 1KB stand-in rounds to 0.0 and would make the size assertions meaningless.
def _make_capture(root, cid: str, *, finalized: bool = True, raw_bytes: int = 250_000) -> str:
    d = os.path.join(str(root), cid)
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "raw.d1raw"), "wb") as f:
        f.write(b"\0" * raw_bytes)
    if finalized:
        with open(os.path.join(d, "capture.mat"), "wb") as f:
            f.write(b"\0" * 64)
        with open(os.path.join(d, "live_cache.bin"), "wb") as f:
            f.write(b"\0" * 32)
        with open(os.path.join(d, "summary.json"), "w") as f:
            json.dump({
                "sample_name": f"SAMPLE-{cid}", "duration_sec": 4.5, "n": 9000,
                "peaks": {"Fx": 1.0, "Fy": 2.0, "Fz": 3.0}, "config": {"source": "nidaq"},
            }, f)
    return d


def test_browse_lists_finalized_and_incomplete(client, tmp_path):
    _make_capture(tmp_path, "20260822-100000-aaa", finalized=True)
    _make_capture(tmp_path, "20260822-090000-bbb", finalized=False)

    body = client.get("/captures/browse").json()
    ids = [c["id"] for c in body["captures"]]
    assert ids == ["20260822-100000-aaa", "20260822-090000-bbb"]  # newest first

    done, partial = body["captures"]
    assert done["finalized"] is True
    assert done["sample_name"] == "SAMPLE-20260822-100000-aaa"
    assert done["source"] == "nidaq"
    assert done["peaks"]["Fz"] == 3.0
    # An un-finalized capture is exactly what accumulates from "Don't save", so it must be listed,
    # just without the summary-derived fields.
    assert partial["finalized"] is False
    assert "sample_name" not in partial
    assert partial["files"]["raw.d1raw"] > 0


def test_browse_reports_sizes_and_totals(client, tmp_path):
    _make_capture(tmp_path, "a", raw_bytes=2_000_000)
    _make_capture(tmp_path, "b", raw_bytes=1_000_000)

    body = client.get("/captures/browse").json()
    assert body["total_size_mb"] == pytest.approx(3.0, abs=0.01)
    assert body["captures_root"] == str(tmp_path)
    assert "free_gb" in body["disk"]


def test_browse_empty_root(client):
    body = client.get("/captures/browse").json()
    assert body["captures"] == [] and body["total_size_mb"] == 0


def test_delete_removes_a_finalized_capture(client, tmp_path):
    """The gap this closes: recovery.discard_session refuses finalized sessions by design, so
    before this endpoint a completed capture could never be removed from inside the app."""
    d = _make_capture(tmp_path, "20260822-100000-aaa", finalized=True, raw_bytes=500_000)
    assert os.path.isdir(d)

    body = client.delete("/captures/20260822-100000-aaa").json()
    assert body["deleted"] is True
    assert body["freed_mb"] == pytest.approx(0.5, abs=0.01)
    assert not os.path.exists(d)


def test_delete_missing_is_404(client):
    assert client.delete("/captures/nope").status_code == 404


@pytest.mark.parametrize("bad", ["../escape", "a/b", "a\\b"])
def test_delete_rejects_path_traversal(client, bad):
    assert client.delete(f"/captures/{bad}").status_code in (400, 404)


def test_delete_refuses_the_in_progress_recording(client, tmp_path, monkeypatch):
    _make_capture(tmp_path, "live-one", finalized=False)

    class _FakeSession:
        id = "live-one"
        state = "recording"

    monkeypatch.setattr(main, "_session", _FakeSession())
    res = client.delete("/captures/live-one")
    assert res.status_code == 409
    assert os.path.isdir(os.path.join(str(tmp_path), "live-one"))


def test_delete_allows_a_finished_session_that_is_still_referenced(client, tmp_path, monkeypatch):
    """Only an ACTIVE recording is protected — the last finished one must still be deletable."""
    _make_capture(tmp_path, "done-one", finalized=True)

    class _FakeSession:
        id = "done-one"
        state = "done"

    monkeypatch.setattr(main, "_session", _FakeSession())
    assert client.delete("/captures/done-one").status_code == 200
