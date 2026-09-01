# Diagnostics Recipe Engine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the diagnostics pipeline's fixed seven-stage sequence into a registry-driven, hashable, editable recipe that the orchestrator executes — without changing a single output byte.

**Architecture:** `scripts/diag` gains four small modules: a recipe schema with prefix hashing, a step registry, the seven existing algorithms registered as steps, and a `run_recipe` executor. `analyse()` becomes a thin wrapper that runs the default recipe, so every existing caller and test keeps working. A golden reference captured *before* any refactoring proves byte-identical equivalence. Phase B then persists the recipe per cut, publishes a `base.d1an` intermediate for the future preview service, and extends `claim_diag` to requeue on either a code change or a recipe change.

**Tech Stack:** Python 3.13, NumPy, SciPy, scikit-learn, psycopg2, pytest, dbmate (via Docker).

**Spec:** `docs/superpowers/specs/2026-09-01-diagnostics-recipe-workbench-design.md`

## Global Constraints

- All computation stays server-side. Nothing in this plan adds browser-side computation.
- `scripts/diag/` must remain free of database, subprocess and MATLAB imports — it is imported by both the orchestrator and (later) a service container. This is stated in its own `__init__.py` and is load-bearing.
- The default recipe must reproduce today's `analyse()` byte-for-byte. Any deviation is a bug, not an improvement.
- `process_force.m` remains the sole owner of cut geometry. No task recomputes `x`/`y`.
- Run tests from the repo root with `py -m pytest tests/scripts/diag/ -v`.
- Lint with `py -m ruff check scripts/`. It must pass before every commit.
- Existing column names are fixed by the D1AN contract and the browser reader: `t, rev, x, y, tsa_resid, resid_z, gi_star, gi_sig, cluster_id, glosh, env_band`.

---

## File Structure

| File | Responsibility |
|---|---|
| `scripts/diag/recipe.py` | **Create.** Recipe/Step schema, `DEFAULT_RECIPE`, canonicalisation, `recipe_hash` / `prefix_hash`. No algorithms. |
| `scripts/diag/registry.py` | **Create.** The `@step` decorator, `STEPS` table, `StepSpec`, `SEED_COLUMNS`, `validate_recipe`. Mechanism only. |
| `scripts/diag/ops.py` | **Create.** The seven algorithms registered as steps. Thin adapters over `angular.py` / `detrend.py` / `spatial.py` / `envelope.py` / `frames.py`, which are not modified. |
| `scripts/diag/runner.py` | **Create.** `run_recipe()` — walks steps, skips disabled, merges columns and metrics. |
| `scripts/diag/pipeline.py` | **Modify.** `analyse()` delegates to `run_recipe(DEFAULT_RECIPE, ...)`; signature unchanged. |
| `tests/scripts/diag/fixtures/golden_default_recipe.npz` | **Create.** Frozen output of today's `analyse()`. The safety net. |
| `tests/scripts/diag/test_recipe.py` | **Create.** Hash stability and canonicalisation. |
| `tests/scripts/diag/test_registry.py` | **Create.** Registration and ordering validation. |
| `tests/scripts/diag/test_runner.py` | **Create.** Executor behaviour + the golden equivalence test. |
| `db/migrations/20260901000106_diag_recipe.sql` | **Create.** `diag_recipe`, `diag_recipe_hash`, `diag_recipes` library table. |
| `scripts/force_orchestrator.py` | **Modify.** Publish `base.d1an`, run the row's recipe, dual-axis `claim_diag`. |

---

## Task 1: Capture the golden reference

Must happen **first**, before any refactoring — its whole value is that it records behaviour that exists now.

**Files:**
- Create: `tests/scripts/diag/fixtures/golden_default_recipe.npz`
- Create: `tests/scripts/diag/conftest.py`
- Create: `scripts/diag/_capture_golden.py` (throwaway; deleted in Task 7)

**Interfaces:**
- Consumes: nothing.
- Produces: `synthetic_cut()` pytest fixture returning `(cache: dict, x: np.ndarray, y: np.ndarray)`; an `.npz` holding every column `analyse()` returns.

- [ ] **Step 1: Extract the synthetic cut into a shared fixture**

`tests/scripts/diag/test_pipeline.py` defines `_synthetic_cut` privately. Move it to a conftest so Task 6 can use the identical input. Create `tests/scripts/diag/conftest.py`:

```python
import os
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", "scripts"))

SPR = 256


def synthetic_cut(n_rev=40, spr=SPR, anomaly_rev=25.0, anomaly_span=0.05):
    """A clean spiral with one implanted force anomaly at a known revolution.

    Seeded (default_rng(7)) so the golden reference is reproducible. Identical to the
    fixture test_pipeline.py used privately before this was extracted.
    """
    n = n_rev * spr
    revs = np.arange(n, dtype=np.float64) / spr
    fs = 25_000.0
    t = revs * 60.0 / 1200.0
    phase = 2 * np.pi * revs
    fz = 120.0 + 4.0 * np.sin(phase) + 1.5 * np.sin(3 * phase)
    rng = np.random.default_rng(7)
    fz = fz + rng.normal(scale=0.4, size=n)
    hit = np.abs(revs - anomaly_rev) < anomaly_span
    fz[hit] += 30.0
    fx = np.zeros(n)
    fy = np.zeros(n)
    rpm = np.full(n, 1200.0)
    rho = 40.0 - 0.05 * revs
    x, y = rho * np.cos(phase), rho * np.sin(phase)
    return t, fx, fy, fz, rpm, revs, x, y, fs, hit


def cache_of(t, fx, fy, fz, rpm, revs, fs):
    return {
        "n": t.size, "fs": fs, "feed": 0.05, "diam": 80.0,
        "cs_sec": 0.0, "ce_sec": float(t[-1]),
        "t": t, "fx": fx, "fy": fy, "fz": fz, "rpm": rpm, "revs": revs,
    }


@pytest.fixture
def standard_cut():
    """(cache, x, y) for the 40-revolution reference cut."""
    t, fx, fy, fz, rpm, revs, x, y, fs, _ = synthetic_cut()
    return cache_of(t, fx, fy, fz, rpm, revs, fs), x, y
```

- [ ] **Step 2: Write the capture script**

Create `scripts/diag/_capture_golden.py`:

```python
"""One-shot: freeze today's analyse() output as the refactor's golden reference.

Deleted once the registry refactor is proven equivalent (see the plan's Task 7). Run from
the repo root:  py scripts/diag/_capture_golden.py
"""

from __future__ import annotations

import os
import sys

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from tests.scripts.diag.conftest import cache_of, synthetic_cut  # noqa: E402

from diag.pipeline import analyse  # noqa: E402

OUT = os.path.join(
    os.path.dirname(__file__), "..", "..",
    "tests", "scripts", "diag", "fixtures", "golden_default_recipe.npz",
)


def main() -> None:
    t, fx, fy, fz, rpm, revs, x, y, fs, _ = synthetic_cut()
    cols, metrics = analyse(cache_of(t, fx, fy, fz, rpm, revs, fs), x, y, samples_per_rev=256)
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    np.savez_compressed(OUT, **cols, __metrics__=np.array(repr(sorted(metrics.items()))))
    print(f"wrote {OUT}: {len(cols)} columns, n={cols['t'].size}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 3: Run it and confirm the fixture exists**

Run: `py scripts/diag/_capture_golden.py`
Expected: `wrote ...golden_default_recipe.npz: 11 columns, n=10240`

- [ ] **Step 4: Point the existing test at the shared fixture**

In `tests/scripts/diag/test_pipeline.py`, delete the private `_synthetic_cut` definition and import it instead. Replace the top-of-file block so it reads:

```python
from conftest import cache_of, synthetic_cut  # noqa: F401

_synthetic_cut = synthetic_cut
```

- [ ] **Step 5: Run the existing suite to prove nothing moved**

Run: `py -m pytest tests/scripts/diag/ -v`
Expected: PASS — all 45 tests, unchanged.

- [ ] **Step 6: Commit**

```bash
git add tests/scripts/diag/conftest.py tests/scripts/diag/fixtures/golden_default_recipe.npz \
        tests/scripts/diag/test_pipeline.py scripts/diag/_capture_golden.py
git commit -m "test(diag): freeze analyse()'s output as a golden reference before the recipe refactor"
```

---

## Task 2: Recipe schema and prefix hashing

**Files:**
- Create: `scripts/diag/recipe.py`
- Test: `tests/scripts/diag/test_recipe.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `RECIPE_VERSION: int`, `DEFAULT_RECIPE: dict`, `enabled_steps(recipe) -> list[dict]`, `prefix_hash(recipe, upto_index: int | None = None) -> str` (16 hex chars), `recipe_hash(recipe) -> str`.

- [ ] **Step 1: Write the failing test**

Create `tests/scripts/diag/test_recipe.py`:

```python
import copy

from diag.recipe import DEFAULT_RECIPE, enabled_steps, prefix_hash, recipe_hash


def test_default_recipe_is_well_formed():
    assert DEFAULT_RECIPE["recipe_version"] == 1
    ids = [s["id"] for s in DEFAULT_RECIPE["steps"]]
    assert len(ids) == len(set(ids)), "step ids must be unique"
    assert [s["op"] for s in DEFAULT_RECIPE["steps"]][:3] == [
        "frame_transform", "angular_resample", "tsa",
    ]


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
    next(s for s in b["steps"] if s["op"] == "hdbscan")["params"]["min_cluster_size"] = 99
    idx = next(i for i, s in enumerate(a["steps"]) if s["op"] == "getis_ord")
    assert prefix_hash(a, idx) == prefix_hash(b, idx)
    assert recipe_hash(a) != recipe_hash(b)


def test_enabled_steps_filters():
    n_on = sum(1 for s in DEFAULT_RECIPE["steps"] if s.get("on", True))
    assert len(enabled_steps(DEFAULT_RECIPE)) == n_on
```

- [ ] **Step 2: Run it to verify it fails**

Run: `py -m pytest tests/scripts/diag/test_recipe.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'diag.recipe'`

- [ ] **Step 3: Implement the module**

Create `scripts/diag/recipe.py`:

```python
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
# value here changes every cut's recipe_hash, so treat it as a schema change.
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


def enabled_steps(recipe: dict) -> list[dict]:
    return [s for s in recipe.get("steps", []) if s.get("on", True)]


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
    payload = [_canonical(s) for s in steps if s.get("on", True)]
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


def recipe_hash(recipe: dict) -> str:
    return prefix_hash(recipe, None)
```

- [ ] **Step 4: Run the tests**

Run: `py -m pytest tests/scripts/diag/test_recipe.py -v`
Expected: PASS — 7 tests.

- [ ] **Step 5: Lint and commit**

```bash
py -m ruff check scripts/diag/
git add scripts/diag/recipe.py tests/scripts/diag/test_recipe.py
git commit -m "feat(diag): add the recipe schema and prefix hashing"
```

---

## Task 3: The step registry

**Files:**
- Create: `scripts/diag/registry.py`
- Test: `tests/scripts/diag/test_registry.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `Columns = dict[str, np.ndarray]`; `StepSpec` (frozen dataclass: `name, fn, produces, requires, tier`); `STEPS: dict[str, StepSpec]`; `step(name, *, produces, requires, tier)` decorator; `SEED_COLUMNS: tuple[str, ...]`; `RecipeError(ValueError)`; `validate_recipe(recipe) -> None`. Step functions have signature `fn(cols: Columns, params: dict, inputs: dict) -> tuple[Columns, dict]` returning **new columns only** and a metrics fragment.

- [ ] **Step 1: Write the failing test**

Create `tests/scripts/diag/test_registry.py`:

```python
import numpy as np
import pytest

from diag import ops  # noqa: F401  -- registers the built-in steps
from diag.recipe import DEFAULT_RECIPE
from diag.registry import STEPS, RecipeError, validate_recipe


def test_all_default_recipe_ops_are_registered():
    for s in DEFAULT_RECIPE["steps"]:
        assert s["op"] in STEPS, f"{s['op']} is not registered"


def test_default_recipe_validates():
    validate_recipe(DEFAULT_RECIPE)


def test_unknown_op_is_rejected():
    bad = {"recipe_version": 1, "name": "x",
           "steps": [{"id": "a", "op": "does_not_exist", "on": True, "params": {}}]}
    with pytest.raises(RecipeError, match="unknown op"):
        validate_recipe(bad)


def test_duplicate_step_id_is_rejected():
    bad = {"recipe_version": 1, "name": "x", "steps": [
        {"id": "a", "op": "frame_transform", "on": True, "params": {"channel": "fp", "mount_deg": 0.0}},
        {"id": "a", "op": "frame_transform", "on": True, "params": {"channel": "fp", "mount_deg": 0.0}},
    ]}
    with pytest.raises(RecipeError, match="duplicate step id"):
        validate_recipe(bad)


def test_out_of_order_step_is_rejected():
    """radial_detrend consumes tsa_resid, so it cannot precede tsa. The editor relies on
    this to refuse an illegal insertion before anything runs."""
    bad = {"recipe_version": 1, "name": "x", "steps": [
        {"id": "a", "op": "frame_transform", "on": True, "params": {"channel": "fp", "mount_deg": 0.0}},
        {"id": "b", "op": "angular_resample", "on": True, "params": {"samples_per_rev": 256}},
        {"id": "c", "op": "radial_detrend", "on": True, "params": {"n_bins": 200, "min_per_bin": 8}},
    ]}
    with pytest.raises(RecipeError, match="requires"):
        validate_recipe(bad)


def test_disabled_step_does_not_satisfy_a_requirement():
    """A switched-off step produces nothing, so a later step depending on it is invalid."""
    bad = {"recipe_version": 1, "name": "x", "steps": [
        {"id": "a", "op": "frame_transform", "on": True, "params": {"channel": "fp", "mount_deg": 0.0}},
        {"id": "b", "op": "angular_resample", "on": True, "params": {"samples_per_rev": 256}},
        {"id": "c", "op": "tsa", "on": False, "params": {}},
        {"id": "d", "op": "radial_detrend", "on": True, "params": {"n_bins": 200, "min_per_bin": 8}},
    ]}
    with pytest.raises(RecipeError, match="requires"):
        validate_recipe(bad)


def test_every_step_declares_a_valid_tier():
    for spec in STEPS.values():
        assert spec.tier in ("base", "derived")


def test_envelope_is_base_tier():
    """envelope.py is explicitly full-rate time-domain -- the Hz content the angular domain
    discards -- so retuning it costs a re-bake. The UI depends on this being declared."""
    assert STEPS["envelope"].tier == "base"


def test_step_functions_return_columns_and_metrics():
    spec = STEPS["frame_transform"]
    n = 16
    cols = {k: np.ones(n) for k in ("fx", "fy", "fz")}
    new, metrics = spec.fn(cols, {"channel": "fp", "mount_deg": 0.0}, {})
    assert set(spec.produces) <= set(new)
    assert isinstance(metrics, dict)
```

- [ ] **Step 2: Run it to verify it fails**

Run: `py -m pytest tests/scripts/diag/test_registry.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'diag.registry'`

- [ ] **Step 3: Implement the registry**

Create `scripts/diag/registry.py`:

```python
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

from dataclasses import dataclass
from typing import Any, Callable

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
```

- [ ] **Step 4: Run the tests — they will still fail on `diag.ops`**

Run: `py -m pytest tests/scripts/diag/test_registry.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'diag.ops'`. That is correct; Task 4 supplies it.

- [ ] **Step 5: Commit the mechanism**

```bash
py -m ruff check scripts/diag/
git add scripts/diag/registry.py tests/scripts/diag/test_registry.py
git commit -m "feat(diag): add the step registry and recipe validation"
```

---

## Task 4: Register the seven algorithms as steps

**Files:**
- Create: `scripts/diag/ops.py`
- Test: `tests/scripts/diag/test_registry.py` (written in Task 3, passes here)

**Interfaces:**
- Consumes: `step`, `Columns` from `registry`; the existing `angular`, `detrend`, `frames`, `spatial`, `envelope` modules, none of which are modified.
- Produces: registrations for `frame_transform` (→ `fc, ff, fp`), `angular_resample` (→ `t, rev, x, y, sig`), `tsa` (→ `tsa_resid`), `radial_detrend` (→ `resid_z`), `getis_ord` (→ `gi_star, gi_sig`), `hdbscan` (→ `cluster_id, glosh`), `envelope` (→ `env_band`).

- [ ] **Step 1: Implement the ops module**

Create `scripts/diag/ops.py`:

```python
"""The seven analysis stages, registered as recipe steps.

Thin adapters only. Every algorithm still lives in angular.py / detrend.py / frames.py /
spatial.py / envelope.py, which this module does not modify -- their unit tests remain the
authority on the science. What is added here is the contract (produces / requires / tier)
that makes the sequence editable and the produced channels discoverable.

Column vocabulary:
    seeded    t_raw fx fy fz rpm revs x_raw y_raw      (D1LC cache + D1OC spiral)
    derived   fc ff fp                                  frame_transform
              t rev x y sig                             angular_resample
              tsa_resid                                 tsa
              resid_z                                   radial_detrend
              gi_star gi_sig                            getis_ord
              cluster_id glosh                          hdbscan
              env_band                                  envelope
"""

from __future__ import annotations

import numpy as np

from .angular import angular_resample, order_spectrum, tsa as _tsa
from .detrend import radial_detrend as _radial_detrend
from .envelope import bandpass_envelope, envelope_spectrum
from .frames import frame_transform as _frame_transform
from .registry import Columns, step
from .spatial import (
    assign_from_grid,
    benjamini_hochberg,
    cluster_hdbscan,
    getis_ord_gi_star,
    grid_reduce,
)

_CHANNELS = ("fc", "ff", "fp")


@step("frame_transform", produces=["fc", "ff", "fp"],
      requires=["fx", "fy", "fz"], tier="base")
def _op_frame_transform(cols: Columns, params: dict, inputs: dict):
    h = params.get("h_matrix")
    fx, fy, fz = cols["fx"], cols["fy"], cols["fz"]
    if h is not None:
        hm = np.asarray(h, dtype=np.float64)
        if hm.shape != (3, 3):
            raise ValueError(f"h_matrix must be 3x3, got shape {hm.shape}")
        corrected = hm @ np.vstack([fx, fy, fz])
        fx, fy, fz = corrected[0], corrected[1], corrected[2]
    mount_deg = float(params.get("mount_deg", 0.0))
    fc, ff, fp = _frame_transform(fx, fy, fz, mount_deg)
    return {"fc": fc, "ff": ff, "fp": fp}, {
        "mount_deg": mount_deg,
        "h_matrix_applied": h is not None,
        "channel": params.get("channel", "fp"),
    }


@step("angular_resample", produces=["t", "rev", "x", "y", "sig"],
      requires=["revs", "t_raw", "x_raw", "y_raw", "fc", "ff", "fp"], tier="base")
def _op_angular_resample(cols: Columns, params: dict, inputs: dict):
    spr = int(params.get("samples_per_rev", 256))
    channel = str(params.get("channel", "fp"))
    if channel not in _CHANNELS:
        raise ValueError(f"channel must be one of {_CHANNELS}, got {channel!r}")
    revs = np.asarray(cols["revs"], dtype=np.float64)
    rev_grid, sig = angular_resample(revs, cols[channel], spr)
    _, t = angular_resample(revs, np.asarray(cols["t_raw"], dtype=np.float64), spr)
    _, x = angular_resample(revs, np.asarray(cols["x_raw"], dtype=np.float64), spr)
    _, y = angular_resample(revs, np.asarray(cols["y_raw"], dtype=np.float64), spr)
    return {"t": t, "rev": rev_grid, "x": x, "y": y, "sig": sig}, {
        "samples_per_rev": spr,
    }


@step("tsa", produces=["tsa_resid"], requires=["sig"], tier="derived")
def _op_tsa(cols: Columns, params: dict, inputs: dict):
    spr = int(params.get("samples_per_rev") or 0)
    if not spr:
        spr = int(round(1.0 / float(cols["rev"][1] - cols["rev"][0])))
    signature, residual = _tsa(cols["sig"], spr)
    n = residual.size
    orders, amp = order_spectrum(cols["sig"], spr)
    keep = orders <= 16.0
    # TSA truncates to whole revolutions, so every column carried forward must be cut to
    # the residual's length. The runner applies this via the returned "__truncate__" key.
    return {"tsa_resid": residual, "__truncate__": np.array(n)}, {
        "n_points": int(n),
        "n_revolutions": int(n // spr),
        "tsa_signature": [float(v) for v in signature],
        "order_spectrum": {
            "orders": [float(v) for v in orders[keep]],
            "amplitude": [float(v) for v in amp[keep]],
        },
    }


@step("radial_detrend", produces=["resid_z"],
      requires=["tsa_resid", "x", "y"], tier="derived")
def _op_radial_detrend(cols: Columns, params: dict, inputs: dict):
    r = np.hypot(cols["x"], cols["y"])
    z = _radial_detrend(
        r, cols["tsa_resid"],
        n_bins=int(params.get("n_bins", 200)),
        min_per_bin=int(params.get("min_per_bin", 8)),
    )
    return {"resid_z": z}, {
        "resid_z_p99": float(np.percentile(np.abs(z), 99)) if z.size else 0.0,
    }


@step("getis_ord", produces=["gi_star", "gi_sig"],
      requires=["x", "y", "resid_z"], tier="derived")
def _op_getis_ord(cols: Columns, params: dict, inputs: dict):
    k = int(params.get("k", 30))
    alpha = float(params.get("alpha", 0.05))
    n = cols["resid_z"].size
    # Degrade rather than raise: a short test cut can have fewer points than Gi* needs, and
    # crashing the whole pipeline over one statistic is the wrong trade. Matches analyse().
    if n > k:
        gi, p = getis_ord_gi_star(cols["x"], cols["y"], cols["resid_z"], k=k)
        sig = benjamini_hochberg(p, alpha=alpha).astype(np.float64)
    else:
        gi, sig = np.zeros(n), np.zeros(n)
    return {"gi_star": gi, "gi_sig": sig}, {}


@step("hdbscan", produces=["cluster_id", "glosh"],
      requires=["x", "y", "resid_z"], tier="derived")
def _op_hdbscan(cols: Columns, params: dict, inputs: dict):
    target = int(params.get("grid_target", 20000))
    min_size = int(params.get("min_cluster_size", 10))
    n = cols["resid_z"].size
    xr, yr, vr, cell_id = grid_reduce(cols["x"], cols["y"], cols["resid_z"], target_n=target)
    if xr.size >= min_size:
        labels, glosh = cluster_hdbscan(xr, yr, vr, min_cluster_size=min_size)
        cluster_id, glosh = assign_from_grid(cell_id, labels, glosh)
    else:
        cluster_id, glosh = np.full(n, -1.0), np.zeros(n)
    return {"cluster_id": cluster_id, "glosh": glosh}, {}


@step("envelope", produces=["env_band"],
      requires=["fc", "ff", "fp", "revs", "t_raw"], tier="base")
def _op_envelope(cols: Columns, params: dict, inputs: dict):
    """Full-rate, time-domain. This is why the step is 'base' tier despite running last:
    the modulation rate it recovers lives in Hz, which the angular domain discards."""
    n = cols["tsa_resid"].size
    fn_hz = params.get("fn_hz")
    channel = str(params.get("channel", "fp"))
    spr = int(params.get("samples_per_rev", 256))
    t_in = np.asarray(cols["t_raw"], dtype=np.float64)
    span = float(t_in[-1] - t_in[0]) if t_in.size > 1 else 0.0
    eff_fs = (t_in.size / span) if span > 0 else 0.0
    if fn_hz is None or float(fn_hz) <= 0:
        return {"env_band": np.zeros(n)}, {
            "env_band_status": "refused: dyno_fn_hz not provided",
        }
    fn_hz = float(fn_hz)
    frac = float(params.get("bandwidth_frac", 0.2))
    hi_needed = fn_hz + fn_hz * (frac / 2.0)
    nyquist = eff_fs / 2.0
    if nyquist <= hi_needed:
        return {"env_band": np.zeros(n)}, {
            "env_band_status": (
                f"refused: effective_nyquist_hz ({nyquist:.1f}) below required "
                f"{hi_needed:.1f} Hz for the resonance band"
            ),
        }
    env = bandpass_envelope(cols[channel], eff_fs, f_center=fn_hz, bandwidth_frac=frac)
    _, env_ang = angular_resample(np.asarray(cols["revs"], dtype=np.float64), env, spr)
    ef, ea = envelope_spectrum(env, eff_fs, max_freq=nyquist)
    return {"env_band": env_ang[:n]}, {
        "env_band_status": "computed",
        "dyno_fn_hz": fn_hz,
        "quantitative_limit_hz": fn_hz / 5.0,
        "envelope_spectrum": {
            "freqs": [float(v) for v in ef],
            "amplitude": [float(v) for v in ea],
        },
    }
```

- [ ] **Step 2: Run the registry tests**

Run: `py -m pytest tests/scripts/diag/test_registry.py -v`
Expected: PASS — 9 tests.

- [ ] **Step 3: Lint and commit**

```bash
py -m ruff check scripts/diag/
git add scripts/diag/ops.py
git commit -m "feat(diag): register the seven analysis stages as recipe steps"
```

---

## Task 5: The `run_recipe` executor

**Files:**
- Create: `scripts/diag/runner.py`
- Test: `tests/scripts/diag/test_runner.py`

**Interfaces:**
- Consumes: `STEPS`, `SEED_COLUMNS`, `validate_recipe`, `Columns` from `registry`; `enabled_steps` from `recipe`; `diag.ops` for its registrations.
- Produces: `seed_columns(cache, x, y) -> Columns`; `run_recipe(recipe, cols, *, layers=None, from_step=None) -> tuple[Columns, dict]`. The returned columns exclude the internal `sig` and `__truncate__` keys and every seed column, matching `analyse()`'s public column set.

- [ ] **Step 1: Write the failing test**

Create `tests/scripts/diag/test_runner.py`:

```python
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


def test_invalid_recipe_is_refused_before_any_work():
    bad = copy.deepcopy(DEFAULT_RECIPE)
    bad["steps"] = [s for s in bad["steps"] if s["op"] != "tsa"]
    with pytest.raises(RecipeError, match="requires"):
        run_recipe(bad, _seed())


def test_from_step_reuses_supplied_columns():
    """Preview's core optimisation: given the columns as of step 4, running from step 5
    must reproduce the same final result as a full run."""
    full, _ = run_recipe(DEFAULT_RECIPE, _seed())
    idx = next(i for i, s in enumerate(DEFAULT_RECIPE["steps"]) if s["op"] == "getis_ord")
    prefix, _ = run_recipe(DEFAULT_RECIPE, _seed(), from_step=None, stop_after=idx - 1)
    resumed, _ = run_recipe(DEFAULT_RECIPE, prefix, from_step=idx)
    np.testing.assert_array_equal(resumed["gi_star"], full["gi_star"])
    np.testing.assert_array_equal(resumed["cluster_id"], full["cluster_id"])
```

- [ ] **Step 2: Run it to verify it fails**

Run: `py -m pytest tests/scripts/diag/test_runner.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'diag.runner'`

- [ ] **Step 3: Implement the runner**

Create `scripts/diag/runner.py`:

```python
"""Recipe execution. One code path, two callers.

The orchestrator's bake and (later) the preview service both import this function, which is
what makes "what you tuned is what you baked" a structural guarantee rather than a
convention: they cannot drift because there is only one implementation.
"""

from __future__ import annotations

from typing import Any

import numpy as np

from . import ops  # noqa: F401  -- import for its registration side effects
from .registry import SEED_COLUMNS, STEPS, Columns, validate_recipe

# The D1AN contract: exactly these columns, always, in this order. A disabled step still
# contributes its column (zero-filled) because the browser's reader indexes by name and a
# missing column is a parse error, not an absence.
PUBLIC_COLUMNS: tuple[str, ...] = (
    "t", "rev", "x", "y", "tsa_resid", "resid_z",
    "gi_star", "gi_sig", "cluster_id", "glosh", "env_band",
)


def seed_columns(cache: dict, x: np.ndarray, y: np.ndarray) -> Columns:
    """The pre-step column set, from the D1LC cache and the D1OC spiral coordinates.

    x/y are MATLAB's own geometry, passed through untouched -- process_force.m remains the
    sole owner of the spiral, the cut window and drift compensation.
    """
    return {
        "t_raw": np.asarray(cache["t"], dtype=np.float64),
        "fx": np.asarray(cache["fx"], dtype=np.float64),
        "fy": np.asarray(cache["fy"], dtype=np.float64),
        "fz": np.asarray(cache["fz"], dtype=np.float64),
        "rpm": np.asarray(cache["rpm"], dtype=np.float64),
        "revs": np.asarray(cache["revs"], dtype=np.float64),
        "x_raw": np.asarray(x, dtype=np.float64),
        "y_raw": np.asarray(y, dtype=np.float64),
    }


def _truncate(cols: Columns, n: int) -> Columns:
    """TSA keeps whole revolutions only, so every angular-domain column shortens with it.
    Seed columns stay at raw length: `envelope` is full-rate and still needs them."""
    out = {}
    for k, v in cols.items():
        out[k] = v[:n] if (k not in SEED_COLUMNS and v.ndim == 1 and v.size >= n) else v
    return out


def run_recipe(
    recipe: dict,
    cols: Columns,
    *,
    layers: dict[str, Any] | None = None,
    from_step: int | None = None,
    stop_after: int | None = None,
) -> tuple[Columns, dict]:
    """Execute `recipe` over `cols`.

    `from_step` and `stop_after` index the FULL step list (disabled steps included), so a
    caller can address a step positionally as the UI does. `from_step` assumes `cols`
    already holds everything the earlier steps produced -- that is the preview path, where
    a cached prefix is resumed rather than recomputed.
    """
    validate_recipe(recipe)
    steps = recipe.get("steps", [])
    metrics: dict = {}
    work: Columns = dict(cols)

    for i, s in enumerate(steps):
        if from_step is not None and i < from_step:
            continue
        if stop_after is not None and i > stop_after:
            break
        if not s.get("on", True):
            continue
        spec = STEPS[s["op"]]
        params = dict(s.get("params") or {})
        # samples_per_rev is set once, on angular_resample, but tsa and envelope both need
        # it. Thread it through rather than duplicating it in every step's params, which
        # would let the two drift apart.
        if "samples_per_rev" not in params:
            for earlier in steps:
                if earlier["op"] == "angular_resample":
                    params.setdefault(
                        "samples_per_rev",
                        int((earlier.get("params") or {}).get("samples_per_rev", 256)),
                    )
                    break
        if "channel" not in params:
            for earlier in steps:
                if earlier["op"] == "frame_transform":
                    params.setdefault(
                        "channel", (earlier.get("params") or {}).get("channel", "fp")
                    )
                    break
        produced, frag = spec.fn(work, params, (layers or {}))
        n_trunc = produced.pop("__truncate__", None)
        work.update(produced)
        if n_trunc is not None:
            work = _truncate(work, int(n_trunc))
        metrics.update(frag)

    n = int(work["tsa_resid"].size) if "tsa_resid" in work else 0
    out: Columns = {}
    for name in PUBLIC_COLUMNS:
        col = work.get(name)
        out[name] = (
            np.asarray(col[:n], dtype=np.float32) if col is not None
            else np.zeros(n, dtype=np.float32)
        )
    return out, metrics
```

- [ ] **Step 4: Run the tests**

Run: `py -m pytest tests/scripts/diag/test_runner.py -v`
Expected: PASS — 6 tests.

- [ ] **Step 5: Lint and commit**

```bash
py -m ruff check scripts/diag/
git add scripts/diag/runner.py tests/scripts/diag/test_runner.py
git commit -m "feat(diag): add the run_recipe executor"
```

---

## Task 6: Prove equivalence against the golden reference

The task the whole refactor exists to be safe under.

**Files:**
- Modify: `tests/scripts/diag/test_runner.py`

**Interfaces:**
- Consumes: `run_recipe`, `seed_columns`, `DEFAULT_RECIPE`, the Task 1 fixture.
- Produces: nothing new.

- [ ] **Step 1: Write the failing test**

Append to `tests/scripts/diag/test_runner.py`:

```python
import os

GOLDEN = os.path.join(os.path.dirname(__file__), "fixtures", "golden_default_recipe.npz")


def test_default_recipe_reproduces_the_frozen_analyse_output_exactly():
    """The equivalence gate. The golden .npz was captured from analyse() BEFORE the registry
    existed (see the plan's Task 1), so this compares the new pipeline against the old one's
    recorded behaviour rather than against itself. Exact equality, not allclose: this is a
    refactor, so any numerical difference at all is a defect."""
    golden = np.load(GOLDEN, allow_pickle=False)
    cols, _ = run_recipe(DEFAULT_RECIPE, _seed())
    expected = {k: golden[k] for k in golden.files if not k.startswith("__")}
    assert set(cols) == set(expected), "column set drifted from the frozen reference"
    for name, want in expected.items():
        np.testing.assert_array_equal(
            cols[name], want, err_msg=f"column {name!r} differs from the golden reference"
        )
```

- [ ] **Step 2: Run it**

Run: `py -m pytest tests/scripts/diag/test_runner.py::test_default_recipe_reproduces_the_frozen_analyse_output_exactly -v`
Expected: PASS. If it FAILS, the registry pipeline is not equivalent — fix `ops.py`/`runner.py` until it passes. **Do not regenerate the golden file to make this go green**; that would discard the only evidence the refactor is safe.

- [ ] **Step 3: Commit**

```bash
git add tests/scripts/diag/test_runner.py
git commit -m "test(diag): assert the default recipe reproduces analyse() byte-for-byte"
```

---

## Task 7: `analyse()` delegates to the runner

**Files:**
- Modify: `scripts/diag/pipeline.py`
- Delete: `scripts/diag/_capture_golden.py`

**Interfaces:**
- Consumes: `run_recipe`, `seed_columns`, `DEFAULT_RECIPE`.
- Produces: `analyse()` keeps its exact public signature and return type, so `process_diag_row` and every existing test are unaffected.

- [ ] **Step 1: Replace analyse()'s body**

In `scripts/diag/pipeline.py`, keep the module docstring and the `analyse` signature exactly as they are, and replace the body with a translation from keyword arguments to a recipe:

```python
def analyse(cache, x, y, *, mount_deg=0.0, h_matrix=None, samples_per_rev=DEFAULT_SAMPLES_PER_REV,
            fn_hz=None, channel="fp", gi_k=30, hdbscan_grid_target=20_000,
            hdbscan_min_cluster_size=10, envelope_bandwidth_frac=0.2):
    """Run the default recipe. Retained as the stable entry point for callers that want the
    pipeline's default behaviour with a few knobs, rather than a recipe document: the
    orchestrator's own bake now passes a recipe directly (see process_diag_row)."""
    import copy

    from .recipe import DEFAULT_RECIPE
    from .runner import run_recipe, seed_columns

    recipe = copy.deepcopy(DEFAULT_RECIPE)
    by_op = {s["op"]: s for s in recipe["steps"]}
    by_op["frame_transform"]["params"].update(
        {"channel": channel, "mount_deg": mount_deg, "h_matrix": h_matrix}
    )
    by_op["angular_resample"]["params"]["samples_per_rev"] = samples_per_rev
    by_op["getis_ord"]["params"]["k"] = gi_k
    by_op["hdbscan"]["params"].update(
        {"grid_target": hdbscan_grid_target, "min_cluster_size": hdbscan_min_cluster_size}
    )
    by_op["envelope"]["params"].update(
        {"bandwidth_frac": envelope_bandwidth_frac, "fn_hz": fn_hz}
    )
    by_op["envelope"]["on"] = fn_hz is not None and float(fn_hz) > 0

    cols, metrics = run_recipe(recipe, seed_columns(cache, x, y))
    metrics.setdefault("cached_fs_hz", float(cache.get("fs", 0.0)))
    t_in = np.asarray(cache["t"], dtype=np.float64)
    span = float(t_in[-1] - t_in[0]) if t_in.size > 1 else 0.0
    eff_fs = (t_in.size / span) if span > 0 else 0.0
    metrics.setdefault("effective_fs_hz", eff_fs)
    metrics.setdefault("effective_nyquist_hz", eff_fs / 2.0)
    return cols, metrics
```

- [ ] **Step 2: Run the whole diag suite**

Run: `py -m pytest tests/scripts/diag/ -v`
Expected: PASS — every pre-existing test plus the new ones. The synthetic-anomaly test in `test_pipeline.py` passing here is the proof that the science survived the refactor.

- [ ] **Step 3: Confirm the orchestrator still imports and its version is unchanged**

Run: `py -c "import sys; sys.path.insert(0,'scripts'); import force_orchestrator as fo; print(fo.DIAG_VERSION)"`
Expected: `4`

- [ ] **Step 4: Delete the throwaway capture script**

```bash
git rm scripts/diag/_capture_golden.py
```

- [ ] **Step 5: Lint and commit**

```bash
py -m ruff check scripts/
git add scripts/diag/pipeline.py
git commit -m "refactor(diag): analyse() now runs the default recipe through the registry"
```

---

## Task 8: Persist the recipe

**Files:**
- Create: `db/migrations/20260901000106_diag_recipe.sql`

**Interfaces:**
- Consumes: nothing.
- Produces: `machining_force_analysis.diag_recipe jsonb`, `machining_force_analysis.diag_recipe_hash text`, and the `diag_recipes` library table.

- [ ] **Step 1: Write the migration**

Create `db/migrations/20260901000106_diag_recipe.sql`:

```sql
-- migrate:up
-- The diagnostics pipeline becomes an editable recipe rather than a fixed sequence
-- (docs/superpowers/specs/2026-09-01-diagnostics-recipe-workbench-design.md). Mirrors the
-- filter_chain / filter_profiles pair exactly: a per-cut active document plus a named,
-- reusable library, where applying a library entry copies its document onto the cut.
ALTER TABLE machining_force_analysis
    ADD COLUMN IF NOT EXISTS diag_recipe      jsonb,
    ADD COLUMN IF NOT EXISTS diag_recipe_hash text;

COMMENT ON COLUMN machining_force_analysis.diag_recipe IS
    'The recipe this cut''s diagnostics were built from. NULL means the built-in default (scripts/diag/recipe.py DEFAULT_RECIPE).';
COMMENT ON COLUMN machining_force_analysis.diag_recipe_hash IS
    'Identity of the recipe the CURRENT diag artifacts were baked from. Staleness has two independent axes: diag_version tracks code changes, this tracks configuration changes. A baked artifact is reusable only when both match.';

CREATE TABLE IF NOT EXISTS diag_recipes (
    recipe_id   UUID        NOT NULL DEFAULT uuid_generate_v4(),
    name        VARCHAR(128) NOT NULL,
    recipe      JSONB       NOT NULL,
    notes       TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT diag_recipes_pkey PRIMARY KEY (recipe_id),
    CONSTRAINT diag_recipes_name_unique UNIQUE (name)
);

COMMENT ON TABLE diag_recipes IS
    'Named diagnostics recipe library; applying one copies its document onto machining_force_analysis.diag_recipe.';

-- migrate:down
DROP TABLE IF EXISTS diag_recipes;
ALTER TABLE machining_force_analysis
    DROP COLUMN IF EXISTS diag_recipe,
    DROP COLUMN IF EXISTS diag_recipe_hash;
```

- [ ] **Step 2: Apply it**

Run (from the repo root; the Makefile's localhost DSN cannot reach the DB from inside a container, so address the compose network directly):

```bash
MSYS_NO_PATHCONV=1 docker run --rm --network d1-database_d1net \
  -e DATABASE_URL="postgres://d1:change_me@postgres:5432/d1_database?sslmode=disable" \
  -v "$(pwd -W)/db:/db" ghcr.io/amacneil/dbmate:2 \
  --no-dump-schema --migrations-dir /db/migrations up
```

Expected: `Applied: 20260901000106_diag_recipe.sql`

- [ ] **Step 3: Verify live**

```bash
docker exec d1-database-postgres-1 psql -U d1 -d d1_database \
  -c "\d diag_recipes" \
  -c "select column_name from information_schema.columns where table_name='machining_force_analysis' and column_name like 'diag_recipe%';"
```

Expected: the table exists; both `diag_recipe` and `diag_recipe_hash` are listed.

- [ ] **Step 4: Commit**

```bash
git add db/migrations/20260901000106_diag_recipe.sql
git commit -m "feat(diag): add diag_recipe, diag_recipe_hash and the recipe library table"
```

---

## Task 9: Publish `base.d1an`

**Files:**
- Modify: `scripts/force_orchestrator.py` (`process_diag_row`)

**Interfaces:**
- Consumes: `write_d1an` from `diag.d1an`; `seed_columns`/`run_recipe` from `diag.runner`.
- Produces: `infra/octrees/diag/<op_id>/base.d1an` containing `t, rev, x, y, fc, ff, fp`.

- [ ] **Step 1: Add the base publication**

In `process_diag_row`, after the `analyse()` call and alongside the existing `write_d1an(str(d1an_path), columns)`, add a second artifact. Insert immediately before the `las_path` assignment:

```python
        # base.d1an: the state after angular resampling and before any statistics. It is
        # what the preview service re-runs a recipe from, so tuning a derived step needs
        # neither MATLAB nor the archive. Published rather than reconstructed on the fly:
        # deriving x/y from the cache instead would re-implement cut geometry outside
        # process_force.m, the divergence risk this codebase guards against throughout.
        from diag.registry import STEPS  # noqa: F401  (ensures ops are registered)
        from diag.runner import run_recipe, seed_columns

        base_stop = next(
            i for i, s in enumerate(recipe["steps"]) if s["op"] == "angular_resample"
        )
        base_cols, _ = run_recipe(
            recipe, seed_columns(cache, x, y), stop_after=base_stop
        )
        base_path = Path(outdir) / "base.d1an"
        write_d1an(str(base_path), base_cols)
```

- [ ] **Step 2: Copy it to the published directory**

Extend the existing publish loop. Replace:

```python
        shutil.copy2(d1an_path, dst / "attrs.d1an")
```

with:

```python
        shutil.copy2(d1an_path, dst / "attrs.d1an")
        shutil.copy2(base_path, dst / "base.d1an")
```

- [ ] **Step 3: Verify the module still imports and lints**

```bash
py -c "import sys; sys.path.insert(0,'scripts'); import force_orchestrator"
py -m ruff check scripts/force_orchestrator.py
```

Expected: no output from either.

- [ ] **Step 4: Commit**

```bash
git add scripts/force_orchestrator.py
git commit -m "feat(diag): publish base.d1an alongside the diag octree"
```

---

## Task 10: Bake the row's own recipe

**Files:**
- Modify: `scripts/force_orchestrator.py` (`claim_diag`, `process_diag_row`)

**Interfaces:**
- Consumes: `DEFAULT_RECIPE`, `recipe_hash` from `diag.recipe`.
- Produces: `claim_diag` returns `diag_recipe`; `process_diag_row` writes `diag_recipe_hash`.

- [ ] **Step 1: Return the recipe from `claim_diag`**

In `claim_diag`'s `RETURNING` clause, add `a.diag_recipe` after `a.filter_chain::text AS filter_chain`.

- [ ] **Step 2: Use it in `process_diag_row`**

Immediately after the `outdir = tempfile.mkdtemp(...)` line, resolve the recipe once:

```python
        from diag.recipe import DEFAULT_RECIPE, recipe_hash

        # NULL diag_recipe means "the built-in default", so existing rows keep working
        # untouched and no backfill migration is needed.
        recipe = row.get("diag_recipe") or DEFAULT_RECIPE
```

Then replace the `analyse(...)` call with a recipe run:

```python
        columns, metrics = run_recipe(recipe, seed_columns(cache, x, y))
        metrics.setdefault("cached_fs_hz", float(cache.get("fs", 0.0)))
```

- [ ] **Step 3: Record the hash on success**

In the success `UPDATE`, add the column. Replace the statement with:

```python
                "UPDATE machining_force_analysis SET diag_status='done', diag_path=%s, "
                "diag_points=%s, diag_version=%s, diag_metrics=%s, diag_recipe_hash=%s, "
                "diag_error=NULL, updated_at=now() WHERE id=%s",
                [op, int(n), DIAG_VERSION, json.dumps(metrics), recipe_hash(recipe), row["id"]],
```

- [ ] **Step 4: Extend `claim_diag`'s staleness clause to both axes**

Replace the `WHERE` clause inside `claim_diag`'s `picked` CTE with:

```sql
                 WHERE diag_status='pending'
                    OR (diag_status='done' AND (diag_version IS NULL OR diag_version < %s))
                    OR (diag_status='done' AND diag_recipe_hash IS DISTINCT FROM %s)
```

and change the parameter list from `[DIAG_VERSION, limit]` to
`[DIAG_VERSION, recipe_hash(DEFAULT_RECIPE), limit]`.

Note `IS DISTINCT FROM` rather than `!=`: `diag_recipe_hash` is NULL on every row baked before Task 8, and `NULL != 'abc'` is NULL, not true — those rows would never requeue.

- [ ] **Step 5: Verify and lint**

```bash
py -c "import sys; sys.path.insert(0,'scripts'); import force_orchestrator; print('ok')"
py -m ruff check scripts/force_orchestrator.py
```

Expected: `ok`, then no lint output.

- [ ] **Step 6: End-to-end check against a real cut**

Requeue an operation that already has a working octree and drain it, then confirm both the outputs and the new hash:

```bash
docker exec d1-database-postgres-1 psql -U d1 -d d1_database -c \
  "update machining_force_analysis set diag_status='pending', diag_requested_at=now(), diag_error=null where operation_id='ffe1286d-b636-53b4-b8da-e8c3a6d07bba';"
py scripts/_diag_smoke_test.py
docker exec d1-database-postgres-1 psql -U d1 -d d1_database -c \
  "select diag_status, diag_points, diag_recipe_hash from machining_force_analysis where operation_id='ffe1286d-b636-53b4-b8da-e8c3a6d07bba';"
ls infra/octrees/diag/ffe1286d-b636-53b4-b8da-e8c3a6d07bba/
```

Expected: `diag_status=done`, `diag_points=17920` (unchanged from before the refactor — the equivalence property holding on real data, not just the synthetic), a 16-character `diag_recipe_hash`, and five files including `base.d1an`.

- [ ] **Step 7: Commit**

```bash
git add scripts/force_orchestrator.py
git commit -m "feat(diag): bake each cut's own recipe and requeue on either staleness axis"
```

---

## Self-Review

**Spec coverage.** Component 1 (recipe) → Tasks 2, 8. Component 2 (registry) → Tasks 3, 4, 5. Component 4 (execution, bake half) → Tasks 5, 9, 10. Component 5 (invalidation) → Tasks 8, 10. The `base.d1an` artifact → Task 9. Testing section: default-recipe equivalence → Task 6; step contracts → Task 3; recipe hash stability → Task 2. Component 3 (paint layers), the preview half of Component 4 (`diag-service`), and Component 6 (layout) are Phases C–E and out of this plan's scope by design — `run_recipe` already accepts the `layers` argument they will use, so no interface changes are needed to add them.

**Deliberate gaps.** No `diag_layer` table: nothing consumes layers until Phase E, and creating an unused table now would be speculative. `run_recipe`'s `layers` parameter is threaded through to step functions but is always empty in this plan.

**Type consistency.** `Columns` is `dict[str, np.ndarray]` throughout. Step functions return `tuple[Columns, dict]` in the registry contract (Task 3), in every op (Task 4), and where the runner unpacks them (Task 5). `run_recipe(recipe, cols, *, layers, from_step, stop_after)` is called with `stop_after` in Tasks 5 and 9 and with `from_step` in Task 5, matching its definition. `recipe_hash` is defined in Task 2 and used in Task 10. `seed_columns` is defined in Task 5 and used in Tasks 7, 9, 10. `write_d1an` is the existing function from `diag/d1an.py`, unchanged.
