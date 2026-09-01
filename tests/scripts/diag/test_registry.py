"""Tests for the step registry MECHANISM.

Per controller ruling R1, the MECHANISM tests must not depend on the real algorithms:
they are exercised with dummy steps registered inside the ``dummy_steps`` fixture, which
restores the module-global ``STEPS`` dict afterwards so nothing leaks between modules.

Task 4 appended a second group (below the mechanism tests) that DOES exercise the real
seven ops. Those import ``diag.ops`` at module load -- registering the real steps once,
before any snapshot is taken -- and deliberately do not request ``dummy_steps``.
"""

from dataclasses import FrozenInstanceError

import diag.ops  # noqa: F401  -- import-time side effect: registers the seven real steps
import numpy as np
import pytest
from diag import registry
from diag.recipe import DEFAULT_RECIPE
from diag.registry import (
    SEED_COLUMNS,
    STEPS,
    TIERS,
    RecipeError,
    StepSpec,
    step,
    validate_recipe,
)


@pytest.fixture
def dummy_steps():
    """Snapshot STEPS, register distinctly-named dummies, yield, then restore.

    The ``step()`` decorator mutates a module-global dict at call time; without this
    the dummies would leak into every other test module in the pytest session.
    """
    snapshot = dict(STEPS)
    try:

        @step("_dummy_source", produces=["_dummy_col"], requires=[], tier="derived")
        def _dummy_source(cols, params, inputs):
            n = len(next(iter(cols.values()))) if cols else 4
            return {"_dummy_col": np.zeros(n)}, {"_dummy_metric": 1}

        @step("_dummy_consumer", produces=["_dummy_out"], requires=["_dummy_col"],
              tier="derived")
        def _dummy_consumer(cols, params, inputs):
            return {"_dummy_out": cols["_dummy_col"] + 1}, {}

        yield
    finally:
        STEPS.clear()
        STEPS.update(snapshot)


def test_dummies_are_registered_inside_the_fixture(dummy_steps):
    assert "_dummy_source" in STEPS
    assert "_dummy_consumer" in STEPS


def test_registry_is_clean_after_the_fixture():
    # this test does not request the fixture; the dummies must be gone
    assert "_dummy_source" not in STEPS
    assert "_dummy_consumer" not in STEPS


def test_unknown_op_is_rejected():
    bad = {"recipe_version": 1, "name": "x",
           "steps": [{"id": "a", "op": "does_not_exist", "on": True, "params": {}}]}
    with pytest.raises(RecipeError, match="unknown op"):
        validate_recipe(bad)


def test_duplicate_step_id_is_rejected(dummy_steps):
    bad = {"recipe_version": 1, "name": "x", "steps": [
        {"id": "a", "op": "_dummy_source", "on": True, "params": {}},
        {"id": "a", "op": "_dummy_source", "on": True, "params": {}},
    ]}
    with pytest.raises(RecipeError, match="duplicate step id"):
        validate_recipe(bad)


def test_valid_ordering_passes(dummy_steps):
    ok = {"recipe_version": 1, "name": "x", "steps": [
        {"id": "a", "op": "_dummy_source", "on": True, "params": {}},
        {"id": "b", "op": "_dummy_consumer", "on": True, "params": {}},
    ]}
    validate_recipe(ok)  # must not raise


def test_out_of_order_step_is_rejected(dummy_steps):
    """A step whose `requires` is not produced by an EARLIER enabled step is refused,
    so the editor can reject an illegal insertion before anything runs."""
    bad = {"recipe_version": 1, "name": "x", "steps": [
        {"id": "b", "op": "_dummy_consumer", "on": True, "params": {}},
        {"id": "a", "op": "_dummy_source", "on": True, "params": {}},
    ]}
    with pytest.raises(RecipeError, match="requires"):
        validate_recipe(bad)


def test_disabled_step_does_not_satisfy_a_requirement(dummy_steps):
    """A switched-off step produces nothing, so a later step depending on it is invalid."""
    bad = {"recipe_version": 1, "name": "x", "steps": [
        {"id": "a", "op": "_dummy_source", "on": False, "params": {}},
        {"id": "b", "op": "_dummy_consumer", "on": True, "params": {}},
    ]}
    with pytest.raises(RecipeError, match="requires"):
        validate_recipe(bad)


def test_decorator_rejects_an_invalid_tier():
    with pytest.raises(ValueError, match="tier must be one of"):
        step("_dummy_bad_tier", produces=[], requires=[], tier="nonsense")(lambda *a: None)
    assert "_dummy_bad_tier" not in STEPS


def test_decorator_rejects_a_duplicate_registration(dummy_steps):
    with pytest.raises(ValueError, match="duplicate step registration"):
        step("_dummy_source", produces=[], requires=[], tier="derived")(lambda *a: None)


def test_step_spec_is_frozen(dummy_steps):
    spec = STEPS["_dummy_source"]
    assert isinstance(spec, StepSpec)
    with pytest.raises(FrozenInstanceError):
        spec.tier = "base"


def test_seed_columns_and_tiers_are_exported():
    assert registry.SEED_COLUMNS == (
        "t_raw", "fx", "fy", "fz", "rpm", "revs", "x_raw", "y_raw",
    )
    assert registry.TIERS == ("base", "derived")


# --------------------------------------------------------------------------------------
# Task 4: the real ops (diag.ops) are registered at import time. These tests deliberately
# do NOT request the `dummy_steps` fixture -- they want the real STEPS, unmodified.
# --------------------------------------------------------------------------------------


def test_all_default_recipe_ops_are_registered():
    for s in DEFAULT_RECIPE["steps"]:
        assert s["op"] in STEPS, f"{s['op']} not registered"


def test_default_recipe_validates():
    validate_recipe(DEFAULT_RECIPE)  # must not raise


def test_every_step_declares_a_valid_tier():
    for name, spec in STEPS.items():
        assert spec.tier in TIERS, f"{name} has bad tier {spec.tier!r}"


def test_envelope_is_base_tier():
    # envelope.py is explicitly full-rate time-domain (the Hz content the angular domain
    # discards), so retuning it forces a re-bake. The UI depends on this declaration.
    assert STEPS["envelope"].tier == "base"


def test_seed_column_requirement_is_satisfied_by_seeding():
    """A recipe whose first enabled step requires only seed columns must validate.
    Pins that validate_recipe actually seeds `have` from SEED_COLUMNS (frame_transform
    requires fx/fy/fz, which exist only because of the seed)."""
    assert {"fx", "fy", "fz"}.issubset(set(SEED_COLUMNS))
    r = {"recipe_version": 1, "name": "x", "steps": [
        {"id": "a", "op": "frame_transform", "on": True,
         "params": {"channel": "fp", "mount_deg": 0.0}},
    ]}
    validate_recipe(r)  # must not raise


def test_step_functions_return_columns_and_metrics():
    from diag.angular import angular_resample
    from diag.ops import _op_frame_transform, _op_tsa

    rng = np.random.default_rng(0)
    n_raw = 256 * 5 + 40  # 5 whole revs + a partial
    fx = rng.standard_normal(n_raw)
    fy = rng.standard_normal(n_raw)
    fz = rng.standard_normal(n_raw)

    new_cols, metrics = _op_frame_transform({"fx": fx, "fy": fy, "fz": fz}, {}, {})
    assert isinstance(new_cols, dict) and isinstance(metrics, dict)
    for c in STEPS["frame_transform"].produces:
        assert c in new_cols

    revs = np.linspace(0.0, n_raw / 256.0, n_raw)
    rev_grid, sig = angular_resample(revs, fz, 256)
    new_cols, metrics = _op_tsa({"sig": sig, "rev": rev_grid}, {}, {})
    assert isinstance(new_cols, dict) and isinstance(metrics, dict)
    for c in STEPS["tsa"].produces:
        assert c in new_cols
    # spr-fallback (1 / rev-grid spacing) must land exactly on 256, not 255.999
    assert metrics["n_revolutions"] == new_cols["tsa_resid"].size // 256
    assert metrics["n_revolutions"] >= 4
