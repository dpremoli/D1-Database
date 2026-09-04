import copy

import numpy as np
import pytest

from conftest import (
    GOLDEN_DEFAULT,
    GOLDEN_ENVELOPE,
    assert_columns_match_golden,
    cache_of,
    synthetic_cut,
)

from diag.recipe import DEFAULT_RECIPE
from diag.registry import STEPS, RecipeError
from diag.runner import _TRUNCATABLE, run_recipe, seed_columns

PUBLIC_COLUMNS = {
    "t", "rev", "x", "y", "tsa_resid", "resid_z",
    "gi_star", "gi_sig", "cluster_id", "glosh", "env_band", "segment_id",
    "inverted", "grid_fill", "grid_support", "gmm_id", "gmm_prob",
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


def _angular_resample_idx():
    return next(
        i for i, s in enumerate(DEFAULT_RECIPE["steps"])
        if s["op"] == "angular_resample"
    )


def test_emit_returns_exactly_the_requested_columns_at_natural_length():
    """`emit` bypasses PUBLIC_COLUMNS: it returns the named work-dict columns, float32,
    at their own length -- this is what base.d1an is built from."""
    idx = _angular_resample_idx()
    cols, _ = run_recipe(
        DEFAULT_RECIPE, _seed(), stop_after=idx, emit=("t", "rev", "x", "y", "sig")
    )
    assert list(cols) == ["t", "rev", "x", "y", "sig"]
    assert all(c.dtype == np.float32 for c in cols.values())
    assert len({c.size for c in cols.values()}) == 1
    assert cols["t"].size > 0


def test_emit_works_when_stopped_before_tsa():
    """The default assembly deliberately raises when stopped before tsa; `emit` must not --
    emitting a pre-tsa state is its entire reason to exist."""
    idx = _angular_resample_idx()
    with pytest.raises(ValueError, match="stopped before the 'tsa' step"):
        run_recipe(DEFAULT_RECIPE, _seed(), stop_after=idx)
    cols, _ = run_recipe(DEFAULT_RECIPE, _seed(), stop_after=idx, emit=("t", "sig"))
    assert set(cols) == {"t", "sig"}


def test_emit_missing_column_raises_clearly():
    idx = _angular_resample_idx()
    with pytest.raises(ValueError, match="not present in the work dict"):
        run_recipe(DEFAULT_RECIPE, _seed(), stop_after=idx, emit=("t", "resid_z"))


def test_emit_none_still_yields_the_full_public_column_set():
    """Guard against accidental coupling: the default path is unchanged by the emit seam."""
    cols, _ = run_recipe(DEFAULT_RECIPE, _seed())
    assert set(cols) == PUBLIC_COLUMNS


# --- Equivalence gate --------------------------------------------------------
# The shared golden comparison (and its portability caveat) lives in conftest as
# assert_columns_match_golden; see there. These tests drive it through run_recipe().


def _assert_equivalent_to_golden(recipe, golden_path, nondegenerate=()):
    cols, metrics = run_recipe(recipe, _seed())
    assert_columns_match_golden(cols, metrics, golden_path, nondegenerate)


def test_default_recipe_reproduces_the_frozen_analyse_output_exactly():
    """The equivalence gate. If this FAILS, the registry pipeline is not equivalent and
    the code is what must change -- never the fixture."""
    _assert_equivalent_to_golden(
        copy.deepcopy(DEFAULT_RECIPE),
        GOLDEN_DEFAULT,
        nondegenerate=("tsa_resid", "resid_z", "gi_star"),
    )


def test_default_recipe_with_envelope_on_reproduces_analyse_exactly():
    """Second gate. In golden_default_recipe.npz the env_band column is entirely zeros
    (the default recipe disables the envelope step, so analyse() took its 'refused'
    branch) -- a byte-for-byte check there verifies nothing about the envelope compute
    path. golden_envelope.npz was captured from
    analyse(cache, x, y, samples_per_rev=256, fn_hz=1000.0), which in recipe terms is
    DEFAULT_RECIPE with step s7 ('envelope') turned on and its fn_hz param set to 1000.0.
    deepcopy so the shared DEFAULT_RECIPE constant is never mutated."""
    recipe = copy.deepcopy(DEFAULT_RECIPE)
    s7 = next(s for s in recipe["steps"] if s["id"] == "s7")
    s7["on"] = True
    s7["params"]["fn_hz"] = 1000.0
    _assert_equivalent_to_golden(
        recipe, GOLDEN_ENVELOPE, nondegenerate=("env_band",)
    )


def test_default_recipe_emits_segment_id_all_minus_one():
    cols, _ = run_recipe(DEFAULT_RECIPE, _seed())
    assert "segment_id" in cols
    assert np.all(cols["segment_id"] == -1)
    assert cols["segment_id"].dtype == np.float32
