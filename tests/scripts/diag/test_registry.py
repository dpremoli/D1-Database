"""Tests for the step registry MECHANISM.

Per controller ruling R1, these tests must not depend on the real algorithms
(`diag.ops`, which does not exist until Task 4) nor on `diag.recipe.DEFAULT_RECIPE`.
The mechanism is exercised with dummy steps registered inside a fixture that restores
the module-global ``STEPS`` dict afterwards, so nothing leaks into other test modules.
"""

from dataclasses import FrozenInstanceError

import numpy as np
import pytest

from diag import registry
from diag.registry import STEPS, RecipeError, StepSpec, step, validate_recipe


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
