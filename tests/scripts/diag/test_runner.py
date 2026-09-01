import copy

import numpy as np
import pytest

from conftest import cache_of, synthetic_cut

from diag.recipe import DEFAULT_RECIPE
from diag.registry import STEPS, RecipeError
from diag.runner import _TRUNCATABLE, run_recipe, seed_columns

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


def test_stop_after_before_tsa_raises_not_returns_empties():
    """stop_after cutting before tsa leaves no angular length defined. The runner must fail
    loudly rather than hand back eleven zero-length columns that a caller would persist."""
    idx = next(
        i for i, s in enumerate(DEFAULT_RECIPE["steps"]) if s["op"] == "angular_resample"
    )
    with pytest.raises(ValueError, match="before the 'tsa' step"):
        run_recipe(DEFAULT_RECIPE, _seed(), stop_after=idx)


def test_stop_after_at_radial_detrend_produces_the_full_column_set():
    """Directly exercise stop_after (a later task builds intermediate artifacts with it):
    stopping at radial_detrend still yields all eleven columns, one length, later steps
    zero-filled."""
    idx = next(
        i for i, s in enumerate(DEFAULT_RECIPE["steps"]) if s["op"] == "radial_detrend"
    )
    cols, _ = run_recipe(DEFAULT_RECIPE, _seed(), stop_after=idx)
    assert set(cols) == PUBLIC_COLUMNS
    assert len({c.size for c in cols.values()}) == 1
    assert cols["resid_z"].size > 0
    assert np.count_nonzero(cols["gi_star"]) == 0
    assert np.count_nonzero(cols["cluster_id"]) == 0


def test_resume_path_omits_metrics_it_cannot_truthfully_compute():
    """cached_fs_hz / effective_fs_hz / effective_nyquist_hz derive from seed columns that
    a from_step resume does not carry. Absent keys, not zeros -- a zero Nyquist is a lie a
    consumer would plot."""
    idx = next(i for i, s in enumerate(DEFAULT_RECIPE["steps"]) if s["op"] == "getis_ord")
    prefix, _ = run_recipe(DEFAULT_RECIPE, _seed(), stop_after=idx - 1)
    _, metrics = run_recipe(DEFAULT_RECIPE, prefix, from_step=idx)
    assert "cached_fs_hz" not in metrics
    assert "effective_fs_hz" not in metrics
    assert "effective_nyquist_hz" not in metrics


def test_truncation_allowlist_covers_every_registered_angular_column():
    """Pins the hardcoded allowlist: if a future step is registered that produces an
    angular-domain column, this fails until _TRUNCATABLE covers it (or `sig`, the one
    deliberate exclusion)."""
    covered = set(_TRUNCATABLE) | {"sig"}
    angular = {
        c for s in STEPS.values() if s.tier == "derived" for c in s.produces
    } | set(STEPS["angular_resample"].produces)
    assert covered >= angular


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
