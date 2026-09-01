"""Recipe execution. One code path, two callers.

The orchestrator's bake and (later) the preview service both import this function, which is
what makes "what you tuned is what you baked" a structural guarantee rather than a
convention: they cannot drift because there is only one implementation.

Equivalence with the pre-refactor ``pipeline.analyse()`` is the contract this module is held
to (see the golden fixtures). Two consequences worth stating up front:

* Columns are carried as float64 through the whole chain and cast to float32 exactly once,
  when the public column set is assembled. ``analyse()`` does the same; casting between
  steps would feed ``radial_detrend`` a rounded residual and drift every downstream stat.
* Truncation (TSA keeps whole revolutions only) applies to the angular-domain columns
  ONLY -- never to ``sig``, ``revs``, ``t_raw`` or ``fc/ff/fp``, which the full-rate
  ``envelope`` step still needs at their original length.
"""

from __future__ import annotations

from typing import Any

import numpy as np

from . import ops  # noqa: F401  -- import for its registration side effects
from .registry import STEPS, Columns, validate_recipe

# The D1AN contract: exactly these columns, always, in this order. A disabled step still
# contributes its column (zero-filled) because the browser's reader indexes by name and a
# missing column is a parse error, not an absence.
PUBLIC_COLUMNS: tuple[str, ...] = (
    "t", "rev", "x", "y", "tsa_resid", "resid_z",
    "gi_star", "gi_sig", "cluster_id", "glosh", "env_band",
)

# Angular-domain columns that shorten with the TSA truncation. Deliberately hardcoded and
# NOT derived from any step's `produces`: `angular_resample` also produces `sig`, which must
# stay at its full resampled length so `order_spectrum` (inside the tsa step) and the
# full-rate `envelope` step are unaffected. Seed columns (`t_raw`, `revs`, `fx/fy/fz` ...)
# and the frame channels (`fc/ff/fp`) are likewise left untouched.
_TRUNCATABLE: tuple[str, ...] = PUBLIC_COLUMNS

# Internal, non-array-contract key: the D1LC cache sample rate, stashed by seed_columns so
# run_recipe can reproduce analyse()'s `cached_fs_hz` metric without being handed the cache.
_CACHE_FS_KEY = "__cache_fs__"


def seed_columns(cache: dict, x: np.ndarray, y: np.ndarray) -> Columns:
    """The pre-step column set, from the D1LC cache and the D1OC spiral coordinates.

    x/y are MATLAB's own geometry, passed through untouched -- process_force.m remains the
    sole owner of the spiral, the cut window and drift compensation. Everything is float64:
    the chain stays double-precision until the public columns are assembled.
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
        _CACHE_FS_KEY: np.asarray(cache.get("fs", 0.0), dtype=np.float64),
    }


def _truncate(cols: Columns, n: int) -> Columns:
    """Shorten the angular-domain columns to `n` whole-revolution samples. Only the columns
    in `_TRUNCATABLE` are affected; the `v.size >= n` guard keeps an already-short column
    from silently shrinking further."""
    out = dict(cols)
    for k in _TRUNCATABLE:
        v = out.get(k)
        if v is not None and v.ndim == 1 and v.size >= n:
            out[k] = v[:n]
    return out


def _resample_params(steps: list[dict]) -> dict[str, Any]:
    """The params of the recipe's `angular_resample` step (empty if it has none)."""
    for s in steps:
        if s.get("op") == "angular_resample":
            return dict(s.get("params") or {})
    return {}


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

    Returns `(columns, metrics)`: `columns` is exactly `PUBLIC_COLUMNS`, float32, all one
    length; `metrics` is JSON-serialisable and reproduces analyse()'s payload.
    """
    validate_recipe(recipe)
    steps = list(recipe.get("steps", []))
    resample_params = _resample_params(steps)
    metrics: dict = {}
    work: Columns = dict(cols)

    lo = from_step if from_step is not None else 0
    hi = stop_after if stop_after is not None else len(steps) - 1
    # Which ops the runner actually walked this call. A step outside [lo, hi] was neither
    # run nor consciously skipped, so any metric that stands in for "this step was
    # evaluated" (env_band_status) must not be synthesised on its behalf.
    considered_ops = {steps[i].get("op") for i in range(len(steps)) if lo <= i <= hi}

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
        if "samples_per_rev" not in params and "samples_per_rev" in resample_params:
            params["samples_per_rev"] = int(resample_params["samples_per_rev"])
        # channel likewise originates on frame_transform; angular_resample and envelope
        # both consume it.
        if "channel" not in params:
            for earlier in steps:
                if earlier.get("op") == "frame_transform":
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

    # Metrics analyse() emits unconditionally that no single op can reach. eff_fs is
    # computed exactly as analyse() does -- explicit float(), Python division -- so the
    # frozen `repr(sorted(metrics.items()))` golden matches value-for-value. Each key is
    # emitted ONLY when its input is present: on a `from_step` resume the seed columns are
    # gone, and a synthesised `0.0` there is a plausible-looking lie, not a sentinel.
    fs_val = work.get(_CACHE_FS_KEY)
    if fs_val is not None:
        metrics["cached_fs_hz"] = float(fs_val)
    t_in = work.get("t_raw")
    if t_in is not None:
        if t_in.size > 1:
            span_sec = float(t_in[-1] - t_in[0])
            eff_fs = (t_in.size / span_sec) if span_sec > 0 else 0.0
        else:
            eff_fs = 0.0
        metrics["effective_fs_hz"] = eff_fs
        metrics["effective_nyquist_hz"] = eff_fs / 2.0
    # An enabled envelope step already set this to "computed" (or its own refusal string);
    # setdefault must not clobber it. When the step is off but was walked, analyse()'s
    # default applies. When `stop_after`/`from_step` excluded the envelope step entirely,
    # no status is true -- omit it rather than assert a false refusal reason.
    if "envelope" in considered_ops:
        metrics.setdefault("env_band_status", "refused: dyno_fn_hz not provided")
    # samples_per_rev is emitted by analyse() always; the angular_resample fragment only
    # carries it when that step actually ran this call.
    if "samples_per_rev" not in metrics and "samples_per_rev" in resample_params:
        metrics["samples_per_rev"] = int(resample_params["samples_per_rev"])

    if "tsa_resid" not in work:
        raise ValueError(
            "run_recipe stopped before the 'tsa' step, so no angular column length is "
            "defined; cannot assemble the public column set. Widen stop_after past tsa."
        )
    n = int(work["tsa_resid"].size)
    out: Columns = {}
    for name in PUBLIC_COLUMNS:
        col = work.get(name)
        # .astype(np.float32) always copies (matching analyse()); np.asarray would hand
        # back a VIEW into the caller's prefix-cache dict when col is already float32.
        out[name] = (
            col[:n].astype(np.float32) if col is not None
            else np.zeros(n, dtype=np.float32)
        )
    return out, metrics
