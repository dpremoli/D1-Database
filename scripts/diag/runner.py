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
from .angular import angular_resample
from .registry import STEPS, Columns, resolve_inputs, validate_recipe

# Mirrors ops.py::_CHANNELS. Duplicated rather than imported: ops.py is the step-registration
# module, and STEP_META.frame_transform's options in recipeChannels.ts already mirror this
# same list a third time -- one more import wouldn't remove the real risk (three places
# agreeing on "fp, fc, ff"), and this way each file states its own copy where it's used.
_FRAME_CHANNELS: tuple[str, ...] = ("fp", "fc", "ff")

# The D1AN contract: exactly these columns, always, in this order. A disabled step still
# contributes its column (zero-filled) because the browser's reader indexes by name and a
# missing column is a parse error, not an absence.
#
# inverted/grid_fill/grid_support/gmm_id/gmm_prob (Phase H slice 2) follow the same
# always-present, off-by-default precedent segment_id set: none of invert/griddify/
# gmm_segmentation is in DEFAULT_RECIPE, so every cut that never enables them gets a
# zero-filled (gmm_id: -1-filled, matching segment_id's "unsegmented") column, and the
# analyst can still select the channel to see that it is empty rather than the request
# failing outright.
PUBLIC_COLUMNS: tuple[str, ...] = (
    "t", "rev", "x", "y", "tsa_resid", "resid_z",
    "gi_star", "gi_sig", "cluster_id", "glosh", "env_band", "segment_id",
    "inverted", "grid_fill", "grid_support", "gmm_id", "gmm_prob",
)

# Angular-domain columns that shorten with the TSA truncation. Deliberately hardcoded and
# NOT derived from any step's `produces`: `angular_resample` also produces `sig`, which must
# stay at its full resampled length so `order_spectrum` (inside the tsa step) and the
# full-rate `envelope` step are unaffected. Seed columns (`t_raw`, `revs`, `fx/fy/fz` ...)
# and the frame channels (`fc/ff/fp`) are likewise left untouched.
#
# "Columns that shorten under TSA truncation" and "columns the D1AN file must contain"
# (PUBLIC_COLUMNS) are INDEPENDENT concepts that happen to hold the same values today. Do
# NOT alias one to the other: a new derived step could produce an angular column that must
# truncate without being part of the fixed D1AN contract, and widening _TRUNCATABLE is not
# a licence to widen PUBLIC_COLUMNS (the D1AN contract is fixed) or vice versa.
#
# `segment_id` is listed here for consistency with `cluster_id` and because
# test_truncation_allowlist_covers_every_registered_angular_column pins that every derived
# step's angular output appears -- though like every column produced AFTER `tsa` it is
# created at the already-truncated length, so its presence has no runtime effect today.
_TRUNCATABLE: tuple[str, ...] = (
    "t", "rev", "x", "y", "tsa_resid", "resid_z",
    "gi_star", "gi_sig", "cluster_id", "glosh", "env_band", "segment_id",
    "inverted", "grid_fill", "grid_support", "gmm_id", "gmm_prob",
)

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
    emit: tuple[str, ...] | None = None,
) -> tuple[Columns, dict]:
    """Execute `recipe` over `cols`.

    `emit` overrides the return contract: instead of `PUBLIC_COLUMNS`, return exactly the
    named columns taken from the internal work dict at their natural length, cast to
    float32. The `tsa_resid`-present requirement is NOT applied in this mode -- its whole
    purpose is to emit a pre-`tsa` state (e.g. `base.d1an` after `angular_resample`). A
    requested column absent from the work dict raises rather than being zero-filled.

    `from_step` and `stop_after` index the FULL step list (disabled steps included), so a
    caller can address a step positionally as the UI does. `from_step` assumes `cols`
    already holds everything the earlier steps produced -- that is the preview path, where
    a cached prefix is resumed rather than recomputed.

    Returns `(columns, metrics)`: when `emit` is None, `columns` is exactly
    `PUBLIC_COLUMNS`, float32, all one length; when `emit` is given, `columns` is exactly
    the named columns, float32, at their natural length. `metrics` is JSON-serialisable and
    reproduces analyse()'s payload.
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
        # Resolve this step's painted-layer bindings (if any) into per-point boolean arrays
        # against the CURRENT angular-grid coords. A step with no `inputs` key gets {} --
        # byte-for-byte identical to the pre-Phase-E behaviour where every step got `layers`
        # raw and no step read it.
        resolved = resolve_inputs(s, layers, work.get("x"), work.get("y"))
        produced, frag = spec.fn(work, params, resolved)
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

    if emit is not None:
        picked: Columns = {}
        for name in emit:
            col = work.get(name)
            if col is None:
                available = sorted(k for k in work if not k.startswith("__"))
                raise ValueError(
                    f"run_recipe(emit=...): requested column {name!r} is not present in "
                    f"the work dict; available columns are {available}"
                )
            # .astype always copies, matching the PUBLIC_COLUMNS assembly below and never
            # handing back a view into a caller's prefix-cache dict.
            picked[name] = np.asarray(col).astype(np.float32)
        return picked, metrics

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
        # segment_id and gmm_id default to -1 ("unsegmented" -- 0 is a valid class index for
        # both); every other missing/disabled column zero-fills as before.
        fill = -1.0 if name in ("segment_id", "gmm_id") else 0.0
        out[name] = (
            col[:n].astype(np.float32) if col is not None
            else np.full(n, fill, dtype=np.float32)
        )
    return out, metrics


def base_columns_all_channels(recipe: dict, cols: Columns) -> Columns:
    """The pre-tsa state for EVERY frame_transform channel at once: t/rev/x/y (identical
    regardless of channel, since only the FORCE projection differs) plus one sig_<channel>
    column per entry in _FRAME_CHANNELS.

    Published as base.d1an (Phase H slice 4) so a preview can switch which channel a recipe
    shows without a rebake. frame_transform already computes fc/ff/fp together in one call
    (ops.py::_op_frame_transform) -- the only extra work over the original single-channel
    base is angular_resample-ing the other two signals onto the SAME grid, using the SAME
    revs it already needed for the one it used to keep.

    Precision note: run_recipe's `emit` seam always casts to float32 (matching the original
    single-channel base.d1an path, and base.d1an has been float32 since it was introduced --
    "preview is an approximation" already tolerates far more than one extra truncation of the
    full-rate signal buys here).
    """
    frame_idx = next(i for i, s in enumerate(recipe["steps"]) if s["op"] == "frame_transform")
    spr = int(_resample_params(recipe["steps"]).get("samples_per_rev", 256))

    pre, _ = run_recipe(
        recipe, cols, stop_after=frame_idx,
        emit=("revs", "t_raw", "x_raw", "y_raw", "fc", "ff", "fp"),
    )
    revs = pre["revs"]
    rev_grid, t = angular_resample(revs, pre["t_raw"], spr)
    _, x = angular_resample(revs, pre["x_raw"], spr)
    _, y = angular_resample(revs, pre["y_raw"], spr)
    out: Columns = {
        "t": t.astype(np.float32), "rev": rev_grid.astype(np.float32),
        "x": x.astype(np.float32), "y": y.astype(np.float32),
    }
    for ch in _FRAME_CHANNELS:
        _, sig = angular_resample(revs, pre[ch], spr)
        out[f"sig_{ch}"] = sig.astype(np.float32)
    return out
