"""D1LC live-cache binary format (must match scripts/matlab/process_force.m's
write_live_cache and the client parser in liveCache.ts): 32-byte little-endian header
(magic 'D1LC', version, N, Fs, feed, diam, cs_sec, ce_sec) then six float32[N] arrays
t, Fx, Fy, Fz, rpm, revs_cum."""

from __future__ import annotations

import struct
from dataclasses import dataclass

import numpy as np

MAGIC = 0x44314C43


@dataclass
class Cache:
    fs: float
    feed: float
    diam: float
    cs_sec: float
    ce_sec: float
    t: np.ndarray
    fx: np.ndarray
    fy: np.ndarray
    fz: np.ndarray
    rpm: np.ndarray
    revs: np.ndarray

    @property
    def n(self) -> int:
        return self.t.size


def parse(buf: bytes) -> Cache:
    magic, version, n = struct.unpack_from("<III", buf, 0)
    if magic != MAGIC:
        raise ValueError(f"bad D1LC magic {magic:#x}")
    fs, feed, diam, cs, ce = struct.unpack_from("<fffff", buf, 12)
    arrs = np.frombuffer(buf, dtype="<f4", count=n * 6, offset=32)
    a = arrs.reshape(6, n)
    return Cache(
        fs,
        feed,
        diam,
        cs,
        ce,
        a[0].copy(),
        a[1].copy(),
        a[2].copy(),
        a[3].copy(),
        a[4].copy(),
        a[5].copy(),
    )


def serialise(c: Cache, stride: int = 1) -> bytes:
    """Emit a D1LC binary, optionally strided (preview decimation)."""
    sl = slice(None, None, max(1, stride))
    t = c.t[sl]
    head = struct.pack(
        "<IIIfffff",
        MAGIC,
        1,
        t.size,
        c.fs,
        c.feed,
        c.diam,
        c.cs_sec,
        c.ce_sec,
    )
    body = b"".join(
        np.ascontiguousarray(x[sl], dtype="<f4").tobytes()
        for x in (c.t, c.fx, c.fy, c.fz, c.rpm, c.revs)
    )
    return head + body
