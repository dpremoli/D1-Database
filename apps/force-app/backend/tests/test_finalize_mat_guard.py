"""#40: a capture whose full-resolution DATA array exceeds MAT5's 32-bit size field must not
crash finalize -- it should skip the .mat write and still produce a usable live_cache + summary.
"""

import os

import numpy as np

from app import finalize as finalize_mod
from app.config import SIGNAL_CHANNELS, RecordConfig
from app.d1rw import RawWriter
from app.finalize import finalize


def _write_raw(tmp_path, n, fs):
    p = str(tmp_path)
    os.makedirs(p, exist_ok=True)
    w = RawWriter(
        os.path.join(p, "raw.d1raw"), n_cols=1 + len(SIGNAL_CHANNELS), rate=fs, start_unix=0.0
    )
    t = np.arange(n) / fs
    data = np.zeros((n, len(SIGNAL_CHANNELS)))
    data[:, 4] = 5.0  # Fz1, a flat non-zero cut so _cut_window has something to find
    w.append(t, data)
    w.close()
    return p


def test_normal_size_capture_still_writes_mat(tmp_path):
    fs, n = 4000, 8000
    d = _write_raw(tmp_path, n, fs)
    cfg = RecordConfig(sample_rate=fs, feed=0.05, diam=80)

    summary = finalize(d, cfg)

    assert summary["mat_written"] is True
    assert summary["mat_skip_reason"] is None
    assert summary["files"]["mat"] == "capture.mat"
    assert os.path.isfile(os.path.join(d, "capture.mat"))


def test_oversized_capture_skips_mat_without_crashing(tmp_path, monkeypatch):
    # Force the guard to trip on a small, fast-to-write capture rather than actually writing a
    # multi-gigabyte raw file.
    monkeypatch.setattr(finalize_mod, "MAT_MAX_BYTES", 1000)
    fs, n = 4000, 8000
    d = _write_raw(tmp_path, n, fs)
    cfg = RecordConfig(sample_rate=fs, feed=0.05, diam=80)

    summary = finalize(d, cfg)

    assert summary["mat_written"] is False
    assert "too large" in summary["mat_skip_reason"]
    assert summary["files"]["mat"] is None
    assert not os.path.isfile(os.path.join(d, "capture.mat"))
    # The rest of finalize's output must still be fully produced.
    assert os.path.isfile(os.path.join(d, "live_cache.bin"))
    assert "capture.mat" not in summary["file_sizes_mb"]
    assert summary["n"] == n
