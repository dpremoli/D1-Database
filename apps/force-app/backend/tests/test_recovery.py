"""Tests for crash recovery: manifest writing, incomplete session scanning, recovery, discard."""

import json
import os

import numpy as np

from app.config import RecordConfig
from app.d1rw import RawWriter
from app.recovery import (
    MANIFEST,
    discard_session,
    recover_session,
    scan_incomplete,
    write_manifest,
)


def _make_raw(capture_dir: str, n_rows: int = 500, rate: float = 2000.0) -> str:
    """Write a minimal valid raw.d1raw with n_rows of random data."""
    os.makedirs(capture_dir, exist_ok=True)
    raw_path = os.path.join(capture_dir, "raw.d1raw")
    n_cols = 10
    w = RawWriter(raw_path, n_cols=n_cols, rate=rate, start_unix=1700000000.0)
    rng = np.random.default_rng(42)
    chunk = 100
    for i in range(0, n_rows, chunk):
        n = min(chunk, n_rows - i)
        t = np.arange(i, i + n, dtype=np.float64) / rate
        data = rng.normal(size=(n, n_cols - 1)).astype(np.float64)
        w.append(t, data)
    w.close()
    return raw_path


# ---- write_manifest ----


def test_write_manifest_creates_file(tmp_path):
    d = str(tmp_path / "session-001")
    os.makedirs(d)
    cfg = RecordConfig(sample_rate=2000, duration_sec=1.0, sample_name="TEST")
    write_manifest(d, "recording", cfg)

    path = os.path.join(d, MANIFEST)
    assert os.path.isfile(path)
    with open(path) as f:
        m = json.load(f)
    assert m["state"] == "recording"
    assert m["config"]["sample_name"] == "TEST"
    assert "updated_at" in m
    assert "error" not in m


def test_write_manifest_with_error(tmp_path):
    d = str(tmp_path / "session-002")
    os.makedirs(d)
    write_manifest(d, "error", error="acquisition error: timeout")

    with open(os.path.join(d, MANIFEST)) as f:
        m = json.load(f)
    assert m["state"] == "error"
    assert m["error"] == "acquisition error: timeout"


def test_write_manifest_atomic_overwrite(tmp_path):
    d = str(tmp_path / "session-003")
    os.makedirs(d)
    write_manifest(d, "recording")
    write_manifest(d, "done")

    with open(os.path.join(d, MANIFEST)) as f:
        m = json.load(f)
    assert m["state"] == "done"
    # no leftover .tmp
    assert not os.path.isfile(os.path.join(d, MANIFEST + ".tmp"))


# ---- scan_incomplete ----


def test_scan_incomplete_finds_crashed_session(tmp_path):
    # Session with raw file but no summary.json → incomplete
    sid = "20240101-120000-abc123"
    d = str(tmp_path / sid)
    _make_raw(d, n_rows=200)

    incomplete = scan_incomplete(str(tmp_path))
    assert len(incomplete) == 1
    assert incomplete[0]["id"] == sid
    assert incomplete[0]["raw"]["n_rows"] == 200
    assert incomplete[0]["raw"]["duration_sec"] > 0


def test_scan_incomplete_skips_finalized(tmp_path):
    sid = "20240101-120000-fin001"
    d = str(tmp_path / sid)
    _make_raw(d, n_rows=100)
    # Create summary.json → marks as finalized
    with open(os.path.join(d, "summary.json"), "w") as f:
        json.dump({"n": 100}, f)

    incomplete = scan_incomplete(str(tmp_path))
    assert len(incomplete) == 0


def test_scan_incomplete_skips_empty_raw(tmp_path):
    sid = "20240101-120000-empty1"
    d = str(tmp_path / sid)
    _make_raw(d, n_rows=0)

    incomplete = scan_incomplete(str(tmp_path))
    assert len(incomplete) == 0


def test_scan_incomplete_includes_manifest(tmp_path):
    sid = "20240101-120000-man001"
    d = str(tmp_path / sid)
    _make_raw(d, n_rows=100)
    cfg = RecordConfig(sample_name="CRASHED-CUT")
    write_manifest(d, "recording", cfg)

    incomplete = scan_incomplete(str(tmp_path))
    assert len(incomplete) == 1
    assert incomplete[0]["manifest"]["config"]["sample_name"] == "CRASHED-CUT"


def test_scan_incomplete_multiple_sessions(tmp_path):
    for i in range(3):
        sid = f"20240101-12000{i}-ses00{i}"
        d = str(tmp_path / sid)
        _make_raw(d, n_rows=50 + i * 50)

    incomplete = scan_incomplete(str(tmp_path))
    assert len(incomplete) == 3


# ---- recover_session ----


def test_recover_session_finalizes(tmp_path):
    sid = "20240101-120000-rec001"
    d = str(tmp_path / sid)
    _make_raw(d, n_rows=500)
    cfg = RecordConfig(sample_name="RECOVER-ME", sample_rate=2000, duration_sec=0.25)
    write_manifest(d, "recording", cfg)

    summary = recover_session(str(tmp_path), sid)

    assert summary["n"] == 500
    assert summary["sample_name"] == "RECOVER-ME"
    assert os.path.isfile(os.path.join(d, "summary.json"))
    assert os.path.isfile(os.path.join(d, "capture.mat"))
    assert os.path.isfile(os.path.join(d, "live_cache.bin"))

    # Manifest updated to "recovered"
    with open(os.path.join(d, MANIFEST)) as f:
        m = json.load(f)
    assert m["state"] == "recovered"


def test_recover_session_without_manifest(tmp_path):
    sid = "20240101-120000-noman1"
    d = str(tmp_path / sid)
    _make_raw(d, n_rows=300, rate=4000)

    summary = recover_session(str(tmp_path), sid)

    assert summary["n"] == 300
    assert "RECOVERED-" in summary["sample_name"]
    assert summary["fs"] == 4000.0


def test_recover_session_rejects_already_finalized(tmp_path):
    sid = "20240101-120000-alrfin"
    d = str(tmp_path / sid)
    _make_raw(d, n_rows=100)
    with open(os.path.join(d, "summary.json"), "w") as f:
        json.dump({"n": 100}, f)

    try:
        recover_session(str(tmp_path), sid)
        assert False, "should have raised ValueError"
    except ValueError as e:
        assert "already finalized" in str(e)


def test_recover_session_rejects_missing(tmp_path):
    try:
        recover_session(str(tmp_path), "nonexistent-session")
        assert False, "should have raised FileNotFoundError"
    except FileNotFoundError:
        pass


def test_recover_session_rejects_path_traversal(tmp_path):
    try:
        recover_session(str(tmp_path), "../etc/passwd")
        assert False, "should have raised ValueError"
    except ValueError as e:
        assert "invalid" in str(e)


# ---- discard_session ----


def test_discard_session_removes_directory(tmp_path):
    sid = "20240101-120000-disc01"
    d = str(tmp_path / sid)
    _make_raw(d, n_rows=100)

    discard_session(str(tmp_path), sid)
    assert not os.path.exists(d)


def test_discard_session_rejects_finalized(tmp_path):
    sid = "20240101-120000-disc02"
    d = str(tmp_path / sid)
    _make_raw(d, n_rows=100)
    with open(os.path.join(d, "summary.json"), "w") as f:
        json.dump({"n": 100}, f)

    try:
        discard_session(str(tmp_path), sid)
        assert False, "should have raised ValueError"
    except ValueError as e:
        assert "finalized" in str(e)


def test_discard_session_rejects_missing(tmp_path):
    try:
        discard_session(str(tmp_path), "ghost-session")
        assert False, "should have raised FileNotFoundError"
    except FileNotFoundError:
        pass


def test_scan_incomplete_survives_zero_column_header(tmp_path):
    """A header reporting n_cols == 0 must not take down the whole scan.

    `truncated_bytes = body_bytes % row_bytes` was unguarded (unlike n_rows just above it), so one
    corrupt file raised ZeroDivisionError out of scan_incomplete — 500-ing /recovery/check and
    hiding every OTHER recoverable session from the user.
    """
    import struct

    from app.d1rw import HEADER_SIZE, MAGIC

    bad = tmp_path / "20260101-000000-bad"
    bad.mkdir()
    head = struct.pack("<4sIIfd", MAGIC, 1, 0, 2000.0, 1700000000.0)
    (bad / "raw.d1raw").write_bytes(head + b"\x00" * (HEADER_SIZE - len(head)) + b"\x01" * 64)

    good = tmp_path / "20260101-000001-good"
    _make_raw(str(good), n_rows=100)

    sessions = scan_incomplete(str(tmp_path))  # must not raise
    ids = {s["id"] for s in sessions}
    assert "20260101-000001-good" in ids, "a corrupt sibling must not hide recoverable sessions"
