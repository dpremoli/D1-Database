"""LabAmp auto-range logic + endpoints (against the mock)."""
import time

from fastapi.testclient import TestClient

import app.main as main
from app.labamp import MockLabAmp
from app.labamp_autorange import converge_ranges, recommend_range, recommend_ranges, round_up_nice
from app.main import app as fastapi_app


def test_round_up_nice():
    assert round_up_nice(0) == 1
    assert round_up_nice(3) == 5
    assert round_up_nice(6) == 10
    assert round_up_nice(140) == 200
    assert round_up_nice(1000) == 1000


def test_recommend_range_shrinks_and_reports_bits():
    # peak 90 N, over-ranged at 10000 -> recommend ~200 (nice), finer resolution
    r = recommend_range(90.0, headroom=1.5, current=10000.0)  # default 12-bit DAC bottleneck, ±10 V
    assert r["recommended"] == 200                       # round_up_nice(135)
    assert r["would_clip"] is False                      # 90 < 10000
    # effective 12-bit bipolar (amp DAC bottleneck): LSB = 200 / 2**11
    assert abs(r["resolution"] - 200 / 2 ** 11) < 1e-9
    assert 8.0 < r["bits_used"] <= 12.0
    # V->N mapping: N/V = range / 10 V ; peak uses ~45% of the ±10 V output
    assert abs(r["gain_n_per_v"] - 20.0) < 1e-6
    assert 40 <= r["output_pct"] <= 50


def test_recommend_range_flags_clipping():
    # peak exceeds the current range -> would clip, recommend a bigger range
    r = recommend_range(500.0, headroom=1.5, current=200.0)
    assert r["would_clip"] is True
    assert r["recommended"] >= 500 * 1.5


def test_recommend_ranges_channels():
    recs = recommend_ranges([40.0, 90.0], currents=[10000.0, 10000.0], headroom=1.5)
    assert [x["channel"] for x in recs] == [1, 2]
    assert recs[0]["recommended"] < recs[1]["recommended"]


def test_converge_clipped_ranges_up_non_clipped_down():
    # ch1 railed at its 200 N range (true peak unknown) -> range UP off current, not the gentle
    # headroom bump; ch2 saw 40 N inside a 10000 N range -> converge DOWN.
    recs = converge_ranges(peaks=[200.0, 40.0], clipped=[True, False],
                           currents=[200.0, 10000.0], headroom=1.5, clip_factor=2.0)
    assert recs[0]["clipped"] is True
    assert recs[0]["recommended"] >= 400                 # over-shoots the clipped range
    assert recs[1]["clipped"] is False
    assert recs[1]["recommended"] < 10000                # converges the over-ranged channel down
    # resolution stays consistent with the (possibly bumped) recommended range at 12-bit
    assert abs(recs[0]["resolution"] - recs[0]["recommended"] / 2 ** 11) < 1e-9


def test_converge_endpoint_applies(monkeypatch, tmp_path):
    monkeypatch.setattr(main, "CAPTURES_ROOT", str(tmp_path))
    main._rebuild_labamp()
    with TestClient(fastapi_app) as client:
        out = client.post("/labamp/autorange/converge", json={
            "peaks": [40, 39, 55, 53, 500, 88, 90, 91],   # ch5 spiked
            "clipped": [False] * 4 + [True] + [False] * 3,
            "currents": [200] * 8, "headroom": 1.5, "apply": True,
        }).json()
        assert out["applied"] is True and out["effective_bits"] == 12
        assert out["recommendations"][4]["clipped"] is True
        assert all(s == "OK" for s in out["status"].values())


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
        assert rec["nidaq_bits"] == 16 and rec["dac_bits"] == 12 and rec["effective_bits"] == 12
        assert rec["fullscale_v"] == 10.0 and len(rec["recommendations"]) == 8
        # all recommended ranges are far below the over-ranged 10000 default
        assert all(r["recommended"] < 1000 for r in rec["recommendations"])

        applied = client.post("/labamp/autorange/apply", json={"headroom": 1.5}).json()
        assert len(applied["applied"]) == 8
        # after applying, no channel is over-range
        assert all(s == "OK" for s in applied["status"].values())
        # sensor table now reflects the applied ranges
        rows = client.get("/labamp/sensors").json()["sensors"]
        assert all(row["range"] < 1000 for row in rows)
