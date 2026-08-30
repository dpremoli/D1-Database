"""D1LC live-cache reader — parsing half of the format written by
scripts/matlab/process_force.m::write_live_cache.

Byte-identical in layout to apps/force-app/backend/app/d1lc.py and
plugins/filter-service/app/d1lc.py, which already document each other as copies. This is a
third reader rather than a shared import because scripts/ is not an installable package and
the orchestrator must run standalone on the host.

32-byte LE header (magic 'D1LC', version, N, Fs, feed, diam, cs_sec, ce_sec) then six
float32[N] arrays: t, Fx, Fy, Fz, rpm, revs_cum.
"""

from __future__ import annotations

import struct

import numpy as np

MAGIC = 0x44314C43  # 'D1LC'


def read_d1lc(path: str) -> dict:
    """Parse a live_cache.bin into a dict of header fields plus the six arrays."""
    with open(path, "rb") as f:
        buf = f.read()
    magic, version, n = struct.unpack_from("<III", buf, 0)
    if magic != MAGIC:
        raise ValueError(f"bad D1LC magic {magic:#x}")
    fs, feed, diam, cs, ce = struct.unpack_from("<fffff", buf, 12)
    a = np.frombuffer(buf, dtype="<f4", count=n * 6, offset=32).reshape(6, n)
    return {
        "version": version,
        "n": n,
        "fs": float(fs),
        "feed": float(feed),
        "diam": float(diam),
        "cs_sec": float(cs),
        "ce_sec": float(ce),
        "t": a[0].copy(),
        "fx": a[1].copy(),
        "fy": a[2].copy(),
        "fz": a[3].copy(),
        "rpm": a[4].copy(),
        "revs": a[5].copy(),
    }
