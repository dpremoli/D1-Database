"""D1LC writer tests: v1 byte-identity and the v2 extras trailer.

See docs/superpowers/specs/2026-09-07-milling-path-models-and-polar-design.md #4.
"""
from __future__ import annotations

import os
import struct
import tempfile

import numpy as np

from app.d1lc import parse_d1lc, write_d1lc


def _arrs(n: int = 6):
    t = np.arange(n, dtype=np.float64) * 0.01
    fx = np.arange(n, dtype=np.float64) + 10
    fy = np.arange(n, dtype=np.float64) + 20
    fz = np.arange(n, dtype=np.float64) + 30
    rpm = np.full(n, 1200.0)
    revs = np.arange(n, dtype=np.float64) * 0.02
    return t, fx, fy, fz, rpm, revs


def test_write_d1lc_without_extras_is_byte_identical_to_today(tmp_path):
    path = tmp_path / "live_cache.bin"
    t, fx, fy, fz, rpm, revs = _arrs()
    write_d1lc(str(path), t, fx, fy, fz, rpm, revs, fs=1000.0, feed=0.05, diam=80.0, cs_sec=0.0, ce_sec=0.05)
    buf = path.read_bytes()
    magic, version, n = struct.unpack_from("<III", buf, 0)
    assert magic == 0x44314C43
    assert version == 1
    assert n == 6
    assert len(buf) == 32 + 6 * 6 * 4  # header + six float32[6] arrays, no trailer


def test_write_d1lc_with_extras_writes_v2_trailer_that_round_trips():
    t, fx, fy, fz, rpm, revs = _arrs(5)
    mz = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
    fd, path = tempfile.mkstemp(suffix=".bin")
    os.close(fd)
    try:
        write_d1lc(
            path, t, fx, fy, fz, rpm, revs, fs=1000.0, feed=0.05, diam=80.0, cs_sec=0.0, ce_sec=0.04,
            extras={"Mz": mz},
        )
        buf = open(path, "rb").read()
        _, version, _ = struct.unpack_from("<III", buf, 0)
        assert version == 2
        parsed = parse_d1lc(buf)
        assert parsed["n"] == 5
        assert np.allclose(parsed["extras"]["Mz"], mz)
    finally:
        os.remove(path)


def test_write_d1lc_with_empty_extras_dict_stays_v1(tmp_path):
    path = tmp_path / "live_cache.bin"
    t, fx, fy, fz, rpm, revs = _arrs(3)
    write_d1lc(str(path), t, fx, fy, fz, rpm, revs, fs=1000.0, feed=0.05, diam=80.0, cs_sec=0.0, ce_sec=0.02, extras={})
    buf = path.read_bytes()
    _, version, _ = struct.unpack_from("<III", buf, 0)
    assert version == 1


def test_parse_d1lc_v1_has_empty_extras_dict():
    t, fx, fy, fz, rpm, revs = _arrs(4)
    fd, path = tempfile.mkstemp(suffix=".bin")
    os.close(fd)
    try:
        write_d1lc(path, t, fx, fy, fz, rpm, revs, fs=1000.0, feed=0.05, diam=80.0, cs_sec=0.0, ce_sec=0.03)
        buf = open(path, "rb").read()
        parsed = parse_d1lc(buf)
        assert parsed["extras"] == {}
    finally:
        os.remove(path)


def test_parse_d1lc_ignores_unknown_trailer_names():
    t, fx, fy, fz, rpm, revs = _arrs(3)
    fd, path = tempfile.mkstemp(suffix=".bin")
    os.close(fd)
    try:
        write_d1lc(
            path, t, fx, fy, fz, rpm, revs, fs=1000.0, feed=0.05, diam=80.0, cs_sec=0.0, ce_sec=0.02,
            extras={"Bogus": np.array([1.0, 2.0, 3.0])},
        )
        buf = open(path, "rb").read()
        parsed = parse_d1lc(buf)  # must not raise
        assert parsed["extras"] == {}
    finally:
        os.remove(path)
