"""The live view is in newtons (#212): the per-channel N/V gains finalize applies to the saved
outputs are applied to the live stream too, so the running peaks (which the force alarm reads),
the trace and the cut detector agree with the saved cut instead of reading low by the gain."""

import pytest

from app.config import RecordConfig
from app.session import RecordingSession

from .test_clipping import GAINS, VFS, _Bus, _RailSource

# _RailSource: 0.5 V on all 8 sensor channels, with one 10 V sample on channel 3 (Fy2).
# GAINS: 50 N/V on Fx1..Fy2, 100 N/V on Fz1..Fz4.
FX_N = 2 * 0.5 * 50.0
FY_PEAK_N = 0.5 * 50.0 + 10.0 * 50.0
FZ_N = 4 * 0.5 * 100.0


def _run(cfg, tmp_path):
    sess = RecordingSession(cfg, str(tmp_path), _RailSource(), broadcaster=_Bus())
    sess.start()
    sess._thread.join(15)
    sess.join_finalize(30)
    return sess


def test_live_peaks_are_in_newtons_and_match_the_saved_cut(tmp_path):
    cfg = RecordConfig(sample_rate=1000, duration_sec=0.3, dyno_gains=GAINS, analog_fullscale_v=VFS)
    sess = _run(cfg, tmp_path)
    live = sess.status()["peaks"]
    assert live == pytest.approx({"Fx": FX_N, "Fy": FY_PEAK_N, "Fz": FZ_N})
    # No drift compensation in this config, so finalize's peaks are the same numbers.
    assert live == pytest.approx(sess.summary["peaks"])


def test_cut_detector_threshold_is_compared_in_newtons(tmp_path):
    # |Fz| is 200 N (2 V summed). A 100 N threshold must see the cut; it could not when the
    # detector was fed volts.
    cfg = RecordConfig(
        sample_rate=1000,
        duration_sec=0.3,
        dyno_gains=GAINS,
        analog_fullscale_v=VFS,
        cut_detect_force=100.0,
    )
    assert _run(cfg, tmp_path).cut_started_t is not None


def test_without_gains_the_live_values_are_passed_through(tmp_path):
    # sim/replay: the data is already in newtons, nothing is scaled.
    sess = _run(RecordConfig(sample_rate=1000, duration_sec=0.3), tmp_path)
    assert sess.status()["peaks"] == pytest.approx({"Fx": 1.0, "Fy": 10.5, "Fz": 2.0})


def test_raw_file_keeps_the_volts(tmp_path):
    from app.d1rw import memmap_rows

    cfg = RecordConfig(sample_rate=1000, duration_sec=0.3, dyno_gains=GAINS, analog_fullscale_v=VFS)
    sess = _run(cfg, tmp_path)
    rows = memmap_rows(f"{sess.dir}/raw.d1raw")
    assert float(rows[:, 1:9].max()) == pytest.approx(10.0)  # the railed sample, in volts
    assert float(rows[0, 5]) == pytest.approx(0.5)
