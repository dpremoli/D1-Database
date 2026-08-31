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

from .angular import angular_resample, order_spectrum, tsa
from .d1lc import read_d1lc
from .detrend import radial_detrend
from .envelope import bandpass_envelope, envelope_spectrum
from .frames import frame_transform
from .spatial import (
    assign_from_grid,
    benjamini_hochberg,
    cluster_hdbscan,
    getis_ord_gi_star,
    grid_reduce,
)

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
    """Run the Phase 1 analysis.

    `cache` is a read_d1lc() result. `x`/`y` are the spiral coordinates for the same samples.
    `channel` selects which of the frame-transformed axes ('fc', 'ff', 'fp') drives the TSA /
    order-spectrum / detrend pipeline; see the module docstring for why this defaults to 'fp'.
    `h_matrix` is an optional 3x3 FRF correction applied to (Fx,Fy,Fz) before the frame
    transform -- the worker applies a supplied matrix, it does not estimate one (see
    Component 4/8 non-goals in the design spec).
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
    fx_raw = np.asarray(cache["fx"], dtype=np.float64)
    fy_raw = np.asarray(cache["fy"], dtype=np.float64)
    fz_raw = np.asarray(cache["fz"], dtype=np.float64)
    h_applied = h_matrix is not None
    if h_applied:
        h = np.asarray(h_matrix, dtype=np.float64)
        if h.shape != (3, 3):
            raise ValueError(f"h_matrix must be 3x3, got shape {h.shape}")
        corrected = h @ np.vstack([fx_raw, fy_raw, fz_raw])
        fx_raw, fy_raw, fz_raw = corrected[0], corrected[1], corrected[2]
    frame = dict(zip(_CHANNELS, frame_transform(fx_raw, fy_raw, fz_raw, mount_deg)))
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

    # Spatial statistics run on the same (x_ang, y_ang, resid_z) the detrend already used.
    # Gi* needs at least gi_k+1 points; short test cuts can fall under that, so degrade to
    # "nothing significant" rather than raising -- a two-revolution synthetic cut should not
    # crash the whole pipeline over a statistic it has too few points to compute.
    if n > gi_k:
        gi_star, gi_p = getis_ord_gi_star(x_ang, y_ang, resid_z, k=gi_k)
        gi_sig = benjamini_hochberg(gi_p, alpha=0.05).astype(np.float64)
    else:
        gi_star = np.zeros(n)
        gi_sig = np.zeros(n)

    xr, yr, vr, cell_id = grid_reduce(
        x_ang, y_ang, resid_z, target_n=hdbscan_grid_target
    )
    if xr.size >= hdbscan_min_cluster_size:
        labels_r, glosh_r = cluster_hdbscan(
            xr, yr, vr, min_cluster_size=hdbscan_min_cluster_size
        )
        cluster_id, glosh = assign_from_grid(cell_id, labels_r, glosh_r)
    else:
        cluster_id = np.full(n, -1.0)
        glosh = np.zeros(n)

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
        "h_matrix_applied": h_applied,
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

    # Event-band (envelope) analysis runs on `sig` -- the full-rate signal, NOT sig_ang/
    # resid_z/anything angular-domain. It needs the same precondition quantitative_limit_hz
    # already requires (a real dyno_fn_hz), plus a Nyquist check specific to whether the
    # requested band actually fits: silently aliasing a band that doesn't fit is worse than
    # refusing, so refusal is recorded, never guessed past.
    env_band = np.zeros(n)
    if fn_hz is None or fn_hz <= 0:
        env_band_status = "refused: dyno_fn_hz not provided"
    else:
        half_bw = fn_hz * (envelope_bandwidth_frac / 2.0)
        hi_needed = fn_hz + half_bw
        nyquist = eff_fs / 2.0
        if nyquist < hi_needed:
            env_band_status = (
                f"refused: effective_nyquist_hz ({nyquist:.1f}) below required "
                f"{hi_needed:.1f} Hz for the resonance band"
            )
        else:
            envelope = bandpass_envelope(
                sig, eff_fs, f_center=fn_hz, bandwidth_frac=envelope_bandwidth_frac
            )
            _, env_ang = angular_resample(revs, envelope, samples_per_rev)
            env_band = env_ang[:n]
            env_band_status = "computed"
            env_f, env_amp = envelope_spectrum(envelope, eff_fs, max_freq=nyquist)
    metrics["env_band_status"] = env_band_status
    if env_band_status == "computed":
        metrics["envelope_spectrum"] = {
            "freqs": [float(v) for v in env_f],
            "amplitude": [float(v) for v in env_amp],
        }

    columns = {
        "t": t_ang.astype(np.float32),
        "rev": rev_grid.astype(np.float32),
        "x": x_ang.astype(np.float32),
        "y": y_ang.astype(np.float32),
        "tsa_resid": residual.astype(np.float32),
        "resid_z": resid_z.astype(np.float32),
        "gi_star": gi_star.astype(np.float32),
        "gi_sig": gi_sig.astype(np.float32),
        "cluster_id": cluster_id.astype(np.float32),
        "glosh": glosh.astype(np.float32),
        "env_band": env_band.astype(np.float32),
    }
    return columns, metrics
