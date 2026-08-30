"""One analysis pass: D1LC cache + spiral coordinates -> D1AN columns + metrics.

Phase 1 scope. Emits t, rev, tsa_resid and resid_z; the spatial statistics columns
(gi_star, gi_sig, glosh, cluster_id) and env_band arrive in later phases.

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

from .angular import angular_resample, order_spectrum, tsa
from .d1lc import read_d1lc
from .detrend import radial_detrend
from .frames import frame_transform

__all__ = ["analyse", "read_d1lc"]

DEFAULT_SAMPLES_PER_REV = 256
_CHANNELS = ("fc", "ff", "fp")


def analyse(
    cache: dict,
    x: np.ndarray,
    y: np.ndarray,
    *,
    mount_deg: float = 0.0,
    samples_per_rev: int = DEFAULT_SAMPLES_PER_REV,
    fn_hz: float | None = None,
    channel: str = "fp",
) -> tuple[dict[str, np.ndarray], dict]:
    """Run the Phase 1 analysis.

    `cache` is a read_d1lc() result. `x`/`y` are the spiral coordinates for the same samples.
    `channel` selects which of the frame-transformed axes ('fc', 'ff', 'fp') drives the TSA /
    order-spectrum / detrend pipeline; see the module docstring for why this defaults to 'fp'.
    Returns (columns, metrics): `columns` is the D1AN column dict (all float32, all the same
    length), `metrics` is JSON-serialisable.

    The returned columns are shorter than the input: TSA truncates to whole revolutions, and
    resampling puts everything on an angular grid. `rev` and `t` are emitted alongside so a
    consumer never has to reconstruct the mapping back to the original samples.
    """
    if channel not in _CHANNELS:
        raise ValueError(f"channel must be one of {_CHANNELS}, got {channel!r}")
    revs = np.asarray(cache["revs"], dtype=np.float64)
    t_in = np.asarray(cache["t"], dtype=np.float64)
    frame = dict(
        zip(
            _CHANNELS, frame_transform(cache["fx"], cache["fy"], cache["fz"], mount_deg)
        )
    )
    sig = frame[channel]

    rev_grid, sig_ang = angular_resample(revs, sig, samples_per_rev)
    _, t_ang = angular_resample(revs, t_in, samples_per_rev)
    _, x_ang = angular_resample(revs, np.asarray(x, dtype=np.float64), samples_per_rev)
    _, y_ang = angular_resample(revs, np.asarray(y, dtype=np.float64), samples_per_rev)

    signature, residual = tsa(sig_ang, samples_per_rev)
    n = residual.size  # whole revolutions only
    rev_grid, t_ang, x_ang, y_ang = (a[:n] for a in (rev_grid, t_ang, x_ang, y_ang))

    r = np.hypot(x_ang, y_ang)
    resid_z = radial_detrend(r, residual)

    orders, amp = order_spectrum(sig_ang, samples_per_rev)
    # Keep only the low orders for the metrics payload — everything diagnostically
    # interesting (insert passing, its harmonics, and the non-integer chatter orders between
    # them) lives below ~16x shaft speed, and the full spectrum is far too large for jsonb.
    keep = orders <= 16.0

    span_sec = float(t_in[-1] - t_in[0]) if t_in.size > 1 else 0.0
    eff_fs = (t_in.size / span_sec) if span_sec > 0 else 0.0
    metrics: dict = {
        "n_points": int(n),
        "n_revolutions": int(n // samples_per_rev),
        "samples_per_rev": int(samples_per_rev),
        "cached_fs_hz": float(cache.get("fs", 0.0)),
        "effective_fs_hz": eff_fs,
        "effective_nyquist_hz": eff_fs / 2.0,
        "mount_deg": float(mount_deg),
        "channel": channel,
        "tsa_signature": [float(v) for v in signature],
        "order_spectrum": {
            "orders": [float(v) for v in orders[keep]],
            "amplitude": [float(v) for v in amp[keep]],
        },
        "resid_z_p99": float(np.percentile(np.abs(resid_z), 99)) if n else 0.0,
    }
    if fn_hz is not None and fn_hz > 0:
        # Kistler specifies the valid quantitative measurement range as fn/5. Above it the
        # dynamometer amplifies rather than measures, so that band is event-detection only.
        metrics["dyno_fn_hz"] = float(fn_hz)
        metrics["quantitative_limit_hz"] = float(fn_hz) / 5.0

    columns = {
        "t": t_ang.astype(np.float32),
        "rev": rev_grid.astype(np.float32),
        "tsa_resid": residual.astype(np.float32),
        "resid_z": resid_z.astype(np.float32),
    }
    return columns, metrics
