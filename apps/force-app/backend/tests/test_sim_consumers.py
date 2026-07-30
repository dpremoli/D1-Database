"""SimSource shape/profile, Decimator envelope, FrmIntegrator continuity."""
import numpy as np

from app.acquisition.consumers import Decimator, FrmIntegrator
from app.config import RecordConfig, SIGNAL_CHANNELS
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
    cfg = RecordConfig(sample_rate=5000, duration_sec=2.0, rpm=1500, feed=0.05)
    src = SimSource(cfg, realtime=False)
    frm = FrmIntegrator(cfg)
    total_pts = 0
    last_theta = 0.0
    src.start()
    while True:
        c = src.read()
        if c is None:
            break
        t, data = c
        pts, rpm = frm.process(t, {**sum_axes(data)}, tacho_column(data))
        total_pts += pts.shape[0]
        assert frm._theta >= last_theta  # angle only accumulates
        last_theta = frm._theta
        assert abs(rpm - 1500) / 1500 < 0.05
    # total revs across the run ≈ rpm/60 * duration
    assert abs(frm._theta / (2 * np.pi) - 1500 / 60 * 2.0) / (1500 / 60 * 2.0) < 0.02
    assert total_pts > 0
