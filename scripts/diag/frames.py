"""Dynamometer XYZ -> tool frame (Fc / Ff / Fp).

Every cutting-force-coefficient wear model is defined in the tool frame, the Fc/Ff ratio is
a drift-immune wear indicator, and radial detrending is natural in the tool frame and awkward
in XYZ. So this sits upstream of every analysis rather than being offered as a display option.

Turning: a static rotation set by how the dynamometer is mounted (`mount_deg`).
Milling:  the tool frame rotates with the cutter, so the per-sample spindle angle is added.

Fp is the dynamometer Z axis and is passed through unrotated — this is a planar rotation, not
a general 3-D one, which is what a table dynamometer's geometry actually supports.
"""

from __future__ import annotations

import numpy as np


def frame_transform(
    fx: np.ndarray,
    fy: np.ndarray,
    fz: np.ndarray,
    mount_deg: float,
    angle_rad: np.ndarray | None = None,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Return (Fc, Ff, Fp) in the tool frame.

    `mount_deg` is the static dyno->tool angle. `angle_rad` is the per-sample spindle angle
    for milling, or None for turning.
    """
    fx = np.asarray(fx, dtype=np.float64)
    fy = np.asarray(fy, dtype=np.float64)
    fz = np.asarray(fz, dtype=np.float64)
    phi = np.deg2rad(float(mount_deg))
    if angle_rad is not None:
        angle_rad = np.asarray(angle_rad, dtype=np.float64)
        if angle_rad.shape != fx.shape:
            raise ValueError(
                f"angle_rad shape {angle_rad.shape} does not match force shape {fx.shape}"
            )
        phi = phi + angle_rad
    c, s = np.cos(phi), np.sin(phi)
    fc = fx * c + fy * s
    ff = -fx * s + fy * c
    return fc, ff, fz
