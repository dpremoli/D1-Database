"""LabAmp auto-range logic + endpoints (against the mock)."""
import time

from fastapi.testclient import TestClient

import app.main as main
from app.labamp import MockLabAmp
from app.labamp_autorange import recommend_range, recommend_ranges, round_up_nice
from app.main import app as fastapi_app


def test_round_up_nice():
    assert round_up_nice(0) == 1
    assert round_up_nice(3) == 5
    assert round_up_nice(6) == 10
    assert round_up_nice(140) == 200
    assert round_up_nice(1000) == 1000


def test_recommend_range_shrinks_and_reports_bits():
    # peak 90 N, over-ranged at 10000 -> recommend ~200 (nice), much finer resolution
    r = recommend_range(90.0, headroom=1.5, current=10000.0)
    assert r["recommended"] == 200                       # round_up_nice(135)
    assert r["would_clip"] is False                      # 90 < 10000
    # bipolar 24-bit: LSB = 200 / 2**23 ; bits used by 90 N ≈ log2(90/LSB) ~ 22
    assert 20.0 < r["bits_used"] <= 24.0
    assert r["resolution"] < 0.001                       # fine resolution at the small range


def test_recommend_range_flags_clipping():
    # peak exceeds the current range -> would clip, recommend a bigger range
    r = recommend_range(500.0, headroom=1.5, current=200.0)
    assert r["would_clip"] is True
    assert r["recommended"] >= 500 * 1.5


def test_recommend_ranges_channels():
    recs = recommend_ranges([40.0, 90.0], currents=[10000.0, 10000.0], headroom=1.5)
    assert [x["channel"] for x in recs] == [1, 2]
    assert recs[0]["recommended"] < recs[1]["recommended"]


def test_mock_range_roundtrip():
    m = MockLabAmp()
    assert m.sensor_table(8)[4]["range"] == 10000.0
    assert m.channel_status(8)[5] == "OK"                # peak 92 < range 10000 -> OK
    # over-range only when range < peak; set a tiny range and confirm OR_INPUT
    m.set_range(5, 10.0)
    assert m.channel_status(8)[5] == "OR_INPUT"
    m.set_range(5, 200.0)
    assert m.channel_status(8)[5] == "OK"


def test_autorange_endpoints(monkeypatch, tmp_path):
    monkeypatch.setattr(main, "CAPTURES_ROOT", str(tmp_path))
    main._rebuild_labamp()                               # fresh mock
    with TestClient(fastapi_app) as client:
        rec = client.get("/labamp/autorange").json()
        assert rec["adc_bits"] == 24 and len(rec["recommendations"]) == 8
        # all recommended ranges are far below the over-ranged 10000 default
        assert all(r["recommended"] < 1000 for r in rec["recommendations"])

        applied = client.post("/labamp/autorange/apply", json={"headroom": 1.5}).json()
        assert len(applied["applied"]) == 8
        # after applying, no channel is over-range
        assert all(s == "OK" for s in applied["status"].values())
        # sensor table now reflects the applied ranges
        rows = client.get("/labamp/sensors").json()["sensors"]
        assert all(row["range"] < 1000 for row in rows)
