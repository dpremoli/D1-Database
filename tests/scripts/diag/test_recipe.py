import copy

from diag.recipe import DEFAULT_RECIPE, enabled_steps, prefix_hash, recipe_hash


def test_default_recipe_is_well_formed():
    assert DEFAULT_RECIPE["recipe_version"] == 1
    ids = [s["id"] for s in DEFAULT_RECIPE["steps"]]
    assert len(ids) == len(set(ids)), "step ids must be unique"
    # Assert complete op sequence
    assert [s["op"] for s in DEFAULT_RECIPE["steps"]] == [
        "frame_transform",
        "angular_resample",
        "tsa",
        "radial_detrend",
        "getis_ord",
        "hdbscan",
        "envelope",
    ]
    # Assert step ids are exactly s1..s7
    assert ids == ["s1", "s2", "s3", "s4", "s5", "s6", "s7"]
    # Assert envelope is disabled
    envelope = next(s for s in DEFAULT_RECIPE["steps"] if s["op"] == "envelope")
    assert envelope["on"] is False


def test_disabled_step_params_do_not_change_the_hash():
    """Mirrors chainKey(): only enabled stages contribute to identity, so retuning a
    switched-off step must not invalidate a cached bake."""
    a = copy.deepcopy(DEFAULT_RECIPE)
    b = copy.deepcopy(DEFAULT_RECIPE)
    off = next(s for s in b["steps"] if not s.get("on", True))
    off["params"]["bandwidth_frac"] = 0.9
    assert recipe_hash(a) == recipe_hash(b)


def test_enabling_a_step_changes_the_hash():
    a = copy.deepcopy(DEFAULT_RECIPE)
    b = copy.deepcopy(DEFAULT_RECIPE)
    next(s for s in b["steps"] if not s.get("on", True))["on"] = True
    assert recipe_hash(a) != recipe_hash(b)


def test_param_change_on_an_enabled_step_changes_the_hash():
    a = copy.deepcopy(DEFAULT_RECIPE)
    b = copy.deepcopy(DEFAULT_RECIPE)
    next(s for s in b["steps"] if s["op"] == "getis_ord")["params"]["k"] = 50
    assert recipe_hash(a) != recipe_hash(b)


def test_step_id_is_not_part_of_identity():
    """Two recipes that compute the same thing must share a hash even if their step ids
    differ -- ids exist for UI addressing, not for identity."""
    a = copy.deepcopy(DEFAULT_RECIPE)
    b = copy.deepcopy(DEFAULT_RECIPE)
    for i, s in enumerate(b["steps"]):
        s["id"] = f"renamed{i}"
    assert recipe_hash(a) == recipe_hash(b)


def test_prefix_hash_is_stable_for_later_edits():
    """The optimisation that makes retuning fast: editing step 6 must not invalidate the
    computed prefix through step 5."""
    a = copy.deepcopy(DEFAULT_RECIPE)
    b = copy.deepcopy(DEFAULT_RECIPE)
    next(s for s in b["steps"] if s["op"] == "hdbscan")["params"][
        "min_cluster_size"
    ] = 99
    idx = next(i for i, s in enumerate(a["steps"]) if s["op"] == "getis_ord")
    assert prefix_hash(a, idx) == prefix_hash(b, idx)
    assert recipe_hash(a) != recipe_hash(b)


def test_enabled_steps_filters():
    n_on = sum(1 for s in DEFAULT_RECIPE["steps"] if s.get("on", True))
    assert len(enabled_steps(DEFAULT_RECIPE)) == n_on


def test_prefix_hash_format():
    """Assert that prefix_hash returns 16 hex characters."""
    h = prefix_hash(DEFAULT_RECIPE)
    assert len(h) == 16, f"expected 16 hex chars, got {len(h)}"
    assert all(c in "0123456789abcdef" for c in h), f"expected hex chars only, got {h}"
