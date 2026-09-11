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

from .angular import angular_resample, order_spectrum
from .angular import tsa as _tsa
from .detrend import radial_detrend as _radial_detrend
from .envelope import bandpass_envelope, envelope_spectrum
from .frames import frame_transform as _frame_transform
from .interpolate import grid_interpolate
from .registry import Columns, step
from .spatial import (
    assign_by_neighbours,
    benjamini_hochberg,
    cluster_gmm,
    cluster_hdbscan,
    getis_ord_gi_star,
    grid_reduce,
)

_CHANNELS = ("fc", "ff", "fp")


@step(
    "frame_transform",
    produces=["fc", "ff", "fp"],
    requires=["fx", "fy", "fz"],
    tier="base",
    category="transform",
)
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


@step(
    "angular_resample",
    produces=["t", "rev", "x", "y", "sig"],
    requires=["revs", "t_raw", "x_raw", "y_raw", "fc", "ff", "fp"],
    tier="base",
    category="transform",
)
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


@step(
    "tsa",
    produces=["tsa_resid"],
    requires=["sig", "rev"],
    tier="derived",
    category="residual",
)
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


@step(
    "radial_detrend",
    produces=["resid_z"],
    requires=["tsa_resid", "x", "y"],
    tier="derived",
    category="residual",
)
def _op_radial_detrend(cols: Columns, params: dict, inputs: dict):
    r = np.hypot(cols["x"], cols["y"])
    tsa = cols["tsa_resid"]
    n_bins = int(params.get("n_bins", 200))
    min_per_bin = int(params.get("min_per_bin", 8))
    mask = inputs.get(
        "mask"
    )  # True = an excluded region (chuck mark / fixture artefact)
    if mask is not None and np.any(mask):
        # Hold masked points out of the radial-bin fit entirely and give them NaN: the
        # detrend, Gi* and clustering downstream must never see a fixture artefact. NaN is
        # the D1AN value; the orchestrator sanitises it before the LAS/octree write.
        keep = ~np.asarray(mask, dtype=bool)
        z = np.full(r.shape, np.nan)
        z[keep] = _radial_detrend(
            r[keep], tsa[keep], n_bins=n_bins, min_per_bin=min_per_bin
        )
    else:
        z = _radial_detrend(r, tsa, n_bins=n_bins, min_per_bin=min_per_bin)
    finite = z[np.isfinite(z)]
    return {"resid_z": z}, {
        "resid_z_p99": float(np.percentile(np.abs(finite), 99)) if finite.size else 0.0,
    }


@step(
    "getis_ord",
    produces=["gi_star", "gi_sig"],
    requires=["x", "y", "resid_z"],
    tier="derived",
    category="statistics",
)
def _op_getis_ord(cols: Columns, params: dict, inputs: dict):
    k = int(params.get("k", 30))
    alpha = float(params.get("alpha", 0.05))
    z = cols["resid_z"]
    n = z.size
    # Compute only over finite resid_z: a mask on radial_detrend leaves NaN where a fixture
    # artefact was excluded, and Gi* must not see it. With no mask every point is finite and
    # this is byte-identical to before.
    fin = np.isfinite(z)
    gi = np.full(n, np.nan) if not fin.all() else np.zeros(n)
    sig = np.zeros(n)
    # Degrade rather than raise: a short test cut can have fewer points than Gi* needs, and
    # crashing the whole pipeline over one statistic is the wrong trade. Matches analyse().
    if int(fin.sum()) > k:
        g, p = getis_ord_gi_star(cols["x"][fin], cols["y"][fin], z[fin], k=k)
        gi[fin] = g
        sig[fin] = benjamini_hochberg(p, alpha=alpha).astype(np.float64)
    return {"gi_star": gi, "gi_sig": sig}, {}


@step(
    "hdbscan",
    produces=["cluster_id", "glosh"],
    requires=["x", "y", "resid_z"],
    tier="derived",
    category="segmentation",
)
def _op_hdbscan(cols: Columns, params: dict, inputs: dict):
    target = int(params.get("grid_target", 20000))
    min_size = int(params.get("min_cluster_size", 10))
    z = cols["resid_z"]
    n = z.size
    # Cluster only finite points: a masked-out fixture artefact is NaN in resid_z and must
    # not join a cluster. With no mask, fin is all-True and this is byte-identical.
    fin = np.isfinite(z)
    cluster_id = np.full(n, -1.0)
    glosh = np.zeros(n)
    if int(fin.sum()) >= min_size:
        xr, yr, vr, _cell_id = grid_reduce(
            cols["x"][fin], cols["y"][fin], z[fin], target_n=target
        )
        if xr.size >= min_size:
            labels, gl = cluster_hdbscan(xr, yr, vr, min_cluster_size=min_size)
            # Vote over neighbouring centroids rather than broadcasting each grid cell's
            # label: grid_reduce targets a CELL COUNT, so the broadcast quantized every
            # boundary to ~1/141 of the view at every zoom level -- visibly blocky segments
            # that no parameter could fix. See spatial.assign_by_neighbours.
            cid_fin, gl_fin = assign_by_neighbours(
                cols["x"][fin], cols["y"][fin], xr, yr, labels, gl
            )
            cluster_id[fin] = cid_fin
            glosh[fin] = gl_fin
    return {"cluster_id": cluster_id, "glosh": glosh}, {}


@step(
    "envelope",
    produces=["env_band"],
    requires=["fc", "ff", "fp", "revs", "t_raw", "tsa_resid"],
    tier="base",
    category="residual",
)
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
        # analyse() sets dyno_fn_hz / quantitative_limit_hz before the envelope block,
        # gated only on fn_hz > 0, so they are emitted even on this refusal branch.
        return {"env_band": np.zeros(n)}, {
            "env_band_status": (
                f"refused: effective_nyquist_hz ({nyquist:.1f}) below required "
                f"{hi_needed:.1f} Hz for the resonance band"
            ),
            "dyno_fn_hz": fn_hz,
            "quantitative_limit_hz": fn_hz / 5.0,
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


@step(
    "grow_segmentation",
    produces=["segment_id"],
    requires=["x", "y", "resid_z"],
    tier="derived",
    category="segmentation",
)
def _op_grow_segmentation(cols: Columns, params: dict, inputs: dict):
    """Seeded segmentation: each bound seed-role layer is one class; LabelSpreading fills
    every other point. Degrades to all -1 below 2 seed classes. NOT in DEFAULT_RECIPE -- it
    needs seed layers that do not exist by default; the runner's assembly fills segment_id
    with -1 for every cut that never enables this step."""
    from .segmentation import grow_segmentation

    feature_names = params.get("features") or ["resid_z"]
    feature_cols = [cols[f] for f in feature_names if f in cols]
    seeds = inputs.get("seeds") or {}
    seed_masks = list(seeds.values())  # order preserved from resolve_inputs list mode
    seg, status = grow_segmentation(
        cols["x"],
        cols["y"],
        feature_cols,
        seed_masks,
        k=int(params.get("k", 15)),
        alpha=float(params.get("alpha", 0.2)),
        attr_weight=float(params.get("attr_weight", 1.0)),
    )
    n_classes = len({int(v) for v in seg[seg >= 0]})
    return {"segment_id": seg}, {
        "segmentation_status": status,
        "segmentation_n_classes": int(n_classes),
    }


@step(
    "invert", produces=["inverted"], requires=[], tier="derived", category="transform"
)
def _op_invert(cols: Columns, params: dict, inputs: dict):
    """Value inversion -- NOT a sign flip, NOT deconvolution. Maps `source` through a
    complement or reciprocal so a "low is bad" channel (e.g. glosh, where a poor fit reads
    low) can be coloured the same way as a "high is bad" one (resid_z).

    `requires=()` is deliberate: `source` names WHICH earlier column to invert, chosen at
    recipe-edit time -- a genuinely runtime dependency the static requires/produces graph
    cannot express (every other step's requires is fixed at registration). Raising here with
    the missing name in the message is what lets recipeProblems() (recipeChannels.ts) mirror
    the same check client-side and refuse the doomed request before it is sent, rather than
    this step being the one whose failure the client can never predict.
    """
    source = str(params.get("source", "resid_z"))
    if source not in cols:
        raise ValueError(
            f"invert: source column {source!r} is not available -- place invert after "
            f"the step that produces it"
        )
    v = np.asarray(cols[source], dtype=np.float64)
    mode = str(params.get("mode", "complement"))
    if mode == "reciprocal":
        epsilon = float(params.get("epsilon", 1e-6))
        # Magnitude inverted (small |v| -> large output), sign kept: a positive and a
        # negative anomaly of the same size stay distinguishable after inversion.
        out = np.copysign(1.0 / (np.abs(v) + epsilon), v)
    else:
        finite = v[np.isfinite(v)]
        top = float(np.nanmax(finite)) if finite.size else 0.0
        out = top - v
    return {"inverted": out}, {}


@step(
    "griddify",
    produces=["grid_fill", "grid_support"],
    requires=["x", "y", "resid_z"],
    tier="derived",
    category="interpolation",
)
def _op_griddify(cols: Columns, params: dict, inputs: dict):
    """Regularise resid_z onto a resolution_mm grid and sample it back at every original
    point (see interpolate.py for why -- the point count cannot change). grid_fill is the
    result; grid_support is [0, 1], each point's own local density relative to max_fill_mm,
    the honest "how much of this is invented" estimate."""
    resolution_mm = float(params.get("resolution_mm", 0.25))
    method = str(params.get("method", "linear"))
    max_fill_mm = float(params.get("max_fill_mm", 1.0))
    fill, support = grid_interpolate(
        cols["x"],
        cols["y"],
        cols["resid_z"],
        resolution_mm=resolution_mm,
        method=method,
        max_fill_mm=max_fill_mm,
    )
    finite_support = support[np.isfinite(support)]
    return {"grid_fill": fill, "grid_support": support}, {
        "grid_support_mean": float(finite_support.mean())
        if finite_support.size
        else 0.0,
    }


@step(
    "gmm_segmentation",
    produces=["gmm_id", "gmm_prob"],
    requires=["x", "y", "resid_z"],
    tier="derived",
    category="segmentation",
)
def _op_gmm_segmentation(cols: Columns, params: dict, inputs: dict):
    """Unsupervised counterpart to grow_segmentation -- no seeds needed, every point gets a
    class (no noise) and a genuine per-point confidence (gmm_prob). Runs on the same
    grid-reduced set as hdbscan, carried back with assign_by_neighbours, so it does not
    reintroduce the grid-quantized boundaries assign_from_grid produced (see the hdbscan op's
    comment and spatial.assign_by_neighbours)."""
    n_components = int(params.get("n_components", 4))
    covariance_type = str(params.get("covariance_type", "full"))
    attr_weight = float(params.get("attr_weight", 1.0))
    random_state = int(params.get("random_state", 0))
    target = int(params.get("grid_target", 20000))

    z = cols["resid_z"]
    n = z.size
    fin = np.isfinite(z)
    gmm_id = np.full(n, -1.0)
    gmm_prob = np.zeros(n)
    if int(fin.sum()) >= max(4, n_components):
        xr, yr, vr, _cell_id = grid_reduce(
            cols["x"][fin], cols["y"][fin], z[fin], target_n=target
        )
        labels, prob = cluster_gmm(
            xr,
            yr,
            vr,
            n_components=n_components,
            covariance_type=covariance_type,
            attr_weight=attr_weight,
            random_state=random_state,
        )
        id_fin, prob_fin = assign_by_neighbours(
            cols["x"][fin], cols["y"][fin], xr, yr, labels, prob
        )
        gmm_id[fin] = id_fin
        gmm_prob[fin] = prob_fin
    return {"gmm_id": gmm_id, "gmm_prob": gmm_prob}, {}
