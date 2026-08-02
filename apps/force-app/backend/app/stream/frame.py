"""D1LF live-frame binary codec (little-endian), parsed on the client like liveCache.ts.

Layout: 48-byte header
    magic 'D1LF' (4s) | version u32 | seq u32 | t_sec f32 | rpm f32 |
    peakFx f32 | peakFy f32 | peakFz f32 | nTotal u32 | nTrace u32 | nSub u32 | nPts u32
then trace float32[nTrace*7]            (t, fxmin,fxmax, fymin,fymax, fzmin,fzmax)   — summed axes
then sub   float32[nTrace*nSub*2]       (min,max per sub-channel per bin)            — per-channel
then pts   float32[nPts*3]              (x, y, c)

v2 adds the per-sub-channel envelope block (nSub channels, min/max per bin, same bins as trace) so
the client can plot any individual dyno sub-channel live, not just the summed axes. nSub=0 => no
block (backward-compatible with callers that don't pass one).
"""

from __future__ import annotations

import struct

import numpy as np

MAGIC = b"D1LF"
_HEADER = "<4sIIfffffIIII"
HEADER_SIZE = struct.calcsize(_HEADER)  # 48
VERSION = 2


def encode_frame(
    seq: int,
    t_sec: float,
    rpm: float,
    peaks: tuple[float, float, float],
    n_total: int,
    trace: np.ndarray,  # (nTrace, 7) float32
    pts: np.ndarray,  # (nPts, 3) float32
    sub: np.ndarray | None = None,  # (nTrace, nSub*2) float32 min/max per sub-channel, or None
) -> bytes:
    n_trace = int(trace.shape[0])
    n_pts = int(pts.shape[0])
    n_sub = int(sub.shape[1] // 2) if sub is not None and sub.size else 0
    head = struct.pack(
        _HEADER,
        MAGIC,
        VERSION,
        int(seq),
        float(t_sec),
        float(rpm),
        float(peaks[0]),
        float(peaks[1]),
        float(peaks[2]),
        int(n_total),
        n_trace,
        n_sub,
        n_pts,
    )
    parts = [head, np.ascontiguousarray(trace, dtype="<f4").tobytes()]
    if n_sub:
        parts.append(np.ascontiguousarray(sub, dtype="<f4").tobytes())
    parts.append(np.ascontiguousarray(pts, dtype="<f4").tobytes())
    return b"".join(parts)


def decode_frame(buf: bytes) -> dict:
    """Reference decoder (mirrors the client) — used by tests."""
    (magic, version, seq, t_sec, rpm, pfx, pfy, pfz,
     n_total, n_trace, n_sub, n_pts) = struct.unpack_from(_HEADER, buf, 0)
    if magic != MAGIC:
        raise ValueError(f"bad D1LF magic {magic!r}")
    off = HEADER_SIZE
    trace = np.frombuffer(buf, dtype="<f4", count=n_trace * 7, offset=off).reshape(n_trace, 7)
    off += n_trace * 7 * 4
    sub = np.empty((n_trace, 0), dtype="<f4")
    if n_sub:
        sub = np.frombuffer(buf, dtype="<f4", count=n_trace * n_sub * 2, offset=off).reshape(
            n_trace, n_sub * 2
        )
        off += n_trace * n_sub * 2 * 4
    pts = np.frombuffer(buf, dtype="<f4", count=n_pts * 3, offset=off).reshape(n_pts, 3)
    return {
        "version": version,
        "seq": seq,
        "t_sec": t_sec,
        "rpm": rpm,
        "peaks": (pfx, pfy, pfz),
        "n_total": n_total,
        "trace": trace,
        "sub": sub,
        "pts": pts,
    }
