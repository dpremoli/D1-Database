import struct

import numpy as np

from conftest import (
    GOLDEN_DEFAULT,
    GOLDEN_ENVELOPE,
    assert_columns_match_golden,
    cache_of,
    synthetic_cut,
)

from diag.pipeline import analyse, read_d1lc

SPR = 256


def _write_d1lc(path, t, fx, fy, fz, rpm, revs, fs):
    head = struct.pack(
        "<IIIfffff", 0x44314C43, 1, t.size, float(fs), 0.05, 80.0, 0.0, float(t[-1])
    )
    with open(path, "wb") as f:
        f.write(head)
        for a in (t, fx, fy, fz, rpm, revs):
            f.write(np.ascontiguousarray(a, dtype="<f4").tobytes())


def test_d1lc_round_trip(tmp_path):
    t, fx, fy, fz, rpm, revs, _, _, fs, _ = synthetic_cut(n_rev=4)
    p = str(tmp_path / "c.bin")
    _write_d1lc(p, t, fx, fy, fz, rpm, revs, fs)
    c = read_d1lc(p)
    assert c["n"] == t.size
    np.testing.assert_allclose(c["fz"], fz.astype(np.float32), rtol=1e-6)


def test_pipeline_recovers_implanted_anomaly_location():
    """The test that validates the science: an anomaly implanted at a known revolution
    must come back as the strongest residual at that same revolution, AND as a
    significant spatial hotspot with its own cluster."""
    t, fx, fy, fz, rpm, revs, x, y, fs, hit = synthetic_cut()
    cache = {
        "n": t.size,
        "fs": fs,
        "feed": 0.05,
        "diam": 80.0,
        "cs_sec": 0.0,
        "ce_sec": float(t[-1]),
        "t": t,
        "fx": fx,
        "fy": fy,
        "fz": fz,
        "rpm": rpm,
        "revs": revs,
    }
    cols, metrics = analyse(cache, x, y, samples_per_rev=SPR)
    peak_rev = cols["rev"][int(np.argmax(np.abs(cols["resid_z"])))]
    assert abs(peak_rev - 25.0) < 0.2
    assert metrics["n_points"] == cols["resid_z"].size

    # the point of peak residual must also read as a significant spatial hotspot
    peak_idx = int(np.argmax(np.abs(cols["resid_z"])))
    assert cols["gi_sig"][peak_idx] == 1.0
    assert cols["gi_star"][peak_idx] > 0


def test_pipeline_columns_are_aligned_and_finite():
    t, fx, fy, fz, rpm, revs, x, y, fs, _ = synthetic_cut(n_rev=8)
    cache = {
        "n": t.size,
        "fs": fs,
        "feed": 0.05,
        "diam": 80.0,
        "cs_sec": 0.0,
        "ce_sec": float(t[-1]),
        "t": t,
        "fx": fx,
        "fy": fy,
        "fz": fz,
        "rpm": rpm,
        "revs": revs,
    }
    cols, _ = analyse(cache, x, y, samples_per_rev=SPR)
    sizes = {k: v.size for k, v in cols.items()}
    assert len(set(sizes.values())) == 1, sizes
    for k, v in cols.items():
        assert np.all(np.isfinite(v)), k
        assert v.dtype == np.float32, k


def test_pipeline_columns_include_spatial_coordinates():
    t, fx, fy, fz, rpm, revs, x, y, fs, _ = synthetic_cut(n_rev=8)
    cache = {
        "n": t.size,
        "fs": fs,
        "feed": 0.05,
        "diam": 80.0,
        "cs_sec": 0.0,
        "ce_sec": float(t[-1]),
        "t": t,
        "fx": fx,
        "fy": fy,
        "fz": fz,
        "rpm": rpm,
        "revs": revs,
    }
    cols, _ = analyse(cache, x, y, samples_per_rev=SPR)
    assert set(cols) == {
        "t",
        "rev",
        "x",
        "y",
        "tsa_resid",
        "resid_z",
        "gi_star",
        "gi_sig",
        "cluster_id",
        "glosh",
        "env_band",
        "segment_id",
    }
    # x/y must land on the same radius the spiral actually has at that revolution --
    # not just be finite/present. rho = 40.0 - 0.05*revs in synthetic_cut.
    r = np.hypot(cols["x"], cols["y"])
    expected_r = 40.0 - 0.05 * cols["rev"]
    np.testing.assert_allclose(r, expected_r, atol=0.05)


def test_env_band_refused_when_fn_hz_not_provided():
    t, fx, fy, fz, rpm, revs, x, y, fs, _ = synthetic_cut(n_rev=8)
    cache = {
        "n": t.size,
        "fs": fs,
        "feed": 0.05,
        "diam": 80.0,
        "cs_sec": 0.0,
        "ce_sec": float(t[-1]),
        "t": t,
        "fx": fx,
        "fy": fy,
        "fz": fz,
        "rpm": rpm,
        "revs": revs,
    }
    cols, metrics = analyse(cache, x, y, samples_per_rev=SPR)
    assert metrics["env_band_status"] == "refused: dyno_fn_hz not provided"
    assert "envelope_spectrum" not in metrics
    assert np.all(cols["env_band"] == 0.0)


def test_env_band_refused_when_nyquist_too_low_for_the_band():
    t, fx, fy, fz, rpm, revs, x, y, fs, _ = synthetic_cut(n_rev=8)
    cache = {
        "n": t.size,
        "fs": fs,
        "feed": 0.05,
        "diam": 80.0,
        "cs_sec": 0.0,
        "ce_sec": float(t[-1]),
        "t": t,
        "fx": fx,
        "fy": fy,
        "fz": fz,
        "rpm": rpm,
        "revs": revs,
    }
    # fs is 25000 Hz (Nyquist 12500 Hz) in synthetic_cut; a resonance far above that cannot
    # be band-passed no matter the bandwidth fraction.
    cols, metrics = analyse(cache, x, y, samples_per_rev=SPR, fn_hz=20_000.0)
    assert metrics["env_band_status"].startswith("refused: effective_nyquist_hz")
    assert "envelope_spectrum" not in metrics
    assert np.all(cols["env_band"] == 0.0)


def test_env_band_refused_exactly_at_the_nyquist_boundary():
    """Regression: bandpass_envelope's own rejection is `hi >= nyquist` (strict), so the
    refusal check here must trigger at hi_needed == nyquist too, not just strictly above --
    otherwise the exact-equality case falls through and bandpass_envelope's ValueError
    escapes analyse() instead of being recorded as a graceful refusal.
    """
    t, fx, fy, fz, rpm, revs, x, y, fs, _ = synthetic_cut(n_rev=8)
    cache = {
        "n": t.size,
        "fs": fs,
        "feed": 0.05,
        "diam": 80.0,
        "cs_sec": 0.0,
        "ce_sec": float(t[-1]),
        "t": t,
        "fx": fx,
        "fy": fy,
        "fz": fz,
        "rpm": rpm,
        "revs": revs,
    }
    _, probe = analyse(cache, x, y, samples_per_rev=SPR)
    nyquist = probe["effective_nyquist_hz"]
    bandwidth_frac = 0.2
    # Solve fn_hz so hi_needed == nyquist exactly.
    fn_hz = nyquist / (1.0 + bandwidth_frac / 2.0)
    _, metrics = analyse(
        cache,
        x,
        y,
        samples_per_rev=SPR,
        fn_hz=fn_hz,
        envelope_bandwidth_frac=bandwidth_frac,
    )
    assert metrics["env_band_status"].startswith("refused: effective_nyquist_hz")
    assert "envelope_spectrum" not in metrics


def test_env_band_computed_when_fn_hz_fits_within_nyquist():
    t, fx, fy, fz, rpm, revs, x, y, fs, _ = synthetic_cut(n_rev=8)
    cache = {
        "n": t.size,
        "fs": fs,
        "feed": 0.05,
        "diam": 80.0,
        "cs_sec": 0.0,
        "ce_sec": float(t[-1]),
        "t": t,
        "fx": fx,
        "fy": fy,
        "fz": fz,
        "rpm": rpm,
        "revs": revs,
    }
    # fs=25000 Hz -> Nyquist 12500 Hz; 2300 Hz with a 20% band comfortably fits.
    cols, metrics = analyse(cache, x, y, samples_per_rev=SPR, fn_hz=2300.0)
    assert metrics["env_band_status"] == "computed"
    assert "envelope_spectrum" in metrics
    assert len(metrics["envelope_spectrum"]["freqs"]) > 0
    assert len(metrics["envelope_spectrum"]["freqs"]) == len(
        metrics["envelope_spectrum"]["amplitude"]
    )
    assert cols["env_band"].shape == cols["resid_z"].shape
    assert np.all(np.isfinite(cols["env_band"]))
    assert np.all(cols["env_band"] >= 0.0)


def test_metrics_record_effective_nyquist_and_validity():
    t, fx, fy, fz, rpm, revs, x, y, fs, _ = synthetic_cut(n_rev=8)
    cache = {
        "n": t.size,
        "fs": fs,
        "feed": 0.05,
        "diam": 80.0,
        "cs_sec": 0.0,
        "ce_sec": float(t[-1]),
        "t": t,
        "fx": fx,
        "fy": fy,
        "fz": fz,
        "rpm": rpm,
        "revs": revs,
    }
    _, metrics = analyse(cache, x, y, samples_per_rev=SPR, fn_hz=2300.0)
    assert metrics["effective_fs_hz"] > 0
    assert metrics["effective_nyquist_hz"] == metrics["effective_fs_hz"] / 2
    # Kistler's own guidance: valid quantitative range is fn/5.
    assert abs(metrics["quantitative_limit_hz"] - 460.0) < 1e-6


def test_mount_deg_rotates_the_signature_between_fc_and_ff():
    """Ground truth for the mount_deg translation. frame_transform at 90 deg maps
    ff = -fx*sin(90) + fy*cos(90) = -fx, so a signature that sits on Fx with Fy flat is
    invisible on Ff at mount_deg=0 and fully present on Ff at mount_deg=90. This is the
    gate the design's Phase 6 asks for before a real tool_setup supplies a non-zero angle:
    if frame_transform silently ignored mount_deg, the bake would keep shipping the tool
    frame as a pass-through for every linked cut.
    """
    n_rev, spr = 30, SPR
    n = n_rev * spr
    revs = np.arange(n, dtype=np.float64) / spr
    fs = 25_000.0
    t = revs * 60.0 / 1200.0
    phase = 2 * np.pi * revs
    signature = 50.0 + 5.0 * np.sin(phase) + 2.0 * np.sin(3 * phase)
    fx = signature
    fy = np.zeros(n)
    fz = np.full(n, 10.0)
    rpm = np.full(n, 1200.0)
    rho = 40.0 - 0.05 * revs / (2 * np.pi)
    theta = 2 * np.pi * revs
    x = rho * np.cos(theta)
    y = rho * np.sin(theta)
    cache = dict(n=n, fs=fs, feed=0.05, diam=80.0, cs_sec=0.0, ce_sec=float(t[-1]),
                 t=t, fx=fx, fy=fy, fz=fz, rpm=rpm, revs=revs)

    _, m0 = analyse(cache, x, y, channel="ff", mount_deg=0.0, samples_per_rev=spr)
    assert m0["mount_deg"] == 0.0
    assert max(abs(v) for v in m0["tsa_signature"]) < 1e-6      # Ff = Fy = 0

    _, m90 = analyse(cache, x, y, channel="ff", mount_deg=90.0, samples_per_rev=spr)
    assert m90["mount_deg"] == 90.0
    assert max(abs(v) for v in m90["tsa_signature"]) > 3.0      # Ff = -Fx = the signature


def test_analyse_kwargs_translate_to_the_recipe_frame_transform_reads():
    """analyse() builds a recipe from its kwargs; process_diag_row injects mount_deg /
    h_matrix onto frame_transform's params directly. Both paths must land the same values
    where frame_transform actually reads them. This proves analyse(mount_deg, h_matrix,
    channel) is byte-for-byte identical to run_recipe over a hand-built recipe with those
    same three params set on frame_transform -- the translation the direct-injection bake
    path implicitly trusts.
    """
    import copy

    from diag.recipe import DEFAULT_RECIPE
    from diag.runner import run_recipe, seed_columns

    t, fx, fy, fz, rpm, revs, x, y, fs, _ = synthetic_cut()
    cache = cache_of(t, fx, fy, fz, rpm, revs, fs)
    swap = [[0.0, 1.0, 0.0], [1.0, 0.0, 0.0], [0.0, 0.0, 1.0]]

    cols_a, metrics_a = analyse(
        cache, x, y, channel="fc", mount_deg=37.0, h_matrix=np.array(swap), samples_per_rev=SPR
    )

    recipe = copy.deepcopy(DEFAULT_RECIPE)
    ft = next(s for s in recipe["steps"] if s["op"] == "frame_transform")
    ft["params"].update({"channel": "fc", "mount_deg": 37.0, "h_matrix": swap})
    cols_r, metrics_r = run_recipe(recipe, seed_columns(cache, x, y))

    for name in cols_a:
        np.testing.assert_array_equal(cols_a[name], cols_r[name], err_msg=f"column {name}")
    assert metrics_a["mount_deg"] == metrics_r["mount_deg"] == 37.0
    assert metrics_a["h_matrix_applied"] is metrics_r["h_matrix_applied"] is True
    assert metrics_a["channel"] == metrics_r["channel"] == "fc"


def test_h_matrix_correction_moves_signal_between_channels():
    """A synthetic case where the ONLY way the anomaly-bearing signal ends up on Ff is
    through the H-matrix correction: fx carries the signature, fy is flat. An h_matrix that
    swaps x<->y must move that signature onto ff; without it (h_matrix=None), ff stays flat.
    This is the ground-truth test for Task 1 -- it fails if h_matrix is silently ignored.
    """
    n_rev, spr = 30, SPR
    n = n_rev * spr
    revs = np.arange(n, dtype=np.float64) / spr
    fs = 25_000.0
    t = revs * 60.0 / 1200.0
    phase = 2 * np.pi * revs
    signature = 50.0 + 5.0 * np.sin(phase) + 2.0 * np.sin(3 * phase)
    fx = signature
    fy = np.zeros(n)
    fz = np.full(n, 10.0)  # placeholder, channel under test is 'ff'
    rpm = np.full(n, 1200.0)
    rho = 40.0 - 0.05 * revs / (2 * np.pi)
    theta = 2 * np.pi * revs
    x = rho * np.cos(theta)
    y = rho * np.sin(theta)

    cache = dict(
        n=n,
        fs=fs,
        feed=0.05,
        diam=80.0,
        cs_sec=0.0,
        ce_sec=float(t[-1]),
        t=t,
        fx=fx,
        fy=fy,
        fz=fz,
        rpm=rpm,
        revs=revs,
    )

    # No correction: ff = fy = 0 throughout -- no signature to find.
    _, metrics_plain = analyse(cache, x, y, channel="ff", samples_per_rev=spr)
    assert metrics_plain["h_matrix_applied"] is False
    assert max(abs(v) for v in metrics_plain["tsa_signature"]) < 1e-6

    # h_matrix swaps x and y: corrected fx' = fy = 0, fy' = fx = signature.
    # With mount_deg=0 (identity rotation), ff = fy' = signature.
    swap = np.array([[0.0, 1.0, 0.0], [1.0, 0.0, 0.0], [0.0, 0.0, 1.0]])
    columns, metrics = analyse(
        cache, x, y, channel="ff", h_matrix=swap, samples_per_rev=spr
    )
    assert metrics["h_matrix_applied"] is True
    assert (
        max(abs(v) for v in metrics["tsa_signature"]) > 3.0
    )  # the signature is now on ff


# --- analyse() equivalence gate ----------------------------------------------
#
# Task 6's gate tests call run_recipe() directly -- they prove the executor is
# equivalent, not that analyse()'s kwargs->recipe translation is correct. A wrong
# mapping (dropped mount_deg, mis-wired gi_k, wrong envelope enable condition) would
# leave those green while analyse() itself silently changed for every caller. These
# two tests close that gap: they drive analyse() with the exact calls the fixtures
# were captured from and demand byte-for-byte agreement. The shared golden comparison
# (and its portability caveat) lives in conftest as assert_columns_match_golden.


def _assert_analyse_matches_golden(golden_path, nondegenerate=(), **kwargs):
    t, fx, fy, fz, rpm, revs, x, y, fs, _ = synthetic_cut()
    cache = cache_of(t, fx, fy, fz, rpm, revs, fs)
    cols, metrics = analyse(cache, x, y, **kwargs)
    assert_columns_match_golden(cols, metrics, golden_path, nondegenerate)


def test_analyse_default_reproduces_the_frozen_golden_exactly():
    _assert_analyse_matches_golden(
        GOLDEN_DEFAULT,
        nondegenerate=("tsa_resid", "resid_z", "gi_star"),
        samples_per_rev=256,
    )


def test_analyse_with_fn_hz_reproduces_the_frozen_envelope_golden_exactly():
    _assert_analyse_matches_golden(
        GOLDEN_ENVELOPE, nondegenerate=("env_band",), samples_per_rev=256, fn_hz=1000.0
    )
