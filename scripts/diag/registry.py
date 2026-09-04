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

from .layers import rasterize_polygons

Columns = dict[str, np.ndarray]
StepFn = Callable[[Columns, dict[str, Any], dict[str, Any]], tuple[Columns, dict]]

# The RESOLVED shape a step's fn receives as its third argument. Each declared input name maps
# to one of:
#   - a per-point boolean array  (a {"layer": name} binding, True = inside the painted region)
#   - None                       (a {"layer": name} binding whose optional layer is absent)
#   - an insertion-ordered dict {layer_name: bool_array}  (a {"layers": [names]} binding, e.g.
#     grow_segmentation's seed classes -- order is the recipe's, and it is semantic)
Inputs = dict[str, "np.ndarray | None | dict[str, np.ndarray]"]

# Columns present before any step runs, seeded by the runner from the D1LC cache and the
# D1OC spiral. x_raw/y_raw are MATLAB's own geometry, never recomputed here.
SEED_COLUMNS: tuple[str, ...] = (
    "t_raw", "fx", "fy", "fz", "rpm", "revs", "x_raw", "y_raw",
)

TIERS = ("base", "derived")

# What kind of thing a step does, for the step PICKER only -- the pipeline itself stays a flat
# ordered list, because step order is semantic (radial_detrend must run before getis_ord) and
# grouping the list itself would hide that. 'transform' reshapes the raw signal into the
# working frame; 'residual' extracts what departs from the expected signal; 'interpolation'
# fills gaps; 'statistics' scores points against their neighbourhood; 'segmentation' assigns
# points to discrete groups.
CATEGORIES = ("transform", "residual", "interpolation", "statistics", "segmentation")


@dataclass(frozen=True)
class StepSpec:
    name: str
    fn: StepFn
    produces: tuple[str, ...]
    requires: tuple[str, ...]
    tier: str
    category: str


STEPS: dict[str, StepSpec] = {}


class RecipeError(ValueError):
    """A recipe that cannot be executed as written."""


def step(name: str, *, produces: list[str], requires: list[str], tier: str, category: str):
    """Register a step function. Import-time side effect, so diag.ops must be imported
    before a recipe referencing its ops can be validated or run."""

    def deco(fn: StepFn) -> StepFn:
        if name in STEPS:
            raise ValueError(f"duplicate step registration: {name!r}")
        if tier not in TIERS:
            raise ValueError(f"tier must be one of {TIERS}, got {tier!r}")
        if category not in CATEGORIES:
            raise ValueError(f"category must be one of {CATEGORIES}, got {category!r}")
        STEPS[name] = StepSpec(name, fn, tuple(produces), tuple(requires), tier, category)
        return fn

    return deco


def resolve_inputs(step: dict, layers: dict | None, x, y) -> Inputs:
    """Resolve a step's declared `inputs` bindings into per-point boolean arrays.

    At rest a binding is {"layer": <name>, "required": <bool>}. This looks the named layer up
    in `layers` (the request/DB-supplied {name: {role, geometry, value, version}} dict),
    rasterises its polygons against (x, y) -- the angular-grid coords AT THIS STEP -- and
    hands the step {key: bool_array}. True = the point is inside the painted region.

    A binding on a 'base'-tier step raises: before angular_resample, (x, y) are the
    cache-resolution coords, wrong in both length and coordinate space. DEFAULT_RECIPE binds
    nothing, so neither this nor the length assertion fires today.
    """
    bindings = step.get("inputs") or {}
    if not bindings:
        return {}
    op = step.get("op")
    if op in STEPS and STEPS[op].tier == "base":
        raise RecipeError(
            f"layer bindings are only valid on derived-tier steps; {op!r} is base"
        )
    xa = np.asarray(x)
    out: Inputs = {}
    for key, binding in bindings.items():
        # List mode: {"layers": [names]} -> ordered {name: bool_array}, one per resolvable
        # layer (missing layers skipped, not None-entried). Recipe order is preserved and
        # semantic (e.g. grow_segmentation's seed layers ARE the class indices).
        if "layers" in binding:
            resolved: dict[str, np.ndarray] = {}
            for lname in binding["layers"]:
                layer = (layers or {}).get(lname)
                if layer is None:
                    continue
                arr = rasterize_polygons(layer["geometry"], x, y)
                if arr.shape != xa.shape:
                    raise RecipeError(
                        f"layer {lname!r} rasterised to {arr.shape}, "
                        f"step {op!r} expects {xa.shape}"
                    )
                resolved[lname] = arr
            if not resolved and binding.get("required"):
                raise RecipeError(
                    f"step {op!r} requires input {key!r} but no bound layer resolved"
                )
            out[key] = resolved
            continue
        name = binding.get("layer")
        layer = (layers or {}).get(name)
        if layer is None:
            if binding.get("required"):
                raise RecipeError(
                    f"step {op!r} requires layer {name!r} but the cut has none"
                )
            out[key] = None
            continue
        arr = rasterize_polygons(layer["geometry"], x, y)
        if arr.shape != xa.shape:
            raise RecipeError(
                f"layer {name!r} rasterised to {arr.shape}, step {op!r} expects {xa.shape}"
            )
        out[key] = arr
    return out


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
