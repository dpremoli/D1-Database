"""Recording configuration + the fixed dynamometer channel layout.

The channel layout intentionally matches the NI-DAQ output the MATLAB app captures (8 Kistler
charge sub-channels + a tacho), so the summing / gain / FRM / writer pipeline built here is the
exact code slice 2b reuses with a real `nidaqmx` source — only the source swaps.
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

# 9 signal channels (Time is carried separately as the raw file's column 0).
DYNO_CHANNELS: list[str] = ["Fx1", "Fx2", "Fy1", "Fy2", "Fz1", "Fz2", "Fz3", "Fz4"]
TACHO_CHANNEL = "Tacho"
SIGNAL_CHANNELS: list[str] = DYNO_CHANNELS + [TACHO_CHANNEL]

# Summed-axis definitions (Fx = Fx1+Fx2, Fy = Fy1+Fy2, Fz = Fz1+Fz2+Fz3+Fz4) — the layout the
# .mat v1.0 format and process_force.m assume.
AXIS_SUM: dict[str, list[str]] = {
    "Fx": ["Fx1", "Fx2"],
    "Fy": ["Fy1", "Fy2"],
    "Fz": ["Fz1", "Fz2", "Fz3", "Fz4"],
}


class RecordConfig(BaseModel):
    """Parameters for a (simulated, in 2a) recording run."""

    sample_name: str = Field(default="SIM-CUT", description="Sample/operation label")
    rpm: float = Field(default=1200.0, gt=0, description="Spindle speed (RPM)")
    feed: float = Field(default=0.05, gt=0, description="Feed (mm/rev)")
    diam: float = Field(default=80.0, gt=0, description="Outer diameter (mm)")
    inner_diam: float = Field(default=0.0, ge=0, description="Inner diameter (mm)")
    sample_rate: float = Field(default=25_000.0, gt=0, description="Acquisition rate (Hz)")
    duration_sec: float = Field(default=8.0, gt=0, le=600, description="Run length (s)")
    ppr: int = Field(default=1, ge=1, description="Tacho pulses per revolution")
    axis: str = Field(default="Fz", description="Axis driving the live FRM colour")

    # Nominal steady-cut force means (N) per axis — shape the synthetic cut. 2b replaces the sim.
    mean_fx: float = 40.0
    mean_fy: float = 60.0
    mean_fz: float = 120.0
    noise: float = 6.0  # gaussian noise std (N) on the summed axes

    # Free-form metadata compiled in the UI (sample/insert/tool/etc.), stamped into the .mat +
    # summary. Directus write-back of a run row is a later slice (2d); this just persists it locally.
    extra_metadata: dict[str, Any] = Field(default_factory=dict)
