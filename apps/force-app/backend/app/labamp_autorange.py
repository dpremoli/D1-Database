"""Auto-range logic for the Kistler LabAmp (5167A8x).

The amp's per-channel measuring range (/sensor/N/range == …/charge/physicalRange, a continuous
value in physical units, min 1 / max 100000, adapting to sensitivity) sets the analog full scale
that maps onto the 24-bit ADC. So:
  * too LARGE a range wastes ADC codes → coarse effective resolution / poor SNR,
  * too SMALL a range clips (the amp reports OR_INPUT / OR_ADC over-range).
The optimum is the smallest range that clears the measured peak with headroom — it maximises the
number of ADC bits the signal actually uses.

This module is the decision logic only (pure, testable). Measuring the peak (from a test cut via
/api/$/signal/get) and applying the range (/api/param/set) live on the amp — see labamp.py.
"""
from __future__ import annotations

import math

# The 5167A ADC is 24-bit; force is bipolar (±range), so the usable magnitude is 2**(bits-1) codes.
ADC_BITS = 24
RANGE_MIN = 1.0
RANGE_MAX = 100_000.0


def round_up_nice(x: float) -> float:
    """Round up to the next 1/2/5 × 10^k — operator-friendly range steps."""
    if x <= 0:
        return RANGE_MIN
    exp = math.floor(math.log10(x))
    base = 10.0 ** exp
    for m in (1, 2, 5, 10):
        if x <= m * base * (1 + 1e-9):
            return m * base
    return 10.0 * base


def recommend_range(peak: float, headroom: float = 1.5, range_min: float = RANGE_MIN,
                    range_max: float = RANGE_MAX, adc_bits: int = ADC_BITS,
                    current: float | None = None) -> dict:
    """Recommend a measuring range for one channel from its measured peak magnitude."""
    peak = abs(float(peak))
    headroom = max(1.0, float(headroom))
    rec = round_up_nice(peak * headroom)
    rec = min(max(rec, range_min), range_max)
    full = 2 ** (adc_bits - 1)          # bipolar full-scale in codes
    resolution = rec / full             # physical units per LSB
    bits_used = 0.0
    if peak > 0 and resolution > 0:
        bits_used = max(0.0, min(float(adc_bits), math.log2(peak / resolution)))
    return {
        "peak": round(peak, 4),
        "current": current,
        "recommended": rec,
        "resolution": resolution,               # physical units / LSB at the recommended range
        "bits_used": round(bits_used, 1),        # ADC bits the signal spans at the recommended range
        # would the CURRENT range clip this peak? (>= because the ADC also needs headroom)
        "would_clip": current is not None and peak >= float(current),
        "headroom": headroom,
    }


def recommend_ranges(peaks: list[float], currents: list[float | None] | None = None,
                     headroom: float = 1.5, range_min: float = RANGE_MIN,
                     range_max: float = RANGE_MAX, adc_bits: int = ADC_BITS) -> list[dict]:
    currents = currents or [None] * len(peaks)
    return [
        {"channel": i + 1, **recommend_range(p, headroom, range_min, range_max, adc_bits, currents[i] if i < len(currents) else None)}
        for i, p in enumerate(peaks)
    ]
