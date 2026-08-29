"""SimSource shape/profile, Decimator envelope, FrmIntegrator continuity."""

import numpy as np

from app.acquisition.consumers import Decimator, FrmIntegrator
from app.config import SIGNAL_CHANNELS, RecordConfig
from app.dsp import sum_axes, tacho_column
from app.sources.sim import SimSource


def _drain(src):
    src.start()
    chunks = []
    while True:
        c = src.read()
        if c is None:
            break
        chunks.append(c)
    return chunks


def test_sim_shape_and_profile():
    cfg = RecordConfig(sample_rate=4000, duration_sec=1.0, rpm=1200)
    src = SimSource(cfg, realtime=False)
    chunks = _drain(src)
    t = np.concatenate([c[0] for c in chunks])
    data = np.concatenate([c[1] for c in chunks])
    assert data.shape[1] == len(SIGNAL_CHANNELS)
    assert abs(t.size - 4000) <= src.chunk  # ~rate*duration
    axes = sum_axes(data)
    # steady middle should carry more force than the air-cut start
    assert np.mean(np.abs(axes["Fz"][:100])) < np.mean(np.abs(axes["Fz"][1800:2200]))


def test_decimator_minmax():
    dec = Decimator(bins=2)
    t = np.linspace(0, 1, 100)
    axes = {"Fx": np.zeros(100), "Fy": np.zeros(100), "Fz": np.arange(100.0)}
    out = dec.process(t, axes)
    assert out.shape == (2, 7)
    # Fz max in the second half must be the global max (99)
    assert out[1, 6] == 99.0 and out[0, 5] == 0.0  # fzmin of first bin


def test_frm_integrator_continuity():
    # frm_from_cut=False integrates from t=0 (this test checks the continuous integration itself).
    cfg = RecordConfig(sample_rate=5000, duration_sec=2.0, rpm=1500, feed=0.05, frm_from_cut=False)
    src = SimSource(cfg, realtime=False)
    frm = FrmIntegrator(cfg)
    total_pts = 0
    last_theta = 0.0
    measured_any = False
    src.start()
    while True:
        c = src.read()
        if c is None:
            break
        t, data = c
        pts, rpm, tacho_ok = frm.process(t, {**sum_axes(data)}, tacho_column(data))
        total_pts += pts.shape[0]
        assert frm._theta >= last_theta  # angle only accumulates
        last_theta = frm._theta
        # Warm-up: the sim emits 20 ms chunks and a 1500 RPM / 1 PPR tacho pulses every 40 ms, so
        # the first interval cannot be timed until a second edge arrives a chunk or two later.
        # Before that there is genuinely nothing to report, and 0 is the honest answer — the old
        # code only looked accurate here because it seeded the fallback with cfg.rpm.
        if tacho_ok:
            measured_any = True
            assert abs(rpm - 1500) / 1500 < 0.05
        else:
            assert rpm == 0.0
    assert measured_any, "the sim's pulse train must be measurable across chunk boundaries"
    # total revs across the run ≈ rpm/60 * duration, less the brief un-measured warm-up
    assert abs(frm._theta / (2 * np.pi) - 1500 / 60 * 2.0) / (1500 / 60 * 2.0) < 0.05
    assert total_pts > 0


def test_frm_integrator_reports_zero_rpm_for_a_stationary_tacho():
    """A silent tacho must never be reported as the configured spindle speed, and must eventually
    be flagged as a confirmed fault — not just left in the ambiguous "not yet known" warm-up state
    forever.

    Reproduces a fault found on the rig: with the hall-effect sensor stationary on the bench, every
    live frame carried rpm == cfg.rpm exactly (1200.000, then 777.000 when the config was changed),
    because FrmIntegrator seeded its fallback from cfg.rpm and then fed that value back into itself
    each chunk. The readout was indistinguishable from a healthy one — and because the high-RPM
    safety alarm compares the measured value against cfg.rpm * 1.02, a dead tacho silently disarmed
    it. Assert on cfg.rpm specifically: a plain "is it zero" check would pass even if some other
    nominal leaked through.

    `t` advances a real 0.1s per chunk (unlike reusing one fixed array) specifically so this test
    crosses TACHO_STALE_SEC and exercises the None -> False transition, not just the None warm-up
    state — see test_frm_integrator_does_not_flag_a_healthy_tacho_during_warm_up for that state on
    its own, with a genuinely pulsing tacho.
    """
    cfg = RecordConfig(sample_rate=5000, duration_sec=3.0, rpm=1200, frm_from_cut=False)
    frm = FrmIntegrator(cfg)
    chunk_n = 500  # 0.1s per chunk at 5000 Hz
    flat_tacho = np.zeros(chunk_n)  # sensor powered but not turning: no rising edges at all
    axes = {ax: np.zeros(chunk_n) for ax in ("Fx", "Fy", "Fz")}

    saw_warmup = False
    saw_confirmed_lost = False
    # 30 * 0.1s = 3s total, comfortably crossing the 2s TACHO_STALE_SEC partway through.
    for i in range(30):
        t = i * (chunk_n / cfg.sample_rate) + np.arange(chunk_n) / cfg.sample_rate
        _pts, rpm, tacho_ok = frm.process(t, axes, flat_tacho)
        assert rpm == 0.0, f"expected 0 RPM for a stationary tacho, got {rpm}"
        assert rpm != cfg.rpm, "RPM must never echo the configured spindle speed"
        if t[-1] <= FrmIntegrator.TACHO_STALE_SEC:
            # Nothing has been measured yet — genuinely unknown, not a confirmed fault.
            assert (
                tacho_ok is None
            ), "must read 'not yet known' during warm-up, not a confirmed fault"
            saw_warmup = True
        else:
            assert tacho_ok is False, "must become a confirmed fault once genuinely past warm-up"
            saw_confirmed_lost = True
    assert saw_warmup and saw_confirmed_lost, "test must actually cross the warm-up boundary"

    # The spiral must not wind on fabricated rotation either — a dead tacho would otherwise draw a
    # plausible-looking FRM fingerprint out of nothing.
    assert frm._theta == 0.0


def test_frm_integrator_does_not_flag_a_healthy_tacho_during_warm_up():
    """Regression: FrmIntegrator used to seed `_tacho_ok = False` ("no signal"), so the very first
    chunk of every real recording reported a confirmed fault before there had been any chance to
    measure a single pulse — timing an edge-pair takes at least one pulse period, which almost
    always spans a chunk boundary. alarms.ts::evaluateTacho() latches that immediately with no
    grace period, so this raised a spurious "No tacho signal" alarm at the start of EVERY healthy
    nidaq recording. A genuinely pulsing tacho must read None ("not yet known"), never False,
    before its first interval has been timed.
    """
    fs, rpm_true, ppr = 5000.0, 1500.0, 1
    cfg = RecordConfig(sample_rate=fs, rpm=rpm_true, frm_from_cut=False)
    frm = FrmIntegrator(cfg)
    chunk_n = 100  # 20 ms chunks, matching the real acquisition chunk size
    pulse_period = 60.0 / (rpm_true * ppr)  # ~40 ms — spans several 20 ms chunks

    saw_measured = False
    for i in range(10):  # 10 * 20 ms = 0.2s, comfortably inside the 2s warm-up window
        t = i * (chunk_n / fs) + np.arange(chunk_n) / fs
        tacho = ((t % pulse_period) < 0.15 * pulse_period).astype(float) * 5.0
        axes = {ax: np.zeros(chunk_n) for ax in ("Fx", "Fy", "Fz")}
        _pts, rpm, tacho_ok = frm.process(t, axes, tacho)
        assert tacho_ok is not False, (
            "a genuinely pulsing tacho must never read as a confirmed fault, even before its "
            "first interval has been timed"
        )
        if tacho_ok:
            saw_measured = True
            assert abs(rpm - rpm_true) / rpm_true < 0.05
    assert saw_measured, "the synthetic pulse train must become measurable within the test window"
