"""D1LC live-cache writer — byte-identical to plugins/filter-service/app/d1lc.py,
scripts/matlab/process_force.m::write_live_cache, and the client parser liveCache.ts.

32-byte LE header (magic 'D1LC', version=1, N, Fs, feed, diam, cs_sec, ce_sec) then six
float32[N] arrays t, Fx, Fy, Fz, rpm, revs_cum. Writing this format means the finished cut renders
through the existing FrmCloud/ForceChart with no new display code.
"""

from __future__ import annotations

import struct

import numpy as np

MAGIC = 0x44314C43  # 'D1LC'


def write_d1lc(
    path: str,
    t: np.ndarray,
    fx: np.ndarray,
    fy: np.ndarray,
    fz: np.ndarray,
    rpm: np.ndarray,
    revs: np.ndarray,
    fs: float,
    feed: float,
    diam: float,
    cs_sec: float,
    ce_sec: float,
) -> None:
    n = int(t.size)
    head = struct.pack(
        "<IIIfffff", MAGIC, 1, n, float(fs), float(feed), float(diam), float(cs_sec), float(ce_sec)
    )
    with open(path, "wb") as f:
        f.write(head)
        for arr in (t, fx, fy, fz, rpm, revs):
            f.write(np.ascontiguousarray(arr, dtype="<f4").tobytes())


def read_d1lc_header(buf: bytes) -> dict:
    magic, version, n = struct.unpack_from("<III", buf, 0)
    if magic != MAGIC:
        raise ValueError(f"bad D1LC magic {magic:#x}")
    fs, feed, diam, cs, ce = struct.unpack_from("<fffff", buf, 12)
    return {
        "version": version,
        "n": n,
        "fs": fs,
        "feed": feed,
        "diam": diam,
        "cs_sec": cs,
        "ce_sec": ce,
    }


def parse_d1lc(buf: bytes) -> dict:
    """Full parse: header + the six float32[N] arrays (t, Fx, Fy, Fz, rpm, revs)."""
    h = read_d1lc_header(buf)
    n = h["n"]
    a = np.frombuffer(buf, dtype="<f4", count=n * 6, offset=32).reshape(6, n)
    return {
        **h,
        "t": a[0].copy(),
        "fx": a[1].copy(),
        "fy": a[2].copy(),
        "fz": a[3].copy(),
        "rpm": a[4].copy(),
        "revs": a[5].copy(),
    }
