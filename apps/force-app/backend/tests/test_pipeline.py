"""End-to-end: run a short non-realtime session, then assert the finalized artifacts are correct
and that the live_cache.bin parses back through the shared D1LC format."""
import os
import struct

import numpy as np
from scipy.io import loadmat

from app import d1lc
from app.config import RecordConfig
from app.session import RecordingSession


def test_session_end_to_end(tmp_path):
    cfg = RecordConfig(sample_rate=4000, duration_sec=1.0, rpm=1200, feed=0.05, diam=80)
    sess = RecordingSession(cfg, str(tmp_path), broadcaster=None, realtime=False)
    sess.start()
    sess._thread.join(30)  # runs to natural completion (finite sim), then finalizes
    assert sess.state == "done", sess.error
    assert sess.n_total > 0

    d = sess.dir
    for name in ("raw.d1raw", "capture.mat", "live_cache.bin", "summary.json"):
        assert os.path.isfile(os.path.join(d, name)), f"missing {name}"

    # .mat: v1.0 10-column DATA + metadata
    m = loadmat(os.path.join(d, "capture.mat"))
    assert m["DATA"].shape[1] == 10
    assert m["DATA"].shape[0] == sess.n_total
    assert float(m["metadata"]["fileVersion"][0][0][0][0]) == 1.0

    # live_cache.bin parses via the shared D1LC format (same as filter-service/client)
    buf = open(os.path.join(d, "live_cache.bin"), "rb").read()
    hdr = d1lc.read_d1lc_header(buf)
    assert hdr["n"] > 0
    assert abs(hdr["diam"] - 80.0) < 1e-3 and abs(hdr["feed"] - 0.05) < 1e-6
    arr = np.frombuffer(buf, dtype="<f4", count=hdr["n"] * 6, offset=32).reshape(6, hdr["n"])
    # Fz (index 3) should show real cutting force; revs (index 5) increases
    assert np.max(np.abs(arr[3])) > 10.0
    assert arr[5][-1] > arr[5][0]


def test_start_writes_raw_header(tmp_path):
    cfg = RecordConfig(sample_rate=2000, duration_sec=0.5)
    sess = RecordingSession(cfg, str(tmp_path), broadcaster=None, realtime=False)
    sess.start()
    sess._thread.join(30)
    with open(os.path.join(sess.dir, "raw.d1raw"), "rb") as f:
        magic = f.read(4)
    assert magic == b"D1RW"
