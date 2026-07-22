#!/usr/bin/env python3
r"""FAST 25 (.EMD/.HIS) trace decoder — INVESTIGATION MODULE (not yet wired in).

Status: DEFERRED. The FAST 25 machine stores each run's trace as a binary `.HIS` file
inside its `.EMD` (zip) archive. Unlike the FAST 250 CSV export (handled by
fast_mapping.normalize_fast_csv), the `.HIS` is a raw/structured float stream whose channel
ORDER and NAMES are not carried in the archive. Producing labelled, plottable series
therefore requires verifying the channel layout against the ECS configuration — until that
is done, decoding would yield mis-labelled plots, which is worse than no trace. So FAST 25
run *metadata* is imported (scripts/import_fast25.py) but its traces are intentionally left
un-enqueued.

Findings so far (from Data/Batch/**/*.EMD):
  * Header: bytes 0-1 = 01 00 (record/version marker); byte 2 varies (0x23=35, 0x21=33) —
    a plausible CHANNEL COUNT; byte 3 = 00; then a run of zero padding.
  * Float32 data (little-endian) begins ~offset 14: the first values read as sane physical
    readings, e.g. 250.17 (pyrometer °C), 400.0 (a setpoint), ~20.0 (room-temp TC).
  * File sizes do NOT reduce to a clean channels×samples rectangle (e.g. 653626 B →
    ~163403 floats after the header, not divisible by 33/35), so there is either a trailing
    partial record, a footer, or per-record markers still to be accounted for.

To finish this decoder (follow-up):
  1. Confirm the channel count (byte 2?) and float start offset across many EMDs.
  2. Recover channel NAMES/order — most likely from ECS_CONFIG.mdb::Messwerte (250 measurement
     definitions) and/or the per-run .MMW/.MPS blocks, cross-checked against known run values
     (e.g. run 8738 peaked at 1600°C / 63 kN — find the columns whose max matches).
  3. Emit the SAME canonical CSV normalize_fast_csv produces (`time_s [s]` + named channels,
     US decimals), mapping labels through fast_mapping._CANON so 25 and 250 share series keys.
  4. Wire routing in fast_orchestrator.process_row: when import_archive_path endswith '.EMD',
     call fast_his.decode_emd(raw) instead of normalize_fast_csv(raw) — everything downstream
     (upload, series catalog, dashboard) is unchanged. Then enqueue FAST 25 fast_run_data rows
     (machine_format='25', import_archive_path=<EMD path>) and run the orchestrator.

Run as a script to dump the structural analysis for a given EMD:
    py scripts/fast_his.py path/to/V01_XXXX.EMD
"""
from __future__ import annotations

import struct
import sys
import zipfile
from io import BytesIO


def read_his_bytes(emd_path_or_bytes) -> bytes:
    """Return the .HIS member bytes from an .EMD zip (path or raw bytes)."""
    src = emd_path_or_bytes if isinstance(emd_path_or_bytes, (bytes, bytearray)) \
        else open(emd_path_or_bytes, "rb").read()
    with zipfile.ZipFile(BytesIO(src)) as zf:
        name = next(n for n in zf.namelist() if n.upper().endswith(".HIS"))
        return zf.read(name)


def analyse(his: bytes) -> dict:
    """Structural summary used to reverse-engineer the layout (no decoding claims)."""
    n = len(his)
    header = his[:16]
    byte2 = his[2]
    # float32 stream from offset 14 (empirically where sane values begin)
    off = 14
    floats = struct.unpack(f"<{(n - off) // 4}f", his[off:off + ((n - off) // 4) * 4])
    sane = [f for f in floats[:200] if -1e4 < f < 1e5]
    return {
        "len": n,
        "header_hex": header.hex(" "),
        "byte2_maybe_channels": byte2,
        "float_start": off,
        "n_floats": len(floats),
        "first_sane_values": [round(x, 2) for x in sane[:12]],
    }


def decode_emd(raw: bytes) -> dict:  # noqa: ARG001
    """Placeholder for the canonical-CSV decoder — see module docstring, steps 1-4."""
    raise NotImplementedError(
        "FAST 25 .HIS decoding is not yet verified; run metadata is imported but traces are "
        "deferred. See scripts/fast_his.py docstring for the investigation status."
    )


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit("usage: py scripts/fast_his.py path/to/V01_XXXX.EMD")
    info = analyse(read_his_bytes(sys.argv[1]))
    for k, v in info.items():
        print(f"{k}: {v}")
