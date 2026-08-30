"""D1AN analysis-attribute binary — per-point derived channels for the diag octree.

Mirrors the D1OC/D1GR convention used elsewhere in the pipeline: a fixed little-endian
header followed by column-major float32 arrays, so the body is memmap-able. As with those
formats the magic is the integer that spells the tag in hex (0x4431414E == 'D1AN'), written
little-endian.

Columns are float32 without exception. int16 packing was tried for the grid octree and
reverted: PotreeConverter ignores an extra dim's scale/offset and stores the raw codes, so
the viewer receives codes instead of physical values. See process_grid_row.

Layout:
    magic u32 | version u32 | n u32 | n_cols u32
    n_cols * 16-byte ASCII column names (null-padded)
    n_cols * float32[n], column-major
"""

from __future__ import annotations

import struct

import numpy as np

MAGIC = 0x4431414E  # 'D1AN'
VERSION = 1
NAME_BYTES = 16
_HEADER = "<IIII"
HEADER_SIZE = struct.calcsize(_HEADER)


def write_d1an(path: str, columns: dict[str, np.ndarray]) -> None:
    """Write named float32 columns. All columns must share one length."""
    if not columns:
        raise ValueError("no columns to write")
    lengths = {int(np.asarray(v).size) for v in columns.values()}
    if len(lengths) != 1:
        raise ValueError(
            f"all columns must have the same length, got {sorted(lengths)}"
        )
    n = lengths.pop()
    for name in columns:
        if len(name.encode("ascii")) > NAME_BYTES:
            raise ValueError(f"column name {name!r} exceeds {NAME_BYTES} bytes")
    with open(path, "wb") as f:
        f.write(struct.pack(_HEADER, MAGIC, VERSION, n, len(columns)))
        for name in columns:
            f.write(name.encode("ascii").ljust(NAME_BYTES, b"\x00"))
        for arr in columns.values():
            f.write(np.ascontiguousarray(arr, dtype="<f4").tobytes())


def read_d1an(path: str) -> dict[str, np.ndarray]:
    """Read a D1AN file back into {name: float32 array}."""
    with open(path, "rb") as f:
        raw = f.read(HEADER_SIZE)
        if len(raw) < HEADER_SIZE:
            raise ValueError("truncated D1AN header")
        magic, version, n, n_cols = struct.unpack(_HEADER, raw)
        if magic != MAGIC:
            raise ValueError(f"bad D1AN magic {magic:#x}")
        if version != VERSION:
            raise ValueError(f"unsupported D1AN version {version}")
        names = [
            f.read(NAME_BYTES).rstrip(b"\x00").decode("ascii") for _ in range(n_cols)
        ]
        body = np.frombuffer(f.read(n * n_cols * 4), dtype="<f4")
    if body.size != n * n_cols:
        raise ValueError("truncated D1AN body")
    return {nm: body[i * n : (i + 1) * n].copy() for i, nm in enumerate(names)}
