"""The finished v7.3 file is renamed from capture.mat.part to capture.mat. On Windows that rename can
hit a sharing violation (antivirus, indexer): retry it, and never delete a finished multi-GB file
because of it. A stale .part from a crashed earlier finalize is removed before the disk check."""

import os

import numpy as np
import pytest

from app import finalize as finalize_mod
from app.config import SIGNAL_CHANNELS, RecordConfig
from app.d1rw import RawWriter
from app.finalize import finalize

FS, N = 4000, 8000


@pytest.fixture(autouse=True)
def _small_limit_and_no_waiting(monkeypatch):
    monkeypatch.setattr(finalize_mod, "MAT_MAX_BYTES", 1000)  # force the v7.3 path on a tiny cut
    monkeypatch.setattr(finalize_mod, "_REPLACE_DELAYS_S", (0, 0, 0, 0, 0))


def _capture(tmp_path):
    d = str(tmp_path)
    w = RawWriter(os.path.join(d, "raw.d1raw"), n_cols=1 + len(SIGNAL_CHANNELS), rate=FS, start_unix=0.0)
    data = np.zeros((N, len(SIGNAL_CHANNELS)))
    data[:, 4] = 5.0
    w.append(np.arange(N) / FS, data)
    w.close()
    return d


def _cfg():
    return RecordConfig(sample_rate=FS, feed=0.05, diam=80)


def _flaky_replace(monkeypatch, failures):
    """os.replace raising PermissionError for the .part only (summary.json uses it too)."""
    real = os.replace
    calls = {"n": 0}

    def fake(src, dst, *a, **k):
        if str(src).endswith(".part"):
            calls["n"] += 1
            if failures is None or calls["n"] <= failures:
                raise PermissionError(32, "The process cannot access the file (sharing violation)")
        return real(src, dst, *a, **k)

    monkeypatch.setattr(os, "replace", fake)
    return calls


def test_a_sharing_violation_that_clears_still_gives_the_mat(tmp_path, monkeypatch):
    d = _capture(tmp_path)
    calls = _flaky_replace(monkeypatch, failures=2)

    summary = finalize(d, _cfg())

    assert calls["n"] == 3
    assert summary["mat_written"] is True
    assert summary["mat_skip_reason"] is None
    assert os.path.isfile(os.path.join(d, "capture.mat"))
    assert not os.path.exists(os.path.join(d, "capture.mat.part"))


def test_a_rename_that_never_works_keeps_the_part_and_names_it(tmp_path, monkeypatch):
    d = _capture(tmp_path)
    _flaky_replace(monkeypatch, failures=None)

    summary = finalize(d, _cfg())

    part = os.path.join(d, "capture.mat.part")
    assert summary["mat_written"] is False
    assert summary["files"]["mat"] is None
    assert part in summary["mat_skip_reason"]
    assert os.path.isfile(part) and os.path.getsize(part) > 0   # the finished file is not deleted
    assert not os.path.exists(os.path.join(d, "capture.mat"))
    assert os.path.isfile(os.path.join(d, "live_cache.bin"))


def test_a_stale_part_is_removed_before_the_disk_check(tmp_path, monkeypatch):
    d = _capture(tmp_path)
    part = os.path.join(d, "capture.mat.part")
    with open(part, "wb") as fh:
        fh.write(b"half a file from a crash")
    seen = {}

    def free(path):
        seen["part_exists"] = os.path.exists(part)
        return 10**15

    monkeypatch.setattr(finalize_mod, "_free_bytes", free)

    summary = finalize(d, _cfg())

    assert seen["part_exists"] is False
    assert summary["mat_written"] is True
    assert os.path.isfile(os.path.join(d, "capture.mat"))
    assert not os.path.exists(part)
