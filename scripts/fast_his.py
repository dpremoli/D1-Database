#!/usr/bin/env python3
r"""FAST 25 (.EMD/.HIS) trace decoder.

The FAST 25 machine stores each run's trace as a binary `.HIS` file inside its `.EMD` (zip)
archive. The format was reverse-engineered from the fleet:

  * Header: 14 bytes (01 00 <nch> 00 then zero padding), then the data.
  * Data is float32 little-endian, ROW-MAJOR: one fixed-width record per time sample.
  * Record width (channel count) depends on firmware era: 71 for ~2017+ runs, 31 for the
    oldest (2010-era) runs. Detected per file.
  * Sample interval is a constant 2.000 s (verified: run 8738 = 2301 samples over 4601 s;
    run 4926 = 1110 samples over 2219 s). The .HIS carries no timestamps.
  * For the 71-wide layout the channel positions are fixed and were validated by matching
    known run peaks across multiple runs (col 0 pyrometer -> peak temp; col 8 force -> peak
    kN; cols 20/23 the temp/force setpoints reach the recipe target exactly).
  * Columns 34-69 in the 71-layout are uninitialised memory (values in the ±1e6 range) and
    are dropped; setpoint-constant columns are dropped too.

decode_emd() returns the SAME dict shape as fast_mapping.normalize_fast_csv (format, plant,
recipe, run_start, n_rows, duration_s, columns, summary, csv_text) so the orchestrator and
dashboard treat FAST 25 traces exactly like the FAST 250 ones.

Run as a script to dump the structural analysis / a decode preview for an EMD:
    py scripts/fast_his.py path/to/V01_XXXX.EMD
"""
from __future__ import annotations

import os
import sys
import zipfile
from io import BytesIO

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fast_mapping import summarize_trace  # noqa: E402

SAMPLE_INTERVAL_S = 2.0
HEADER_BYTES = 14

# Fixed channel map for the 71-wide layout: column -> (key, label, unit, group).
# Keys match fast_mapping._CANON so FAST 25 and FAST 250 series share axes.
POS71 = {
    0:  ("pyro_top",     "Pyrometer (top)",     "C",      "temp"),
    2:  ("tc1",          "Thermocouple 1",      "C",      "temp"),
    3:  ("tc2",          "Thermocouple 2",      "C",      "temp"),
    4:  ("tc3",          "Thermocouple 3",      "C",      "temp"),
    5:  ("tc4",          "Thermocouple 4",      "C",      "temp"),
    6:  ("tc5",          "Thermocouple 5",      "C",      "temp"),
    7:  ("tc6",          "Thermocouple 6",      "C",      "temp"),
    8:  ("force",        "Force",               "kN",     "force"),
    10: ("piston_abs",   "Piston travel (abs)", "mm",     "position"),
    11: ("speed",        "Ram speed",           "mm/min", "speed"),
    13: ("pressure_abs", "Pressure (abs)",      "mbar",   "pressure"),
    14: ("pressure_rel", "Pressure (rel)",      "mbar",   "pressure"),
    19: ("heating_pct",  "Heating power",       "%",      "percent"),
    20: ("heating_sp",   "Temp setpoint",       "C",      "temp"),
    23: ("force_sv",     "Force (setpoint)",    "kN",     "force"),
}
POS31_PYRO = 0   # oldest layout: col 0 is still the pyrometer (validated by signature)


def read_his_bytes(emd_path_or_bytes) -> bytes:
    """Return the .HIS member bytes from an .EMD zip (path or raw bytes)."""
    src = emd_path_or_bytes if isinstance(emd_path_or_bytes, (bytes, bytearray)) \
        else open(emd_path_or_bytes, "rb").read()
    with zipfile.ZipFile(BytesIO(src)) as zf:
        name = next(n for n in zf.namelist() if n.upper().endswith(".HIS"))
        return zf.read(name)


def _matrix(his: bytes, off: int, C: int) -> np.ndarray:
    with np.errstate(all="ignore"):   # uninitialised-memory columns decode to inf/huge
        fl = np.frombuffer(his, dtype="<f4", count=(len(his) - off) // 4, offset=off).astype(np.float64)
    fl = fl.copy()
    fl[~np.isfinite(fl)] = np.nan
    m = (len(fl) // C) * C
    return fl[:m].reshape(-1, C)


def _looks_like_pyro(col: np.ndarray) -> bool:
    """A sinter pyrometer trace: peaks in [300, 2500] C, starts well below the peak."""
    v = col[np.isfinite(col)]
    if v.size < 30:
        return False
    peak = v.max()
    return 300 <= peak <= 2500 and v[:5].mean() < peak * 0.9


def detect_layout(his: bytes) -> tuple[int, int]:
    """Return (offset, channel_count). Prefers the known 71-wide record at offset 14."""
    for off, C in ((HEADER_BYTES, 71), (HEADER_BYTES, 31)):
        a = _matrix(his, off, C)
        if a.shape[0] >= 30 and _looks_like_pyro(a[:, 0]):
            return off, C
    # Fallback: search offset/period for any layout whose column 0 reads as a pyrometer.
    best = None
    for off in range(0, 20, 2):
        for C in range(20, 100):
            a = _matrix(his, off, C)
            if a.shape[0] < 30:
                continue
            if _looks_like_pyro(a[:, 0]):
                score = np.nanmean(np.abs(np.diff(a, axis=0))) / (np.nanstd(a) + 1e-9)
                if best is None or score < best[0]:
                    best = (score, off, C)
    if best:
        return best[1], best[2]
    return HEADER_BYTES, 71


def _keep_column(col: np.ndarray) -> bool:
    """Keep a channel only if it carries real, in-range, varying data."""
    v = col[np.isfinite(col)]
    if v.size < col.size * 0.5:
        return False
    rng = float(v.max() - v.min())
    return 1e-6 < rng < 1e5 and abs(np.median(v)) < 1e5


def decode_emd(raw: bytes) -> dict:
    """Decode a FAST 25 .EMD -> canonical trace dict (same shape as normalize_fast_csv)."""
    his = read_his_bytes(raw)
    off, C = detect_layout(his)
    a = _matrix(his, off, C)
    n = a.shape[0]
    time_s = np.arange(n) * SAMPLE_INTERVAL_S

    pos_map = POS71 if C == 71 else {POS31_PYRO: ("pyro_top", "Pyrometer (top)", "C", "temp")}

    columns, series_by_key, seen = [], {}, set()
    for c in range(C):
        col = a[:, c]
        mapped = pos_map.get(c)
        if mapped is None and not _keep_column(col):
            continue
        if mapped:
            key, label, unit, group = mapped
        else:
            key, label, unit, group = f"ch{c}", f"Channel {c}", "", "other"
        if key in seen:
            key = f"{key}_{c}"
        seen.add(key)
        vals = [None if not np.isfinite(x) else float(x) for x in col]
        finite = [v for v in vals if v is not None]
        if not finite:
            continue
        columns.append({"key": key, "label": label, "unit": unit, "group": group,
                        "min": min(finite), "max": max(finite)})
        series_by_key[key] = vals

    # Canonical CSV: time_s first, then each kept channel (US decimals, blank for gaps).
    header = ["time_s [s]"] + [f"{c['label']} [{c['unit']}]" if c["unit"] else c["label"] for c in columns]
    keys = [c["key"] for c in columns]
    lines = [",".join(header)]
    for r in range(n):
        row = [f"{time_s[r]:g}"]
        for k in keys:
            v = series_by_key[k][r]
            row.append("" if v is None else f"{v:g}")
        lines.append(",".join(row))

    summary = summarize_trace(series_by_key, list(time_s))
    return {
        "format": "25", "plant": None, "recipe": None, "run_start": None,
        "n_rows": n, "duration_s": float(time_s[-1] - time_s[0]) if n > 1 else 0.0,
        "columns": columns, "summary": summary,
        "csv_text": "\n".join(lines) + "\n",
    }


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit("usage: py scripts/fast_his.py path/to/V01_XXXX.EMD")
    res = decode_emd(open(sys.argv[1], "rb").read())
    off, C = detect_layout(read_his_bytes(open(sys.argv[1], "rb").read()))
    print(f"layout: offset={off} channels={C}  samples={res['n_rows']}  duration={res['duration_s']:.0f}s")
    print(f"kept {len(res['columns'])} channels; summary={res['summary']}")
    for c in res["columns"][:20]:
        print(f"  {c['key']:14s} {c['label']:22s} [{c['unit']:6s}] {c['group']:8s} {c['min']:.2f}..{c['max']:.2f}")
