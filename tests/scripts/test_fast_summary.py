import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "scripts"))

import fast_mapping as fm


def test_summarize_trace_peaks_and_shape():
    # 0..100..100..0 degC ramp/hold/cool over 40 s at 1 Hz
    t = list(range(40))
    temp = list(range(0, 100, 5)) + [100] * 10 + list(range(100, 50, -5))
    series = {"pyro_top": temp, "force": [0] * 20 + [63.1] * 20}
    s = fm.summarize_trace(series, t)
    assert s["peak_temp_c"] == 100
    assert s["peak_force_kn"] == 63.1
    assert s["dwell_s"] > 0
    assert s["ramp_c_per_min"] > 0


def test_summarize_trace_omits_absent_channels():
    s = fm.summarize_trace({"pyro_top": [1, 2, 3]}, [0, 1, 2])
    assert "peak_temp_c" in s
    assert "peak_force_kn" not in s
    assert "peak_power_kw" not in s


def test_summarize_trace_handles_nones_and_empty():
    assert fm.summarize_trace({}, []) == {}
    s = fm.summarize_trace({"pyro_top": [None, 5, None]}, [0, 1, 2])
    assert s["peak_temp_c"] == 5


def test_normalize_fast_csv_returns_summary():
    raw = (
        b"P.time,AV Pyrometer,AV Force\n"
        b"s,C,kN\n"
        b"0:00:01,100,10\n0:00:02,200,20\n0:00:03,150,15\n"
    )
    res = fm.normalize_fast_csv(raw)
    assert res["summary"]["peak_temp_c"] == 200
    assert res["summary"]["peak_force_kn"] == 20
