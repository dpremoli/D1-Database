"""Recipe schema, the default recipe, and content-addressed identity.

A recipe is an ordered list of typed steps. It is deliberately shaped like the FilterChain
JSON already shared verbatim between packages/force-plotting, plugins/filter-service and
scripts/matlab/frm_filters -- including its rule that only ENABLED stages contribute to
identity, so retuning a switched-off step never invalidates a cached result.

This module holds no algorithms and imports nothing from the rest of the package: the
registry maps op names to functions, and this file only describes and hashes them.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

RECIPE_VERSION = 1

# Reproduces analyse()'s hardcoded sequence exactly, including its defaults. Changing any
# step's op, params, or inputs changes the recipe_hash (treat schema changes carefully).
# Top-level keys recipe_version and name do not affect the hash.
DEFAULT_RECIPE: dict[str, Any] = {
    "recipe_version": RECIPE_VERSION,
    "name": "Default",
    "steps": [
        {"id": "s1", "op": "frame_transform", "on": True,
         "params": {"channel": "fp", "mount_deg": 0.0}},
        {"id": "s2", "op": "angular_resample", "on": True,
         "params": {"samples_per_rev": 256}},
        {"id": "s3", "op": "tsa", "on": True, "params": {}},
        {"id": "s4", "op": "radial_detrend", "on": True,
         "params": {"n_bins": 200, "min_per_bin": 8}},
        {"id": "s5", "op": "getis_ord", "on": True,
         "params": {"k": 30, "alpha": 0.05}},
        {"id": "s6", "op": "hdbscan", "on": True,
         "params": {"grid_target": 20000, "min_cluster_size": 10}},
        # Off by default: envelope analysis needs a real dyno_fn_hz, which no tool_setup
        # record supplies yet, so analyse() has always refused it. See the design's
        # open questions.
        {"id": "s7", "op": "envelope", "on": False,
         "params": {"bandwidth_frac": 0.2, "fn_hz": None}},
    ],
}


def _is_on(step: dict) -> bool:
    """Predicate: is this step enabled?"""
    return step.get("on", True)


def enabled_steps(recipe: dict) -> list[dict]:
    return [s for s in recipe.get("steps", []) if _is_on(s)]


def _canonical(step: dict) -> dict:
    """The identity-bearing part of a step. `id` is excluded deliberately: it addresses a
    step for the UI ("view as of s4") and must not make two otherwise-identical recipes
    hash differently."""
    return {
        "op": step["op"],
        "params": dict(sorted((step.get("params") or {}).items())),
        "inputs": dict(sorted((step.get("inputs") or {}).items())),
    }


def prefix_hash(recipe: dict, upto_index: int | None = None) -> str:
    """Identity of the recipe truncated after `upto_index` (an index into the FULL step
    list, disabled steps included, so the caller can address a step positionally).

    None means the whole recipe. Disabled steps inside the prefix are dropped before
    hashing, matching chainKey()'s rule.
    """
    steps = recipe.get("steps", [])
    if upto_index is not None:
        steps = steps[: upto_index + 1]
    payload = [_canonical(s) for s in steps if _is_on(s)]
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


def recipe_hash(recipe: dict) -> str:
    return prefix_hash(recipe, None)
