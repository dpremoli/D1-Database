"""Channel-model tests: the rotating-dyno preset and its interaction with the fixed
9-column recorder layout. See
docs/superpowers/specs/2026-09-07-milling-path-models-and-polar-design.md #5."""

from __future__ import annotations

import pytest

from app.channels import (
    DYNO_ROTATING,
    DYNO_STATIONARY,
    ROTATING_ORDER,
    autoassign,
    dyno_gains,
    infer_dyno_kind,
    to_record_channels,
)


def _devices_with_n_ai(n: int) -> dict:
    return {
        "chassis": [],
        "standalone": [{"ports": [{"kind": "ai", "physical": f"Dev1/ai{i}"} for i in range(n)]}],
    }


def test_autoassign_stationary_is_unchanged_by_default():
    channels = autoassign(_devices_with_n_ai(10))
    names = [c["name"] for c in channels]
    assert names == ["Fx1", "Fx2", "Fy1", "Fy2", "Fz1", "Fz2", "Fz3", "Fz4", "Tacho"]


def test_autoassign_rotating_fills_four_single_components_plus_tacho():
    channels = autoassign(_devices_with_n_ai(10), kind=DYNO_ROTATING)
    names = [c["name"] for c in channels]
    roles = [c["role"] for c in channels]
    assert names == ["Fx", "Fy", "Fz", "Mz", "Tacho"]
    assert roles == ["Fx", "Fy", "Fz", "Mz", "Tacho"]
    physicals = [c["physical"] for c in channels]
    assert physicals == ["Dev1/ai0", "Dev1/ai1", "Dev1/ai2", "Dev1/ai3", "Dev1/ai4"]


def test_to_record_channels_stationary_unchanged():
    channels = autoassign(_devices_with_n_ai(10))
    out = to_record_channels(channels)
    assert len(out) == 9


def test_to_record_channels_rotating_raises():
    channels = autoassign(_devices_with_n_ai(10), kind=DYNO_ROTATING)
    with pytest.raises(ValueError, match="v2"):
        to_record_channels(channels, kind=DYNO_ROTATING)


def test_dyno_gains_stationary_unchanged():
    channels = autoassign(_devices_with_n_ai(10))
    assert dyno_gains(channels) == []  # no gains supplied -> empty, same as today


def test_dyno_gains_rotating_uses_nm_per_v_for_mz():
    channels = autoassign(_devices_with_n_ai(10), kind=DYNO_ROTATING)
    by_name = {c["name"]: c for c in channels}
    for name in ("Fx", "Fy", "Fz"):
        by_name[name]["gain_n_per_v"] = 100.0
    by_name["Mz"]["gain_nm_per_v"] = 5.0
    gains = dyno_gains(channels, kind=DYNO_ROTATING)
    assert gains == [100.0, 100.0, 100.0, 5.0]


def test_rotating_order_is_fx_fy_fz_mz():
    assert ROTATING_ORDER == ["Fx", "Fy", "Fz", "Mz"]


def test_infer_dyno_kind_detects_rotating_from_mz_channel():
    stationary = autoassign(_devices_with_n_ai(10))
    rotating = autoassign(_devices_with_n_ai(10), kind=DYNO_ROTATING)
    assert infer_dyno_kind(stationary) == DYNO_STATIONARY
    assert infer_dyno_kind(rotating) == DYNO_ROTATING


def test_infer_dyno_kind_defaults_to_stationary_for_empty_or_malformed():
    assert infer_dyno_kind([]) == DYNO_STATIONARY
    assert infer_dyno_kind([{"name": "Fx1"}, {"physical": "Dev1/ai0"}]) == DYNO_STATIONARY


def test_infer_dyno_kind_detects_rotating_from_role_even_if_name_differs():
    # A hand-edited config could name the torque channel anything but still role it "Mz".
    assert infer_dyno_kind([{"name": "Torque", "role": "Mz"}]) == DYNO_ROTATING
