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
    sess.join_finalize(30)
    assert sess.state == "done", sess.error
    buf = open(f"{sess.dir}/live_cache.bin", "rb").read()
    out = d1lc.parse_d1lc(buf)
    # the finalized Fz peak matches the source cut (within decimation tolerance)
    assert abs(float(np.max(out["fz"])) - float(np.max(fz))) < 3.0
    # rpm recovered from the synthesised tacho is ~1500
    assert abs(float(np.median(out["rpm"])) - 1500.0) / 1500.0 < 0.05


def test_replay_live_rpm_survives_decimation(tmp_path):
    """A cut long enough to force stride > 1 must still report the cache's true RPM live.

    Regression: /record/start_replay sets cfg.sample_rate to the cache's ORIGINAL rate while
    ReplaySource streams at fs/stride, so FrmIntegrator (which read cfg.sample_rate) reported
    RPM high by exactly `stride`. Every fixture above is stride == 1, which is why it was missed.
    """
    n, fs = 400_000, 20_000.0  # 20 s; > the 300k cap, so ReplaySource decimates
    cache, _ = _make_cache(tmp_path, n=n, fs=fs, rpm=1500.0)
    src = ReplaySource(cache, ppr=1, realtime=False)
    assert src.rate < fs, "fixture must actually decimate or it cannot catch this"

    # Exactly what main.py:record_start_replay builds — cfg.sample_rate is the ORIGINAL fs.
    cfg = RecordConfig(
        sample_name="REPLAY-DECIMATED", axis="Fz",
        feed=src.feed, diam=src.diam, sample_rate=fs, duration_sec=n / fs, ppr=1,
    )
    sess = RecordingSession(cfg, str(tmp_path), src, broadcaster=None)
    sess.start()
    sess._thread.join(120)
    sess.join_finalize(120)
    assert sess.state == "done", sess.error
    assert abs(sess.frm._last_rpm - 1500.0) / 1500.0 < 0.05, (
        f"live RPM {sess.frm._last_rpm:.0f} != 1500 (stride {fs / src.rate:.0f}x error)"
    )


def test_replay_honours_speed_on_long_chunks(tmp_path):
    """Pacing must track the requested speed even when a chunk exceeds the old 0.1 s sleep cap.

    Chunks are sized so any replay is ~400 of them, so a long cut has long chunks. The old
    min(dt, 0.1) cap under-slept every one of them and never caught up, giving a ~40 s floor
    per replay however long the cut really was.
    """
    import time

    n, fs = 200_000, 2_000.0  # 100 s of cut; chunk lands well above 0.1 s of wall time at 1x
    cache, _ = _make_cache(tmp_path, n=n, fs=fs, rpm=1500.0)
    src = ReplaySource(cache, ppr=1, realtime=True, speed=1.0)
    chunk_sec = src.chunk / src.rate
    assert chunk_sec > 0.1, f"fixture chunk {chunk_sec:.3f}s must exceed the old cap"

    src.start()
    t0 = time.perf_counter()
    reads = 5
    for _ in range(reads):
        assert src.read() is not None
    wall = time.perf_counter() - t0
    played = reads * chunk_sec
    # Allow generous slack for scheduler jitter; the bug was a 3x+ overspeed, not a few percent.
    assert wall > played * 0.7, f"played {played:.2f}s of cut in {wall:.2f}s wall — too fast"
