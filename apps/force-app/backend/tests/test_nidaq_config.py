"""NI-DAQ catalog + enumeration (sim/real) + channel model + endpoints."""

from fastapi.testclient import TestClient

import app.main as main
from app import channels as chan
from app import nidaq_catalog as cat
from app import nidaq_enum
from app.config import DEFAULT_NIDAQ_CHANNELS
from app.main import app as fastapi_app


# ---- catalog ----
def test_catalog_lookup_and_normalize():
    assert cat.normalize("NI-9215") == "NI 9215"
    assert cat.normalize("ni 9234") == "NI 9234"
    assert cat.lookup("NI 9215")["connector"] == "bnc"
    assert cat.lookup("NI 9401")["connector"] == "dsub"
    assert cat.lookup("NI 9205")["connector"] == "terminal"
    assert cat.lookup("NI 9201")["ai"] == 8  # requested card is present
    # unknown model -> generic terminal, using the supplied ai count
    g = cat.lookup("NI 9999", ai_count=5)
    assert g["connector"] == "terminal" and g["ai"] == 5


def test_gallery_has_9201():
    models = [c["product_type"] for c in cat.gallery()]
    assert "NI 9201" in models and "NI 9234" in models


# ---- simulated enumeration ----
def test_simulated_tree_shape():
    d = nidaq_enum.enumerate_simulated()
    assert d["simulated"] is True
    ch = d["chassis"][0]
    assert ch["name"] == "cDAQ1" and ch["slots"] == 8
    mod1 = ch["modules"][0]
    assert mod1["name"] == "cDAQ1Mod1" and mod1["connector"] == "bnc"
    assert [p["physical"] for p in mod1["ports"]] == [
        "cDAQ1Mod1/ai0",
        "cDAQ1Mod1/ai1",
        "cDAQ1Mod1/ai2",
        "cDAQ1Mod1/ai3",
    ]


# ---- real enumeration (faked nidaqmx tree) ----
class _Chan:
    def __init__(self, name):
        self.name = name


class _Dev:
    def __init__(self, name, product_type, ai=(), ci=(), chassis=None, slot=0, modules=()):
        self.name = name
        self.product_type = product_type
        self.ai_physical_chans = [
            _Chan(f"{name}/ai{i}") for i in range(ai if isinstance(ai, int) else 0)
        ]
        self.ci_physical_chans = [
            _Chan(f"{name}/ctr{i}") for i in range(ci if isinstance(ci, int) else 0)
        ]
        self.compact_daq_chassis_device = chassis
        self.compact_daq_slot_num = slot
        self.chassis_module_devices = list(modules)


class _System:
    def __init__(self, devices):
        self.devices = devices


def test_real_enumeration_groups_modules_under_chassis():
    chassis = _Dev("cDAQ1", "cDAQ-9178")
    m1 = _Dev("cDAQ1Mod1", "NI 9215", ai=4, chassis=chassis, slot=1)
    m2 = _Dev("cDAQ1Mod2", "NI 9234", ai=4, chassis=chassis, slot=2)
    chassis.chassis_module_devices = [m1, m2]
    d = nidaq_enum.enumerate_real(_System([chassis, m1, m2]))
    assert d["simulated"] is False
    assert d["chassis"][0]["name"] == "cDAQ1"
    mods = d["chassis"][0]["modules"]
    assert [m["name"] for m in mods] == ["cDAQ1Mod1", "cDAQ1Mod2"]
    assert mods[1]["connector"] == "bnc" and mods[1]["iepe"] is True
    assert mods[0]["ports"][0]["physical"] == "cDAQ1Mod1/ai0"


# ---- max_sample_rate (#46) ----
def test_max_sample_rate_is_the_minimum_across_devices_in_use():
    m1 = _Dev("cDAQ1Mod1", "NI 9215", ai=4)
    m1.ai_max_multi_chan_rate = 100_000.0
    m2 = _Dev("cDAQ1Mod2", "NI 9234", ai=4)
    m2.ai_max_multi_chan_rate = 51_367.188
    rate = nidaq_enum.max_sample_rate(["cDAQ1Mod1/ai0", "cDAQ1Mod2/ai0"], system=_System([m1, m2]))
    assert rate == 51_367.188


def test_max_sample_rate_ignores_devices_not_in_the_channel_list():
    m1 = _Dev("cDAQ1Mod1", "NI 9215", ai=4)
    m1.ai_max_multi_chan_rate = 100_000.0
    m2 = _Dev("cDAQ1Mod2", "NI 9234", ai=4)
    m2.ai_max_multi_chan_rate = 51_367.188  # not referenced by any channel below
    rate = nidaq_enum.max_sample_rate(["cDAQ1Mod1/ai0"], system=_System([m1, m2]))
    assert rate == 100_000.0


def test_max_sample_rate_none_without_a_real_system():
    assert nidaq_enum.max_sample_rate(["cDAQ1Mod1/ai0"], system=None) is None


def test_max_sample_rate_none_for_channels_with_no_device_prefix():
    m1 = _Dev("cDAQ1Mod1", "NI 9215", ai=4)
    m1.ai_max_multi_chan_rate = 100_000.0
    assert nidaq_enum.max_sample_rate([], system=_System([m1])) is None


def test_max_sample_rate_skips_a_device_that_cant_report_its_own_limit():
    # A device present in the tree but whose rate property raises (or is absent) must not take
    # down the whole check -- same defensive pattern as enumerate_real's _safe() guard.
    m1 = _Dev("cDAQ1Mod1", "NI 9215", ai=4)  # no ai_max_multi_chan_rate set at all
    m2 = _Dev("cDAQ1Mod2", "NI 9234", ai=4)
    m2.ai_max_multi_chan_rate = 51_367.188
    rate = nidaq_enum.max_sample_rate(["cDAQ1Mod1/ai0", "cDAQ1Mod2/ai0"], system=_System([m1, m2]))
    assert rate == 51_367.188


def test_nidaq_max_rate_endpoint(monkeypatch):
    m1 = _Dev("cDAQ1Mod1", "NI 9215", ai=4)
    m1.ai_max_multi_chan_rate = 51_367.188
    monkeypatch.setattr(nidaq_enum, "_local_system", lambda: _System([m1]))
    with TestClient(fastapi_app) as client:
        r = client.get("/nidaq/max_rate", params={"channels": "cDAQ1Mod1/ai0,cDAQ1Mod1/ai1"})
        assert r.status_code == 200
        assert r.json()["max_rate_hz"] == 51_367.188


def test_nidaq_max_rate_endpoint_null_when_no_channels(monkeypatch):
    with TestClient(fastapi_app) as client:
        r = client.get("/nidaq/max_rate")
        assert r.json()["max_rate_hz"] is None


# ---- channel model ----
def test_autoassign_force_first_and_tacho_on_next_module_ai0():
    d = nidaq_enum.enumerate_simulated()  # Mod1/Mod2 (4 AI each) + Mod3 (9234, 4 AI)
    channels = chan.autoassign(d)
    names = [c["name"] for c in channels]
    assert names == ["Fx1", "Fx2", "Fy1", "Fy2", "Fz1", "Fz2", "Fz3", "Fz4", "Tacho"]
    by = {c["name"]: c for c in channels}
    assert by["Fx1"]["physical"] == "cDAQ1Mod1/ai0"
    assert by["Fz4"]["physical"] == "cDAQ1Mod2/ai3"
    assert by["Tacho"]["physical"] == "cDAQ1Mod3/ai0"  # ai0 of the next module
    assert by["Fx1"]["role"] == "Fx" and by["Tacho"]["role"] == "Tacho"


def test_to_record_channels_orders_and_falls_back():
    channels = [chan.make_channel("Fx1", "Fx", physical="cDAQ1Mod1/ai0")]
    rec = chan.to_record_channels(channels)
    assert rec[0] == "cDAQ1Mod1/ai0"
    assert rec[1] == DEFAULT_NIDAQ_CHANNELS[1]  # unbound slot keeps placeholder
    assert len(rec) == 9


def test_dyno_gains_only_when_all_present():
    ch = [chan.make_channel(n, n[:2], gain=25.0) for n in chan.FORCE_ORDER]
    assert chan.dyno_gains(ch) == [25.0] * 8
    ch[0]["gain_n_per_v"] = None
    assert chan.dyno_gains(ch) == []


# ---- endpoints ----
def test_nidaq_endpoints(monkeypatch, tmp_path):
    monkeypatch.setattr(main, "CAPTURES_ROOT", str(tmp_path))
    monkeypatch.setattr(main, "NIDAQ_SIM_PATH", str(tmp_path / "nidaq_sim.json"))
    monkeypatch.setattr(main, "NIDAQ_CHANNELS_PATH", str(tmp_path / "nidaq_channels.json"))
    with TestClient(fastapi_app) as client:
        dev = client.get("/nidaq/devices").json()
        assert dev["simulated"] is True and len(dev["chassis"][0]["modules"]) == 3

        cat_cards = client.get("/nidaq/catalog").json()["cards"]
        assert any(c["product_type"] == "NI 9201" for c in cat_cards)

        # add a card to slot 4, then it appears
        added = client.post("/nidaq/sim/card", json={"slot": 4, "product_type": "NI 9201"}).json()
        assert any(
            m["slot"] == 4 and m["product_type"] == "NI 9201"
            for m in added["chassis"][0]["modules"]
        )

        # channels auto-assign on first GET
        ch = client.get("/nidaq/channels").json()["channels"]
        assert [c["name"] for c in ch][:2] == ["Fx1", "Fx2"]

        # remove the card
        removed = client.delete("/nidaq/sim/card", params={"slot": 4}).json()
        assert not any(m["slot"] == 4 for m in removed["chassis"][0]["modules"])
