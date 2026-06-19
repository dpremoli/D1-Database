"""Minimal D1F binary reader (header parse + strided channel read).

Duplicated from heavy-data-worker so each plugin is self-contained.
Format spec: plugins/heavy-data-worker/app/lib/parser.py
"""

import struct
from pathlib import Path
from typing import BinaryIO

import numpy as np

HEADER_SIZE = 64
MAGIC = b"D1FORCE\n"

CHANNEL_NAMES = ("Fx", "Fy", "Fz", "Mx", "My", "Mz")


def parse_header(f: BinaryIO) -> dict:
    """Return the 64-byte D1F header as a dict."""
    magic = f.read(8)
    if magic != MAGIC:
        msg = f"Not a D1F file — bad magic: {magic!r}"
        raise ValueError(msg)
    version = struct.unpack("B", f.read(1))[0]
    n_channels = struct.unpack("B", f.read(1))[0]
    (sample_rate_hz,) = struct.unpack("d", f.read(8))
    (n_samples,) = struct.unpack("Q", f.read(8))
    return {
        "version": version,
        "n_channels": n_channels,
        "sample_rate_hz": sample_rate_hz,
        "n_samples": n_samples,
    }


def read_channel(
    filepath: str | Path,
    header: dict,
    channel_index: int,
    max_samples: int = 131_072,
) -> np.ndarray:
    """Read a single channel, strided to at most *max_samples* points.

    Memory usage: O(min(max_samples, n_samples) × 4) bytes.
    """
    n_ch = header["n_channels"]
    n_samples = header["n_samples"]
    row_bytes = n_ch * 4
    stride = max(1, n_samples // max_samples)

    values: list[float] = []
    with open(filepath, "rb") as f:
        pos = 0
        while pos < n_samples:
            f.seek(HEADER_SIZE + pos * row_bytes + channel_index * 4)
            raw = f.read(4)
            if len(raw) < 4:
                break
            values.append(struct.unpack("f", raw)[0])
            pos += stride

    return np.array(values, dtype=np.float64)
