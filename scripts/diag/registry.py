"""The step registry: mechanism only, no algorithms.

A step is a pure function over a column dict with a declared contract. `produces` is what
lets the viewer's channel selector be derived from the recipe rather than hardcoded --
the defect that left gi_star, glosh and cluster_id computed but unreachable. `requires`
lets the editor refuse an illegal ordering before anything runs. `tier` says whether a step
can be previewed from base.d1an ('derived') or needs the raw full-rate cache and therefore
a re-bake ('base').

Tier is a property of what a step CONSUMES, not of where it sits in the list: `envelope`
is 'base' despite running last, because it operates on the full-rate signal rather than the
angular-resampled columns everything else uses.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import numpy as np

Columns = dict[str, np.ndarray]
StepFn = Callable[[Columns, dict[str, Any], dict[str, Any]], tuple[Columns, dict]]

# Columns present before any step runs, seeded by the runner from the D1LC cache and the
# D1OC spiral. x_raw/y_raw are MATLAB's own geometry, never recomputed here.
SEED_COLUMNS: tuple[str, ...] = (
    "t_raw", "fx", "fy", "fz", "rpm", "revs", "x_raw", "y_raw",
)

TIERS = ("base", "derived")


@dataclass(frozen=True)
class StepSpec:
    name: str
    fn: StepFn
    produces: tuple[str, ...]
    requires: tuple[str, ...]
    tier: str


STEPS: dict[str, StepSpec] = {}


class RecipeError(ValueError):
    """A recipe that cannot be executed as written."""


def step(name: str, *, produces: list[str], requires: list[str], tier: str):
    """Register a step function. Import-time side effect, so diag.ops must be imported
    before a recipe referencing its ops can be validated or run."""

    def deco(fn: StepFn) -> StepFn:
        if name in STEPS:
            raise ValueError(f"duplicate step registration: {name!r}")
        if tier not in TIERS:
            raise ValueError(f"tier must be one of {TIERS}, got {tier!r}")
        STEPS[name] = StepSpec(name, fn, tuple(produces), tuple(requires), tier)
        return fn

    return deco


def validate_recipe(recipe: dict) -> None:
    """Raise RecipeError if the recipe cannot run. Checks unknown ops, duplicate ids, and
    that every enabled step's requirements are produced by an EARLIER enabled step."""
    have: set[str] = set(SEED_COLUMNS)
    seen: set[str] = set()
    for s in recipe.get("steps", []):
        sid = s.get("id")
        if sid in seen:
            raise RecipeError(f"duplicate step id {sid!r}")
        seen.add(sid)
        op = s.get("op")
        if op not in STEPS:
            raise RecipeError(f"unknown op {op!r} in step {sid!r}")
        if not s.get("on", True):
            continue
        spec = STEPS[op]
        missing = [c for c in spec.requires if c not in have]
        if missing:
            raise RecipeError(
                f"step {sid!r} ({op}) requires {missing}, which no earlier enabled step "
                f"produces"
            )
        have.update(spec.produces)
