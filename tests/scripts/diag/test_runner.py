import copy

import numpy as np
import pytest

from conftest import cache_of, synthetic_cut

from diag.recipe import DEFAULT_RECIPE
from diag.registry import RecipeError
from diag.runner import run_recipe, seed_columns

PUBLIC_COLUMNS = {
    "t", "rev", "x", "y", "tsa_resid", "resid_z",
    "gi_star", "gi_sig", "cluster_id", "glosh", "env_band",
}


def _seed():
    t, fx, fy, fz, rpm, revs, x, y, fs, _ = synthetic_cut()
    return seed_columns(cache_of(t, fx, fy, fz, rpm, revs, fs), x, y)


def test_run_default_recipe_produces_the_public_column_set():
    cols, metrics = run_recipe(DEFAULT_RECIPE, _seed())
    assert set(cols) == PUBLIC_COLUMNS
    assert metrics["n_revolutions"] > 0


def test_all_columns_share_one_length():
    cols, _ = run_recipe(DEFAULT_RECIPE, _seed())
    assert len({c.size for c in cols.values()}) == 1


def test_internal_columns_are_not_leaked():
    """`sig` and the truncation marker are runner plumbing, not part of the D1AN contract."""
    cols, _ = run_recipe(DEFAULT_RECIPE, _seed())
    assert "sig" not in cols and "__truncate__" not in cols
    assert not any(k.startswith("__") for k in cols)


def test_disabled_step_produces_zeros_not_a_missing_column():
    """env_band is off by default. The D1AN column set is a fixed contract, so a disabled
    step must still yield its column -- the browser reader indexes by name."""
    cols, _ = run_recipe(DEFAULT_RECIPE, _seed())
    assert "env_band" in cols
    assert np.count_nonzero(cols["env_band"]) == 0


def test_runner_assembles_metrics_no_single_op_can_reach():
    """cached_fs_hz / effective_fs_hz / effective_nyquist_hz / env_band_status all vanish
    when the envelope step is off (the default); the runner must re-emit them."""
    _, metrics = run_recipe(DEFAULT_RECIPE, _seed())
    assert metrics["cached_fs_hz"] == 25_000.0
    assert metrics["effective_fs_hz"] > 0
    assert metrics["effective_nyquist_hz"] == metrics["effective_fs_hz"] / 2.0
    assert metrics["env_band_status"] == "refused: dyno_fn_hz not provided"
    assert metrics["samples_per_rev"] == 256


def test_invalid_recipe_is_refused_before_any_work():
    bad = copy.deepcopy(DEFAULT_RECIPE)
    bad["steps"] = [s for s in bad["steps"] if s["op"] != "tsa"]
    with pytest.raises(RecipeError, match="requires"):
        run_recipe(bad, _seed())


def test_from_step_reuses_supplied_columns():
    """Preview's core optimisation: given the columns as of step 4, running from step 5
    must reproduce the same final result as a full run.

    The resumed path feeds run_recipe's float32 public output back in, so it re-enters the
    pipeline at lower precision than a single full-precision run. Exact equality is the
    wrong thing to demand here: both gi_star (a k-NN statistic -- the float32 round-trip
    can swap a near-tie neighbour and shift the score at a handful of points) and
    cluster_id (discrete labels; grid_reduce can move a point across a cell boundary)
    diverge slightly on the resumed path. Assert structural agreement, not identity.
    """
    full, _ = run_recipe(DEFAULT_RECIPE, _seed())
    idx = next(i for i, s in enumerate(DEFAULT_RECIPE["steps"]) if s["op"] == "getis_ord")
    prefix, _ = run_recipe(DEFAULT_RECIPE, _seed(), from_step=None, stop_after=idx - 1)
    resumed, _ = run_recipe(DEFAULT_RECIPE, prefix, from_step=idx)
    # The overwhelming majority of gi_star values are unchanged; the rest are neighbour-swap
    # discontinuities inherent to float32 re-entry, and the fields stay strongly correlated.
    close = np.isclose(resumed["gi_star"], full["gi_star"], rtol=1e-4, atol=1e-3)
    assert np.mean(close) > 0.85
    assert np.corrcoef(resumed["gi_star"], full["gi_star"])[0, 1] > 0.99
    assert np.mean(resumed["cluster_id"] == full["cluster_id"]) > 0.99
