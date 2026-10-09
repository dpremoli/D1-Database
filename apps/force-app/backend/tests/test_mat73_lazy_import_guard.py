"""h5py loads its own HDF5 DLL, and a conflicting hdf5.dll on PATH (MATLAB, NI) can make that import
fail. It must cost a long cut its .mat only, never stop the backend starting."""

import os
import subprocess
import sys

import numpy as np

from app import finalize as finalize_mod
from app.config import SIGNAL_CHANNELS, RecordConfig
from app.d1rw import RawWriter
from app.finalize import finalize

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_the_backend_imports_when_h5py_cannot_be_loaded():
    code = (
        "import sys; sys.modules['h5py'] = None  # `import h5py` now raises ImportError\n"
        "import app.main, app.finalize, app.mat73\n"
        "assert 'h5py' not in [m for m, v in sys.modules.items() if v is not None]\n"
    )
    r = subprocess.run(
        [sys.executable, "-c", code], cwd=BACKEND, capture_output=True, text=True, timeout=120
    )
    assert r.returncode == 0, r.stderr


def test_an_over_limit_cut_finishes_without_a_mat_when_h5py_cannot_be_loaded(tmp_path, monkeypatch):
    monkeypatch.setattr(finalize_mod, "MAT_MAX_BYTES", 1000)
    monkeypatch.setitem(sys.modules, "h5py", None)
    fs, n = 4000, 8000
    d = str(tmp_path)
    w = RawWriter(os.path.join(d, "raw.d1raw"), n_cols=1 + len(SIGNAL_CHANNELS), rate=fs, start_unix=0.0)
    data = np.zeros((n, len(SIGNAL_CHANNELS)))
    data[:, 4] = 5.0
    w.append(np.arange(n) / fs, data)
    w.close()

    summary = finalize(d, RecordConfig(sample_rate=fs, feed=0.05, diam=80))

    assert summary["mat_written"] is False
    assert summary["mat_format"] is None
    assert "h5py" in summary["mat_skip_reason"]
    assert not os.path.exists(os.path.join(d, "capture.mat"))
    assert not os.path.exists(os.path.join(d, "capture.mat.part"))
    assert os.path.isfile(os.path.join(d, "live_cache.bin"))
