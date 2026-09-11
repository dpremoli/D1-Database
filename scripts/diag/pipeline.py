"""One analysis pass: D1LC cache + spiral coordinates -> D1AN columns + metrics.

Phase 1-4 scope. Emits t, rev, x, y, tsa_resid, resid_z, gi_star, gi_sig, cluster_id, glosh
and env_band -- the full column set the design spec's D1AN contract calls for.

No geometry is recomputed here. process_force.m owns the spiral, the cut window and drift
compensation; this module consumes revs_cum and (x, y) as given. Recomputing either would
reintroduce exactly the divergence the pipeline already guards against elsewhere.

Channel choice: frame_transform always returns (Fc, Ff, Fp), but until a real tool-setup
record supplies a genuine `mount_deg` (deferred — see the design spec's Phase 6), Fc/Ff are
just a rotation of Fx/Fy by whatever default angle was passed in, not a real tool-frame
decomposition. The app's own FRM colour axis already defaults to Fz (RecordConfig.axis), so
Phase 1 analyses `Fp` (the unrotated dyno Z axis) by default, and only switches to Fc/Ff once
a caller supplies a real mount_deg for a real setup.
"""

from __future__ import annotations

import numpy as np

from .d1lc import read_d1lc

__all__ = ["analyse", "read_d1lc"]

DEFAULT_SAMPLES_PER_REV = 256
_CHANNELS = ("fc", "ff", "fp")


def analyse(
    cache: dict,
    x: np.ndarray,
    y: np.ndarray,
    *,
    mount_deg: float = 0.0,
    h_matrix: np.ndarray | None = None,
    samples_per_rev: int = DEFAULT_SAMPLES_PER_REV,
    fn_hz: float | None = None,
    channel: str = "fp",
    gi_k: int = 30,
    hdbscan_grid_target: int = 20_000,
    hdbscan_min_cluster_size: int = 10,
    envelope_bandwidth_frac: float = 0.2,
) -> tuple[dict[str, np.ndarray], dict]:
    """Run the default recipe. Retained as the stable entry point for callers that want the
    pipeline's default behaviour with a few knobs, rather than a recipe document: the
    orchestrator's own bake now passes a recipe directly (see process_diag_row).

    `cache` is a read_d1lc() result. `x`/`y` are the spiral coordinates for the same samples.
    `channel` selects which of the frame-transformed axes ('fc', 'ff', 'fp') drives the TSA /
    order-spectrum / detrend pipeline; see the module docstring for why this defaults to 'fp'.
    `h_matrix` is an optional 3x3 FRF correction applied to (Fx,Fy,Fz) before the frame
    transform. Returns (columns, metrics): `columns` is the D1AN column dict (all float32,
    all the same length), `metrics` is JSON-serialisable.
    """
    import copy

    from .recipe import DEFAULT_RECIPE
    from .runner import run_recipe, seed_columns

    if channel not in _CHANNELS:
        raise ValueError(f"channel must be one of {_CHANNELS}, got {channel!r}")

    recipe = copy.deepcopy(DEFAULT_RECIPE)
    by_op = {s["op"]: s for s in recipe["steps"]}
    by_op["frame_transform"]["params"].update(
        {"channel": channel, "mount_deg": mount_deg, "h_matrix": h_matrix}
    )
    by_op["angular_resample"]["params"]["samples_per_rev"] = samples_per_rev
    by_op["getis_ord"]["params"]["k"] = gi_k
    by_op["hdbscan"]["params"].update(
        {
            "grid_target": hdbscan_grid_target,
            "min_cluster_size": hdbscan_min_cluster_size,
        }
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
