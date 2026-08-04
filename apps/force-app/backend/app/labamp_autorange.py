"""Auto-range logic for the Kistler LabAmp (5167A8x) — ANALOG-OUTPUT path.

IMPORTANT: we digitise the amp's ANALOG OUTPUT with the NI-DAQ, not the amp's internal 24-bit ADC.
The amp's per-channel measuring range (/sensor/N/range == …/charge/physicalRange, a continuous value
in physical units) sets how force maps to the analog output: force = range → full-scale output
voltage (±10 V typical). The NI-DAQ then quantises that voltage with ITS ADC (fewer bits, e.g. 16).

So the V→N mapping is  N/V = range / V_fullscale , and a smaller range makes a given force swing
more of the ±V_fullscale span → the NI-DAQ digitises it with more of its codes (finer resolution).
  * too LARGE a range → small output swing → few NI-DAQ codes used → coarse resolution,
  * too SMALL a range → the analog output rails / the amp reports OR_INPUT (clipping).
The optimum is the smallest range that clears the measured peak with headroom.

With the NI-DAQ input range matched to the amp output (±V_fullscale), the force resolution reduces
to range / 2**(nidaq_bits-1) — i.e. it depends on the NI-DAQ bit depth, not the amp's 24-bit.

This module is the decision logic only (pure, testable). Measuring the peak (from a test cut via
/api/$/signal/get) and applying the range (/api/param/set) live on the amp — see labamp.py.
"""

from __future__ import annotations

import math

# The effective resolution is the BOTTLENECK of the analog-output chain: the LabAmp's analog-output
# DAC (limited to 12-bit without the recording licence) feeding the NI-DAQ (e.g. 16-bit). The NI-DAQ
# can't recover more than the 12-bit DAC gives, so the true bit depth = min(dac_bits, nidaq_bits).
LABAMP_DAC_BITS = 12
NIDAQ_BITS = 16
ANALOG_FULLSCALE_V = 10.0  # amp analog output full scale (±V), matched by the NI-DAQ input range
RANGE_MIN = 1.0
RANGE_MAX = 100_000.0


def effective_bits(dac_bits: int = LABAMP_DAC_BITS, nidaq_bits: int = NIDAQ_BITS) -> int:
    return int(min(dac_bits, nidaq_bits))


def round_up_nice(x: float) -> float:
    """Round up to the next 1/2/5 × 10^k — operator-friendly range steps."""
    if x <= 0:
        return RANGE_MIN
    exp = math.floor(math.log10(x))
    base = 10.0**exp
    for m in (1, 2, 5, 10):
        if x <= m * base * (1 + 1e-9):
            return m * base
    return 10.0 * base


def recommend_range(
    peak: float,
    headroom: float = 1.5,
    range_min: float = RANGE_MIN,
    range_max: float = RANGE_MAX,
    bits: int = LABAMP_DAC_BITS,
    fullscale_v: float = ANALOG_FULLSCALE_V,
    current: float | None = None,
) -> dict:
    """Recommend a measuring range for one channel from its measured peak magnitude, accounting for
    the analog-output chain: V→N mapping + the EFFECTIVE bit depth (min of the amp DAC & NI-DAQ)."""
    peak = abs(float(peak))
    headroom = max(1.0, float(headroom))
    rec = round_up_nice(peak * headroom)
    rec = min(max(rec, range_min), range_max)
    full = 2 ** (bits - 1)  # bipolar full-scale in codes at the effective bit depth
    resolution = rec / full  # N per LSB (input range matched to ±V_fs)
    bits_used = 0.0
    if peak > 0 and resolution > 0:
        bits_used = max(0.0, min(float(bits), math.log2(peak / resolution)))
    gain_n_per_v = rec / fullscale_v if fullscale_v > 0 else 0.0  # DynoGain (N/V) at this range
    output_pct = min(100.0, peak / rec * 100.0) if rec > 0 else 0.0  # % of ±V_fs the peak uses
    return {
        "peak": round(peak, 4),
        "current": current,
        "recommended": rec,
        "resolution": resolution,  # N / LSB at the NI-DAQ, recommended range
        "bits_used": round(bits_used, 1),  # NI-DAQ bits the signal spans (not the amp's 24)
        "gain_n_per_v": round(gain_n_per_v, 4),  # V→N: N/V = range / V_fullscale
        "output_pct": round(output_pct, 0),  # analog-output utilisation at the peak
        # would the CURRENT range clip this peak? (peak >= range rails the ±V_fs output)
        "would_clip": current is not None and peak >= float(current),
        "headroom": headroom,
    }


def recommend_ranges(
    peaks: list[float],
    currents: list[float | None] | None = None,
    headroom: float = 1.5,
    range_min: float = RANGE_MIN,
    range_max: float = RANGE_MAX,
    bits: int = LABAMP_DAC_BITS,
    fullscale_v: float = ANALOG_FULLSCALE_V,
) -> list[dict]:
    currents = currents or [None] * len(peaks)
    return [
        {
            "channel": i + 1,
            **recommend_range(
                p,
                headroom,
                range_min,
                range_max,
                bits,
                fullscale_v,
                currents[i] if i < len(currents) else None,
            ),
        }
        for i, p in enumerate(peaks)
    ]


def converge_ranges(
    peaks: list[float],
    clipped: list[bool] | None = None,
    currents: list[float | None] | None = None,
    headroom: float = 1.5,
    clip_factor: float = 2.0,
    range_min: float = RANGE_MIN,
    range_max: float = RANGE_MAX,
    bits: int = LABAMP_DAC_BITS,
    fullscale_v: float = ANALOG_FULLSCALE_V,
) -> list[dict]:
    """Recommend the NEXT-pass range per channel from the LAST recorded cut's per-channel peaks.

    This is the converging between-cuts auto-range: it runs on the peaks measured from OUR recording
    (not a live amp poll), so it's a between-cuts step, not a mid-cut gain-follower.

    A channel that RAILED (clipped) recorded a peak ≈ its current range, so its true peak is unknown
    (only a lower bound). For those we range up by `clip_factor` off the current range (a deliberate
    over-shoot that converges down over the next pass or two), not the gentle `headroom` bump
    a non-clipped, trustworthy peak gets. Channels using little of their range converge downward.
    """
    n = len(peaks)
    clipped = (clipped or [False] * n) + [False] * max(0, n - len(clipped or []))
    currents = currents or [None] * n
    out: list[dict] = []
    for i, peak in enumerate(peaks):
        cur = currents[i] if i < len(currents) else None
        rec = recommend_range(peak, headroom, range_min, range_max, bits, fullscale_v, cur)
        if clipped[i] and cur:
            # railed — true peak unknown; over-shoot off the (too-small) current range.
            bumped = min(max(round_up_nice(float(cur) * clip_factor), range_min), range_max)
            rec["recommended"] = max(rec["recommended"], bumped)
            rec["resolution"] = rec["recommended"] / (2 ** (bits - 1))
            rec["gain_n_per_v"] = (
                round(rec["recommended"] / fullscale_v, 4) if fullscale_v > 0 else 0.0
            )
            rec["output_pct"] = 100.0  # it railed
        rec["clipped"] = bool(clipped[i])
        out.append({"channel": i + 1, **rec})
    return out
