import os
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", "scripts"))

from diag.registry import RecipeError, resolve_inputs


def _sq(h):
    return [[-h, -h], [h, -h], [h, h], [-h, h]]


def _layer(polys):
    return {
        "role": "mask",
        "geometry": {"polygons": polys},
        "value": {"mode": "exclude"},
        "version": 1,
    }


def test_resolve_inputs_rasterizes_a_bound_layer():
    step = {
        "op": "radial_detrend",
        "on": True,
        "inputs": {"mask": {"layer": "chuck", "required": False}},
    }
    layers = {"chuck": _layer([_sq(1.0)])}
    out = resolve_inputs(step, layers, np.array([0.0, 5.0]), np.array([0.0, 5.0]))
    assert out["mask"].tolist() == [True, False]


def test_resolve_inputs_no_binding_returns_empty():
    assert resolve_inputs({"op": "tsa", "on": True}, None, None, None) == {}


def test_resolve_inputs_missing_optional_layer_is_none():
    step = {"op": "radial_detrend", "inputs": {"mask": {"layer": "absent"}}}
    assert resolve_inputs(step, {}, np.zeros(3), np.zeros(3)) == {"mask": None}


def test_resolve_inputs_missing_required_layer_raises():
    step = {"op": "radial_detrend", "inputs": {"mask": {"layer": "absent", "required": True}}}
    with pytest.raises(RecipeError, match="absent"):
        resolve_inputs(step, {}, np.zeros(3), np.zeros(3))


def test_resolve_inputs_rejects_a_binding_on_a_base_tier_step():
    step = {"op": "angular_resample", "inputs": {"mask": {"layer": "x"}}}
    with pytest.raises(RecipeError, match="base"):
        resolve_inputs(step, {"x": _layer([_sq(1.0)])}, np.zeros(3), np.zeros(3))


def test_resolve_inputs_rejects_a_length_mismatch():
    # a degenerate geometry can't mismatch, but a hand-mangled layers dict could; the guard
    # exists so a coordinate-space slip surfaces loudly rather than as silent misalignment.
    step = {"op": "getis_ord", "inputs": {"mask": {"layer": "m"}}}
    bad = {"m": {"geometry": {"polygons": [_sq(1.0)]}, "role": "mask", "value": None, "version": 1}}
    # monkeypatch rasterize to return the wrong length
    import diag.registry as reg

    orig = reg.rasterize_polygons
    reg.rasterize_polygons = lambda *_: np.zeros(99, dtype=bool)
    try:
        with pytest.raises(RecipeError, match="expects"):
            resolve_inputs(step, bad, np.zeros(3), np.zeros(3))
    finally:
        reg.rasterize_polygons = orig
