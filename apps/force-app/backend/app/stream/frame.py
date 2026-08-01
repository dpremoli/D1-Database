"""D1LF live-frame binary codec (little-endian), parsed on the client like liveCache.ts.

Layout: 44-byte header
    magic 'D1LF' (4s) | version u32 | seq u32 | t_sec f32 | rpm f32 |
    peakFx f32 | peakFy f32 | peakFz f32 | nTotal u32 | nTrace u32 | nPts u32
then trace float32[nTrace*7]  (t, fxmin,fxmax, fymin,fymax, fzmin,fzmax)
then pts   float32[nPts*3]    (x, y, c)
"""

from __future__ import annotations

import struct

import numpy as np

MAGIC = b"D1LF"
_HEADER = "<4sIIfffffIII"
HEADER_SIZE = struct.calcsize(_HEADER)  # 44


def encode_frame(
    seq: int,
    t_sec: float,
    rpm: float,
    peaks: tuple[float, float, float],
    n_total: int,
    trace: np.ndarray,  # (nTrace, 7) float32
    pts: np.ndarray,  # (nPts, 3) float32
) -> bytes:
    n_trace = int(trace.shape[0])
    n_pts = int(pts.shape[0])
    head = struct.pack(
        _HEADER,
        MAGIC,
        1,
        int(seq),
        float(t_sec),
        float(rpm),
        float(peaks[0]),
        float(peaks[1]),
        float(peaks[2]),
        int(n_total),
        n_trace,
        n_pts,
    )
    return (
        head
        + np.ascontiguousarray(trace, dtype="<f4").tobytes()
        + np.ascontiguousarray(pts, dtype="<f4").tobytes()
    )


def decode_frame(buf: bytes) -> dict:
    """Reference decoder (mirrors the client) — used by tests."""
    magic, version, seq, t_sec, rpm, pfx, pfy, pfz, n_total, n_trace, n_pts = struct.unpack_from(
        _HEADER, buf, 0
    )
    if magic != MAGIC:
        raise ValueError(f"bad D1LF magic {magic!r}")
    off = HEADER_SIZE
    trace = np.frombuffer(buf, dtype="<f4", count=n_trace * 7, offset=off).reshape(n_trace, 7)
    off += n_trace * 7 * 4
    pts = np.frombuffer(buf, dtype="<f4", count=n_pts * 3, offset=off).reshape(n_pts, 3)
    return {
        "version": version,
        "seq": seq,
        "t_sec": t_sec,
        "rpm": rpm,
        "peaks": (pfx, pfy, pfz),
        "n_total": n_total,
        "trace": trace,
        "pts": pts,
    }
