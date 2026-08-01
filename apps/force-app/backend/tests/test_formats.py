"""Binary format round-trips: D1LC, D1RW, D1LF."""

import numpy as np

from app import d1lc, d1rw
from app.stream.frame import decode_frame, encode_frame


def test_d1lc_roundtrip(tmp_path):
    n = 1000
    t = np.linspace(0, 1, n).astype(np.float32)
    fx, fy, fz = (
        (np.sin(t) * 10).astype(np.float32),
        (np.cos(t) * 20).astype(np.float32),
        (t * 30).astype(np.float32),
    )
    rpm = np.full(n, 1200.0, np.float32)
    revs = np.cumsum(rpm / 60.0 / n).astype(np.float32)
    p = tmp_path / "lc.bin"
    d1lc.write_d1lc(
        str(p), t, fx, fy, fz, rpm, revs, fs=1000, feed=0.05, diam=80, cs_sec=0.1, ce_sec=0.9
    )
    buf = p.read_bytes()
    hdr = d1lc.read_d1lc_header(buf)
    assert hdr["n"] == n and hdr["version"] == 1
    assert abs(hdr["fs"] - 1000) < 1e-3 and abs(hdr["feed"] - 0.05) < 1e-6
    # arrays follow the 32-byte header, six float32[n] in order
    arr = np.frombuffer(buf, dtype="<f4", count=n * 6, offset=32).reshape(6, n)
    assert np.allclose(arr[0], t) and np.allclose(arr[3], fz) and np.allclose(arr[5], revs)


def test_d1rw_roundtrip(tmp_path):
    p = str(tmp_path / "raw.d1raw")
    n_cols = 10
    w = d1rw.RawWriter(p, n_cols=n_cols, rate=2000.0, start_unix=123456.0)
    t1 = np.arange(0, 5) / 2000.0
    d1 = np.random.default_rng(0).normal(size=(5, n_cols - 1))
    w.append(t1, d1)
    t2 = np.arange(5, 8) / 2000.0
    d2 = np.random.default_rng(1).normal(size=(3, n_cols - 1))
    w.append(t2, d2)
    assert w.rows == 8
    w.close()
    hdr = d1rw.read_header(p)
    assert hdr["n_cols"] == n_cols and abs(hdr["rate"] - 2000.0) < 1e-3
    rows = d1rw.memmap_rows(p)
    assert rows.shape == (8, n_cols)
    assert np.allclose(rows[:5, 0], t1.astype(np.float32))
    assert np.allclose(rows[5:, 1:], d2.astype(np.float32))


def test_d1lf_roundtrip():
    trace = np.arange(2 * 7, dtype=np.float32).reshape(2, 7)
    pts = np.arange(5 * 3, dtype=np.float32).reshape(5, 3)
    buf = encode_frame(
        seq=7, t_sec=1.5, rpm=1200.0, peaks=(1, 2, 3), n_total=999, trace=trace, pts=pts
    )
    d = decode_frame(buf)
    assert d["seq"] == 7 and d["n_total"] == 999 and abs(d["rpm"] - 1200) < 1e-3
    assert d["peaks"] == (1, 2, 3)
    assert np.allclose(d["trace"], trace) and np.allclose(d["pts"], pts)
