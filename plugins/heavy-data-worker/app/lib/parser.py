"""Binary parser for D1 Force (.d1f) files.

File layout:
  Offset  0: magic b'D1FORCE\\n'     (8 bytes)
  Offset  8: version uint8           (1 byte)
  Offset  9: n_channels uint8        (1 byte)
  Offset 10: sample_rate_hz float64  (8 bytes)
  Offset 18: n_samples uint64        (8 bytes)
  Offset 26: reserved zeros          (38 bytes)
  Offset 64: data float32, row-major (n_samples × n_channels × 4 bytes)
"""
import struct
from pathlib import Path
from typing import BinaryIO, TypedDict

import numpy as np

HEADER_SIZE = 64
MAGIC = b"D1FORCE\n"

CHANNEL_NAMES = ("Fx", "Fy", "Fz", "Mx", "My", "Mz")
CHANNEL_UNITS = ("N", "N", "N", "Nm", "Nm", "Nm")


class FileHeader(TypedDict):
    version: int
    n_channels: int
    sample_rate_hz: float
    n_samples: int


def parse_header(f: BinaryIO) -> FileHeader:
    """Parse the 64-byte D1F header from an open binary file."""
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


def strided_read(
    filepath: str | Path,
    header: FileHeader,
    target_points: int = 10_000,
) -> np.ndarray:
    """Read at most *target_points* evenly-spaced rows from the data section.

    Memory usage is O(min(target_points, n_samples) × n_channels × 4 bytes)
    regardless of file size — suitable for generating overview plots.
    """
    n_ch = header["n_channels"]
    n_samples = header["n_samples"]
    row_bytes = n_ch * 4
    stride = max(1, n_samples // target_points)

    rows: list[np.ndarray] = []
    with open(filepath, "rb") as f:
        pos = 0
        while pos < n_samples:
            f.seek(HEADER_SIZE + pos * row_bytes)
            raw = f.read(row_bytes)
            if len(raw) < row_bytes:
                break
            rows.append(np.frombuffer(raw, dtype=np.float32).copy())
            pos += stride

    return np.array(rows)  # shape: (n_points, n_channels)
