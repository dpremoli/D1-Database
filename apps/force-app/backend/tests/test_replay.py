"""ReplaySource: a D1LC cache streamed through the pipeline reconstructs the same summed forces."""

import numpy as np

from app import d1lc
from app.config import RecordConfig
from app.session import RecordingSession
from app.sources.replay import ReplaySource


def _make_cache(tmp_path, n=6000, fs=6000.0, rpm=1500.0, feed=0.05, diam=80.0):
    t = np.arange(n) / fs
    fx = np.full(n, 30.0, np.float32)
    fy = np.full(n, 45.0, np.float32)
    fz = (100.0 + 8.0 * np.sin(2 * np.pi * 5 * t)).astype(np.float32)  # structured
    rpm_a = np.full(n, rpm, np.float32)
    revs = np.cumsum(rpm_a / 60.0 / fs).astype(np.float32)
    p = tmp_path / "src.bin"
    d1lc.write_d1lc(
        str(p),
        t.astype(np.float32),
        fx,
        fy,
        fz,
        rpm_a,
        revs,
        fs=fs,
        feed=feed,
        diam=diam,
        cs_sec=0.1,
        ce_sec=t[-1] - 0.1,
    )
    return p.read_bytes(), fz


def test_replay_reconstructs_channels():
    cache, fz = _make_cache_bytes()
    src = ReplaySource(cache, ppr=1, realtime=False)
    assert src.channels[-1] == "Tacho"
    src.start()
    t, data = src.read()
    # Fz sub-channels sum back to the cache Fz
    from app.dsp import sum_axes

    axes = sum_axes(data)
    assert np.allclose(axes["Fz"][: t.size], fz[: t.size], atol=1e-3)
    # tacho actually pulses
    assert data[:, -1].max() > 0


def _make_cache_bytes():
    import pathlib
    import tempfile

    d = pathlib.Path(tempfile.mkdtemp())
    return _make_cache(d)


def test_replay_end_to_end(tmp_path):
    cache, fz = _make_cache(tmp_path)
    src = ReplaySource(cache, ppr=1, realtime=False)
    cfg = RecordConfig(
        sample_name="REPLAY-TEST",
        sample_rate=src.rate,
        feed=src.feed,
        diam=src.diam,
        duration_sec=src.total / src.rate,
        axis="Fz",
    )
    sess = RecordingSession(cfg, str(tmp_path), src, broadcaster=None)
    sess.start()
    sess._thread.join(30)
    assert sess.state == "done", sess.error
    buf = open(f"{sess.dir}/live_cache.bin", "rb").read()
    out = d1lc.parse_d1lc(buf)
    # the finalized Fz peak matches the source cut (within decimation tolerance)
    assert abs(float(np.max(out["fz"])) - float(np.max(fz))) < 3.0
    # rpm recovered from the synthesised tacho is ~1500
    assert abs(float(np.median(out["rpm"])) - 1500.0) / 1500.0 < 0.05
