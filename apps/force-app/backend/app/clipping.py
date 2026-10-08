"""Near-full-scale ("railed") detection for the 8 dyno sensor channels.

One definition, two callers: finalize.py applies it to each channel's whole-capture peak (the
`channels_ranging.clipped` flags the converging between-cuts auto-range reads), and the live
consumer in session.py applies it to every block as it arrives, so the operator is told
mid-cut instead of after it. A channel that rails has lost its peaks: the amp's analog output
saturated, so re-ranging up is the only fix, and it can only be done between cuts.

Only meaningful with real per-channel gains (the NI-DAQ path, where `cfg.dyno_gains` holds N/V
from the amp's ranges). Sim and replay data are already in newtons with no range to compare
against, so they never rail.
"""

from __future__ import annotations

import numpy as np

# A channel counts as railed once its peak reaches this fraction of its full-scale range.
RAIL_FRACTION = 0.99


def near_full_scale(peak: np.ndarray, full_scale: np.ndarray) -> np.ndarray:
    """Elementwise: `peak` (>= 0) is within RAIL_FRACTION of a positive `full_scale`. A
    non-positive full scale (no usable range) is never railed."""
    peak = np.asarray(peak, dtype=np.float64)
    full_scale = np.asarray(full_scale, dtype=np.float64)
    return (full_scale > 0) & (peak >= RAIL_FRACTION * full_scale)


def dyno_gain_array(gains: list[float] | None) -> np.ndarray | None:
    """The 8 per-channel volts-to-newtons gains (cfg.dyno_gains) as an array, or None when the
    config has no full set: sim and replay data is already in newtons. The rail test, the live
    view and finalize all take their gains through here, so they agree on what "has per-channel
    gains" means."""
    g = [float(x) for x in (gains or [])]
    return np.array(g[:8], dtype=np.float64) if len(g) >= 8 else None


def rail_volts(full_scale_v: float, input_limit_v: float = 0.0) -> float:
    """The voltage at which a sensor channel has no more to give (#200): the Lab Amp's analog
    full scale, or the input range of the NI-DAQ module reading it when that is smaller. An
    NI 9234 reads +/-5 V, so behind a 10 V amp output a channel stops at half its range, and a
    rail test against the amp's 10 V never fires. `input_limit_v` of 0 means not known."""
    fs = float(full_scale_v or 10.0)
    return min(fs, input_limit_v) if input_limit_v > 0 else fs


class RailDetector:
    """Per-block railing test for the live stream. Cheap enough for the acquisition hot path: a
    column-wise min and max over the block's 8 sensor columns (no |x| temporary), then 8 compares.

    `gains` is cfg.dyno_gains (N per volt, one per sensor channel); with fewer than 8 the detector
    is disabled (`enabled` False) and `update` always returns False. Railed channels latch for
    the life of the detector (one cut), growing monotonically.
    """

    def __init__(self, gains: list[float] | None, full_scale_v: float, input_limit_v: float = 0.0):
        g = dyno_gain_array(gains)
        self.enabled = g is not None
        self._gains = g if g is not None else np.zeros(8)
        self._ranges = self._gains * rail_volts(full_scale_v, input_limit_v)
        self._latched = np.zeros(8, dtype=bool)

    @property
    def any(self) -> bool:
        return bool(self._latched.any())

    @property
    def railed(self) -> list[int]:
        """Indices (0-7, in Fx1..Fz4 order) of the channels that have railed so far."""
        return [int(i) for i in np.flatnonzero(self._latched)]

    def update(self, block: np.ndarray) -> bool:
        """Fold in one block of raw volts, shape (n, >=8). Returns True when a channel newly
        railed in this block (so the caller publishes only on a change)."""
        if not self.enabled or block.shape[0] == 0:
            return False
        sensors = block[:, :8]
        peak_v = np.maximum(sensors.max(axis=0), -sensors.min(axis=0))
        hit = near_full_scale(peak_v * self._gains, self._ranges)
        new = hit & ~self._latched
        if not new.any():
            return False
        self._latched |= hit
        return True
