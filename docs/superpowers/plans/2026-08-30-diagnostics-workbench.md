# Diagnostics Workbench Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an advanced analysis window that separates the repeatable part of a machining cut from its residual, scores that residual statistically in space, and links the signal, spectrum and 3D point-cloud views bidirectionally.

**Architecture:** Server-side analysis runs as a third Potree octree variant per operation, built by a new handler in `scripts/force_orchestrator.py` that clones the existing `process_octree_row` pattern. All heavy statistics are precomputed into per-point LAS attributes (`D1AN`), so the browser only thresholds and highlights — it never computes. MATLAB's `process_force.m` remains the sole owner of cut geometry and is not modified.

**Tech Stack:** Python 3.12 (NumPy, SciPy, scikit-learn ≥ 1.3, laspy), PotreeConverter, PostgreSQL (dbmate migrations), Vue 3 + TypeScript + three.js/potree-core.

**Spec:** `docs/superpowers/specs/2026-08-30-diagnostics-workbench-design.md`

## Global Constraints

- Python target `py312`; ruff `line-length = 88`, `select = ["E","F","I","N","UP","W"]`, `ignore = ["E501"]` (root `pyproject.toml`).
- `process_force.m` is **not modified** by this plan. It is the single source of truth for cut geometry.
- LAS extra dims are **float32**, never int16. PotreeConverter ignores extra-dim scale/offset and stores raw codes — this was tried in `process_grid_row` and reverted.
- The diag handler runs at **concurrency 1**. The host also serves Directus.
- WorkingSet decimation floor is **5 000 000 points**, matching `process_force.m:43` `live_cache_points` and `_octree_threshold`'s fallback.
- Script tests import via `sys.path.insert(0, <repo>/scripts)` then `from diag import ...`. There is no `conftest.py`; follow `tests/scripts/test_fast_his.py`.
- Migrations are dbmate style: `-- migrate:up` / `-- migrate:down`, `ADD COLUMN IF NOT EXISTS`, filename `db/migrations/YYYYMMDDNNNNNN_name.sql`.
- Never claim a step passes without running it and reading the output.

---

## File Structure

**New Python package — pure functions, no DB, no subprocess, no MATLAB:**

| File | Responsibility |
|---|---|
| `scripts/diag/__init__.py` | Package marker |
| `scripts/diag/d1lc.py` | D1LC live-cache reader (mirrors the existing copies) |
| `scripts/diag/frames.py` | Dyno XYZ → tool frame (Fc/Ff/Fp) |
| `scripts/diag/angular.py` | Angular resampling, TSA, order spectrum |
| `scripts/diag/detrend.py` | Radial detrend + robust z-score |
| `scripts/diag/d1an.py` | D1AN binary format writer/reader |
| `scripts/diag/pipeline.py` | Wires the above into one analysis pass |

**Modified:**

| File | Change |
|---|---|
| `scripts/force_orchestrator.py` | Add `claim_diag` / `process_diag_row` / `handle_diags`, wire into `run_queue` + daemon loop |
| `db/migrations/20260830000104_diag_workbench.sql` | New — `diag_*` columns |

**Tests:** `tests/scripts/diag/test_{d1an,frames,angular,detrend,pipeline}.py`

Tasks 1–5 are pure Python and testable with no MATLAB, no database, and no PotreeConverter. Tasks 6–7 are the integration layer.

---

### Task 1: D1AN binary format

Self-contained, no dependencies on other tasks. Do this first so later tasks have a concrete output format to target.

**Files:**
- Create: `scripts/diag/__init__.py`
- Create: `scripts/diag/d1an.py`
- Test: `tests/scripts/diag/test_d1an.py`

**Interfaces:**
- Consumes: nothing
- Produces:
  - `write_d1an(path: str, columns: dict[str, np.ndarray]) -> None`
  - `read_d1an(path: str) -> dict[str, np.ndarray]`
  - `MAGIC: int = 0x4431414E`

Format (mirrors the D1OC/D1GR convention — the integer spells the tag in hex, written little-endian):

```
magic    u32  = 0x4431414E
version  u32  = 1
n        u32  row count
n_cols   u32  column count
names    n_cols * 16 bytes, ASCII, null-padded
data     n_cols * float32[n], column-major
```

- [ ] **Step 1: Write the failing test**

```python
# tests/scripts/diag/test_d1an.py
import os
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", "scripts"))

from diag import d1an


def test_round_trip_preserves_columns(tmp_path):
    cols = {
        "t": np.linspace(0.0, 1.0, 64, dtype=np.float32),
        "resid_z": np.random.default_rng(0).normal(size=64).astype(np.float32),
    }
    p = str(tmp_path / "a.d1an")
    d1an.write_d1an(p, cols)
    back = d1an.read_d1an(p)
    assert set(back) == {"t", "resid_z"}
    for k in cols:
        np.testing.assert_allclose(back[k], cols[k], rtol=0, atol=0)


def test_rejects_ragged_columns(tmp_path):
    cols = {"a": np.zeros(4, np.float32), "b": np.zeros(5, np.float32)}
    with pytest.raises(ValueError, match="same length"):
        d1an.write_d1an(str(tmp_path / "b.d1an"), cols)


def test_rejects_bad_magic(tmp_path):
    p = tmp_path / "bad.d1an"
    p.write_bytes(b"\x00" * 32)
    with pytest.raises(ValueError, match="magic"):
        d1an.read_d1an(str(p))


def test_rejects_overlong_column_name(tmp_path):
    cols = {"x" * 17: np.zeros(4, np.float32)}
    with pytest.raises(ValueError, match="name"):
        d1an.write_d1an(str(tmp_path / "c.d1an"), cols)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/scripts/diag/test_d1an.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'diag'`

- [ ] **Step 3: Write the implementation**

```python
# scripts/diag/__init__.py
"""Diagnostics Workbench analysis package.

Pure NumPy/SciPy signal and spatial statistics consumed by the diag handler in
scripts/force_orchestrator.py. Deliberately free of database, subprocess and MATLAB
dependencies so every function here is testable in isolation.
"""
```

```python
# scripts/diag/d1an.py
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
        raise ValueError(f"all columns must have the same length, got {sorted(lengths)}")
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/scripts/diag/test_d1an.py -v`
Expected: 4 passed

- [ ] **Step 5: Lint and commit**

```bash
ruff check scripts/diag tests/scripts/diag
git add scripts/diag/__init__.py scripts/diag/d1an.py tests/scripts/diag/test_d1an.py
git commit -m "feat(diag): add D1AN analysis-attribute binary format"
```

---

### Task 2: Frame transform

**Files:**
- Create: `scripts/diag/frames.py`
- Test: `tests/scripts/diag/test_frames.py`

**Interfaces:**
- Consumes: nothing
- Produces: `frame_transform(fx, fy, fz, mount_deg: float, angle_rad: np.ndarray | None = None) -> tuple[np.ndarray, np.ndarray, np.ndarray]` returning `(fc, ff, fp)`

The transform is a rotation in the dynamometer XY plane. `mount_deg` is the static angle from the dyno frame to the tool frame. For milling, `angle_rad` adds the per-sample spindle angle so the tool frame rotates with the cutter; for turning it is `None`. `Fp` is the dyno Z axis and is not rotated.

- [ ] **Step 1: Write the failing test**

```python
# tests/scripts/diag/test_frames.py
import os
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", "scripts"))

from diag.frames import frame_transform


def test_zero_mount_angle_is_identity():
    fx = np.array([1.0, 2.0, 3.0])
    fy = np.array([4.0, 5.0, 6.0])
    fz = np.array([7.0, 8.0, 9.0])
    fc, ff, fp = frame_transform(fx, fy, fz, mount_deg=0.0)
    np.testing.assert_allclose(fc, fx)
    np.testing.assert_allclose(ff, fy)
    np.testing.assert_allclose(fp, fz)


def test_ninety_degrees_swaps_axes():
    fx = np.array([1.0, 0.0])
    fy = np.array([0.0, 1.0])
    fz = np.zeros(2)
    fc, ff, fp = frame_transform(fx, fy, fz, mount_deg=90.0)
    # Fc =  fx cos + fy sin ;  Ff = -fx sin + fy cos
    np.testing.assert_allclose(fc, [0.0, 1.0], atol=1e-12)
    np.testing.assert_allclose(ff, [-1.0, 0.0], atol=1e-12)
    np.testing.assert_allclose(fp, fz)


def test_rotation_preserves_planar_magnitude():
    rng = np.random.default_rng(1)
    fx, fy = rng.normal(size=256), rng.normal(size=256)
    fz = np.zeros(256)
    fc, ff, _ = frame_transform(fx, fy, fz, mount_deg=37.5)
    np.testing.assert_allclose(fc**2 + ff**2, fx**2 + fy**2, rtol=1e-12)


def test_milling_angle_rotates_per_sample():
    fx = np.array([1.0, 1.0])
    fy = np.array([0.0, 0.0])
    fz = np.zeros(2)
    ang = np.array([0.0, np.pi / 2])
    fc, ff, _ = frame_transform(fx, fy, fz, mount_deg=0.0, angle_rad=ang)
    np.testing.assert_allclose(fc, [1.0, 0.0], atol=1e-12)
    np.testing.assert_allclose(ff, [0.0, -1.0], atol=1e-12)


def test_angle_length_must_match():
    with pytest.raises(ValueError, match="angle_rad"):
        frame_transform(
            np.zeros(4), np.zeros(4), np.zeros(4), 0.0, angle_rad=np.zeros(3)
        )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/scripts/diag/test_frames.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'diag.frames'`

- [ ] **Step 3: Write the implementation**

```python
# scripts/diag/frames.py
"""Dynamometer XYZ -> tool frame (Fc / Ff / Fp).

Every cutting-force-coefficient wear model is defined in the tool frame, the Fc/Ff ratio is
a drift-immune wear indicator, and radial detrending is natural in the tool frame and awkward
in XYZ. So this sits upstream of every analysis rather than being offered as a display option.

Turning: a static rotation set by how the dynamometer is mounted (`mount_deg`).
Milling:  the tool frame rotates with the cutter, so the per-sample spindle angle is added.

Fp is the dynamometer Z axis and is passed through unrotated — this is a planar rotation, not
a general 3-D one, which is what a table dynamometer's geometry actually supports.
"""

from __future__ import annotations

import numpy as np


def frame_transform(
    fx: np.ndarray,
    fy: np.ndarray,
    fz: np.ndarray,
    mount_deg: float,
    angle_rad: np.ndarray | None = None,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Return (Fc, Ff, Fp) in the tool frame.

    `mount_deg` is the static dyno->tool angle. `angle_rad` is the per-sample spindle angle
    for milling, or None for turning.
    """
    fx = np.asarray(fx, dtype=np.float64)
    fy = np.asarray(fy, dtype=np.float64)
    fz = np.asarray(fz, dtype=np.float64)
    phi = np.deg2rad(float(mount_deg))
    if angle_rad is not None:
        angle_rad = np.asarray(angle_rad, dtype=np.float64)
        if angle_rad.shape != fx.shape:
            raise ValueError(
                f"angle_rad shape {angle_rad.shape} does not match force shape {fx.shape}"
            )
        phi = phi + angle_rad
    c, s = np.cos(phi), np.sin(phi)
    fc = fx * c + fy * s
    ff = -fx * s + fy * c
    return fc, ff, fz
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/scripts/diag/test_frames.py -v`
Expected: 5 passed

- [ ] **Step 5: Lint and commit**

```bash
ruff check scripts/diag tests/scripts/diag
git add scripts/diag/frames.py tests/scripts/diag/test_frames.py
git commit -m "feat(diag): add dyno-to-tool frame transform"
```

---

### Task 3: Angular resampling, TSA, order spectrum

The highest-leverage piece. `revs_cum` already exists in the D1LC cache, so resampling to equal angular increments is a single `np.interp`.

**Files:**
- Create: `scripts/diag/angular.py`
- Test: `tests/scripts/diag/test_angular.py`

**Interfaces:**
- Consumes: nothing
- Produces:
  - `angular_resample(revs_cum, sig, samples_per_rev: int) -> tuple[np.ndarray, np.ndarray]` returning `(rev_grid, resampled)`
  - `tsa(resampled, samples_per_rev: int) -> tuple[np.ndarray, np.ndarray]` returning `(signature, residual)`; `residual` is truncated to whole revolutions
  - `order_spectrum(resampled, samples_per_rev: int) -> tuple[np.ndarray, np.ndarray]` returning `(orders, amplitude)`

- [ ] **Step 1: Write the failing test**

```python
# tests/scripts/diag/test_angular.py
import os
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", "scripts"))

from diag.angular import angular_resample, order_spectrum, tsa

SPR = 256


def test_constant_rate_resample_round_trips():
    revs = np.linspace(0.0, 10.0, 10 * SPR + 1)
    sig = np.sin(2 * np.pi * 3.0 * revs)  # order 3
    grid, out = angular_resample(revs, sig, SPR)
    np.testing.assert_allclose(out, np.sin(2 * np.pi * 3.0 * grid), atol=1e-6)


def test_varying_rpm_collapses_swept_tone_to_fixed_order():
    # Spindle accelerates: revs advance quadratically in time. A tone locked to shaft
    # angle is a frequency sweep in time but a single fixed order in the angular domain.
    t = np.linspace(0.0, 10.0, 200_000)
    revs = 0.5 * t**2
    sig = np.sin(2 * np.pi * 5.0 * revs)  # order 5, always
    _, out = angular_resample(revs, sig, SPR)
    orders, amp = order_spectrum(out, SPR)
    assert abs(orders[np.argmax(amp)] - 5.0) < 0.05


def test_tsa_recovers_signature_and_zero_residual_when_perfectly_periodic():
    revs = np.linspace(0.0, 20.0, 20 * SPR + 1)
    sig = np.sin(2 * np.pi * 1.0 * revs) + 0.5 * np.sin(2 * np.pi * 4.0 * revs)
    _, out = angular_resample(revs, sig, SPR)
    signature, residual = tsa(out, SPR)
    assert signature.size == SPR
    assert np.max(np.abs(residual)) < 1e-6


def test_tsa_residual_isolates_a_one_off_event():
    rng = np.random.default_rng(3)
    revs = np.linspace(0.0, 20.0, 20 * SPR + 1)
    sig = np.sin(2 * np.pi * 1.0 * revs)
    _, out = angular_resample(revs, sig, SPR)
    out = out.copy()
    out[5 * SPR + 40] += 10.0  # single implanted spike
    _, residual = tsa(out, SPR)
    assert np.argmax(np.abs(residual)) == 5 * SPR + 40
    assert np.max(np.abs(residual)) > 5.0
    _ = rng


def test_resample_requires_monotonic_revs():
    revs = np.array([0.0, 1.0, 0.5, 2.0])
    with pytest.raises(ValueError, match="monotonic"):
        angular_resample(revs, np.zeros(4), SPR)


def test_order_spectrum_orders_are_in_cycles_per_rev():
    revs = np.linspace(0.0, 32.0, 32 * SPR + 1)
    sig = np.sin(2 * np.pi * 7.0 * revs)
    _, out = angular_resample(revs, sig, SPR)
    orders, amp = order_spectrum(out, SPR)
    assert abs(orders[np.argmax(amp)] - 7.0) < 0.05
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/scripts/diag/test_angular.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'diag.angular'`

- [ ] **Step 3: Write the implementation**

```python
# scripts/diag/angular.py
"""Angular-domain (order) analysis.

Resampling to equal angular increments makes everything spindle-synchronous stationary
regardless of speed variation, which matters because face turning changes cutting speed
continuously as the radius falls. Two things fall out of it:

  * order spectrum — insert-passing harmonics land in fixed integer bins, so chatter shows
    up as NON-integer orders rather than as a peak you have to interpret;
  * time-synchronous averaging — the per-revolution mean is the repeatable signature (tool
    geometry, runout, fixture), and the residual is what does not repeat. The residual is
    the anomaly substrate every downstream statistic runs on.

`revs_cum` is already integrated from the tacho by process_force.m and carried in the D1LC
cache, so resampling is one np.interp and costs almost nothing.
"""

from __future__ import annotations

import numpy as np


def angular_resample(
    revs_cum: np.ndarray, sig: np.ndarray, samples_per_rev: int
) -> tuple[np.ndarray, np.ndarray]:
    """Resample `sig` onto a uniform grid of shaft revolutions.

    Returns (rev_grid, resampled). `revs_cum` must be non-decreasing — it is a cumulative
    angle, so a decrease means the tacho integration is corrupt and interpolating through it
    would silently fabricate samples.
    """
    revs_cum = np.asarray(revs_cum, dtype=np.float64)
    sig = np.asarray(sig, dtype=np.float64)
    if revs_cum.shape != sig.shape:
        raise ValueError(
            f"revs_cum shape {revs_cum.shape} does not match sig shape {sig.shape}"
        )
    if revs_cum.size < 2:
        raise ValueError("need at least two samples to resample")
    if np.any(np.diff(revs_cum) < 0):
        raise ValueError("revs_cum must be monotonic non-decreasing")
    if samples_per_rev < 1:
        raise ValueError("samples_per_rev must be >= 1")
    r0, r1 = float(revs_cum[0]), float(revs_cum[-1])
    n = int(np.floor((r1 - r0) * samples_per_rev))
    if n < 1:
        raise ValueError("span covers less than one resampled step")
    grid = r0 + np.arange(n, dtype=np.float64) / samples_per_rev
    return grid, np.interp(grid, revs_cum, sig)


def tsa(
    resampled: np.ndarray, samples_per_rev: int
) -> tuple[np.ndarray, np.ndarray]:
    """Time-synchronous average over whole revolutions.

    Returns (signature, residual). `signature` is the per-revolution mean of length
    `samples_per_rev`; `residual` is the input minus that signature, truncated to whole
    revolutions (so it is shorter than the input whenever the cut does not end on a
    revolution boundary — callers must use the returned length, not the input's).
    """
    resampled = np.asarray(resampled, dtype=np.float64)
    n_rev = resampled.size // samples_per_rev
    if n_rev < 1:
        raise ValueError("need at least one full revolution for TSA")
    block = resampled[: n_rev * samples_per_rev].reshape(n_rev, samples_per_rev)
    signature = block.mean(axis=0)
    return signature, (block - signature).ravel()


def order_spectrum(
    resampled: np.ndarray, samples_per_rev: int
) -> tuple[np.ndarray, np.ndarray]:
    """Single-sided amplitude spectrum in orders (cycles per revolution)."""
    resampled = np.asarray(resampled, dtype=np.float64)
    n = resampled.size
    if n < 2:
        raise ValueError("need at least two samples for a spectrum")
    w = np.hanning(n)
    spec = np.abs(np.fft.rfft((resampled - resampled.mean()) * w))
    amp = spec * (2.0 / w.sum())
    orders = np.fft.rfftfreq(n, d=1.0 / samples_per_rev)
    return orders, amp
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/scripts/diag/test_angular.py -v`
Expected: 6 passed

- [ ] **Step 5: Lint and commit**

```bash
ruff check scripts/diag tests/scripts/diag
git add scripts/diag/angular.py tests/scripts/diag/test_angular.py
git commit -m "feat(diag): add angular resampling, TSA and order spectrum"
```

---

### Task 4: Radial detrend and robust z-score

The step that stops the anomaly detector from rediscovering geometry. In face turning the cutting speed falls with radius, so raw force carries a deterministic radial trend; without removing it, any global outlier statistic flags the part centre and the entry transient on every cut.

**Files:**
- Create: `scripts/diag/detrend.py`
- Test: `tests/scripts/diag/test_detrend.py`

**Interfaces:**
- Consumes: nothing
- Produces: `radial_detrend(r, v, n_bins: int = 200, min_per_bin: int = 8) -> np.ndarray` returning `resid_z`

Uses binned median and MAD rather than a polynomial fit: the trend shape is unknown and a median is not dragged by the very outliers being looked for. A single pass is not enough on its own — a spatially contiguous macrozone can be the majority of the points in the single narrow bin it falls in, past the median's 50% breakdown point; the implementation must pool each output bin's statistics from a wider neighbourhood and reweight once, excluding already-flagged points, to stay robust against exactly the anomaly it is trying to detect.

- [ ] **Step 1: Write the failing test**

```python
# tests/scripts/diag/test_detrend.py
import os
import sys

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", "scripts"))

from diag.detrend import radial_detrend


def test_pure_radial_ramp_yields_no_significant_outliers():
    # THE regression test: a clean ramp with no implanted anomaly must not light up.
    rng = np.random.default_rng(0)
    r = np.linspace(10.0, 40.0, 50_000)
    v = 100.0 - 2.0 * r + rng.normal(scale=1.0, size=r.size)
    z = radial_detrend(r, v)
    assert np.mean(np.abs(z) > 4.0) < 0.001


def test_implanted_hotspot_is_recovered():
    rng = np.random.default_rng(1)
    r = np.linspace(10.0, 40.0, 50_000)
    v = 100.0 - 2.0 * r + rng.normal(scale=1.0, size=r.size)
    v[20_000:20_200] += 25.0
    z = radial_detrend(r, v)
    assert np.median(z[20_000:20_200]) > 8.0


def test_nonlinear_trend_is_removed():
    rng = np.random.default_rng(2)
    r = np.linspace(10.0, 40.0, 50_000)
    v = 0.05 * (r - 25.0) ** 3 + rng.normal(scale=1.0, size=r.size)
    z = radial_detrend(r, v)
    assert np.mean(np.abs(z) > 4.0) < 0.001


def test_sparse_bins_do_not_produce_nan():
    r = np.concatenate([np.linspace(0.0, 1.0, 500), np.array([50.0, 50.1])])
    v = np.concatenate([np.zeros(500), np.array([1.0, 2.0])])
    z = radial_detrend(r, v)
    assert np.all(np.isfinite(z))


def test_output_length_matches_input():
    r = np.linspace(0.0, 1.0, 1000)
    assert radial_detrend(r, np.zeros(1000)).size == 1000
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/scripts/diag/test_detrend.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'diag.detrend'`

- [ ] **Step 3: Write the implementation**

```python
# scripts/diag/detrend.py
"""Radial detrending and robust scoring.

In face turning the cutting speed changes continuously as the radius falls, so the force
carries a strong deterministic radial trend. Run any global outlier statistic on the raw
signal and it will faithfully report that the middle of the part differs from the edge — on
every cut, forever. Removing the radial trend first is what makes the remaining variation
attributable to the material rather than to the geometry.

Binned median + MAD rather than a polynomial fit: the trend shape is not known a priori, and
a median is not dragged around by the very outliers being searched for -- up to a point. A
macrozone is spatially contiguous, so it can be the *majority* of the points in the bin it
falls in; median has only a 50% breakdown point, so a single pass lets a large-enough,
dense-enough hotspot pull its own bin's "normal" trend toward itself and understate its own
z-score. Two fixes: each output bin pools its statistics from a wider neighbourhood of
adjacent bins (diluting a locally-dominant anomaly without losing resolution on genuine
curvature), and one reweighting pass excludes points already flagged before the trend is
recomputed, the way a Hampel filter refines its own threshold.
"""

from __future__ import annotations

import numpy as np

_MAD_TO_SIGMA = 1.4826
_REFINE_Z = 3.5
_MAX_PASSES = 2
_WINDOW_HALF_SPAN = 2  # aggregate +/-2 neighbouring bins per output centre (5 bins total)


def _bin_trend(
    r: np.ndarray, v: np.ndarray, edges: np.ndarray, min_per_bin: int, weight: np.ndarray
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """One pass of moving-window median/MAD, using only points where `weight` is True.

    Output resolution is one value per bin, but each bin's statistics pool points from
    `_WINDOW_HALF_SPAN` bins on either side too. A macrozone can be a large fraction of the
    single bin it falls in without being a large fraction of that wider pooled window, which
    is what keeps a spatially contiguous anomaly under the median's 50% breakdown point.
    """
    n_bins = edges.size - 1
    idx = np.clip(np.digitize(r, edges) - 1, 0, n_bins - 1)
    centres = 0.5 * (edges[:-1] + edges[1:])
    med = np.full(n_bins, np.nan)
    mad = np.full(n_bins, np.nan)
    order = np.argsort(idx, kind="stable")
    bounds = np.searchsorted(idx[order], np.arange(n_bins + 1))
    for b in range(n_bins):
        lo_bin = max(0, b - _WINDOW_HALF_SPAN)
        hi_bin = min(n_bins - 1, b + _WINDOW_HALF_SPAN)
        sel = order[bounds[lo_bin] : bounds[hi_bin + 1]]
        sel = sel[weight[sel]]
        if sel.size >= min_per_bin:
            vb = v[sel]
            m = np.median(vb)
            med[b] = m
            mad[b] = np.median(np.abs(vb - m))
    return med, mad, centres


def radial_detrend(
    r: np.ndarray, v: np.ndarray, n_bins: int = 200, min_per_bin: int = 8
) -> np.ndarray:
    """Return a robust z-score of `v` against its own radial trend.

    Bins by radius, takes the median and MAD in each sufficiently-populated bin, interpolates
    both across radius, then reports (v - trend) / (1.4826 * MAD). Bins with fewer than
    `min_per_bin` samples are ignored and interpolated across, so a thin outer ring cannot
    define its own baseline from three points. A flagged-point-exclusion pass follows (see
    module docstring) so a dense, spatially contiguous anomaly does not corrupt the trend it
    is supposed to stand out from.
    """
    r = np.asarray(r, dtype=np.float64)
    v = np.asarray(v, dtype=np.float64)
    if r.shape != v.shape:
        raise ValueError(f"r shape {r.shape} does not match v shape {v.shape}")
    if r.size == 0:
        return np.zeros(0, dtype=np.float64)

    lo, hi = float(np.min(r)), float(np.max(r))
    if not np.isfinite(lo) or not np.isfinite(hi) or hi <= lo:
        return np.zeros_like(v)

    edges = np.linspace(lo, hi, n_bins + 1)
    weight = np.ones(v.shape, dtype=bool)
    z = np.zeros_like(v)

    for _ in range(_MAX_PASSES):
        med, mad, centres = _bin_trend(r, v, edges, min_per_bin, weight)
        good = np.isfinite(med)
        if not np.any(good):
            return np.zeros_like(v)

        trend = np.interp(r, centres[good], med[good])
        scale = np.interp(r, centres[good], mad[good]) * _MAD_TO_SIGMA
        # A bin can be genuinely noiseless (a flat synthetic, a saturated region). Fall back
        # to the global scale there rather than dividing by zero and reporting infinite
        # outliers.
        global_scale = float(np.median(mad[good])) * _MAD_TO_SIGMA
        if not np.isfinite(global_scale) or global_scale <= 0:
            global_scale = 1.0
        scale = np.where(np.isfinite(scale) & (scale > 0), scale, global_scale)
        z = (v - trend) / scale

        new_weight = np.abs(z) <= _REFINE_Z
        if np.array_equal(new_weight, weight):
            break
        weight = new_weight

    return z
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/scripts/diag/test_detrend.py -v`
Expected: 5 passed

- [ ] **Step 5: Lint and commit**

```bash
ruff check scripts/diag tests/scripts/diag
git add scripts/diag/detrend.py tests/scripts/diag/test_detrend.py
git commit -m "feat(diag): add radial detrend with robust z-score"
```

---

### Task 5: D1LC reader and the pipeline pass

Wires Tasks 1–4 into one analysis pass, and adds the synthetic ground-truth test that validates the science rather than the plumbing.

**Files:**
- Create: `scripts/diag/d1lc.py`
- Create: `scripts/diag/pipeline.py`
- Test: `tests/scripts/diag/test_pipeline.py`

**Interfaces:**
- Consumes: `diag.frames.frame_transform`, `diag.angular.{angular_resample,tsa,order_spectrum}`, `diag.detrend.radial_detrend`, `diag.d1an.write_d1an`
- Produces:
  - `read_d1lc(path: str) -> dict` with keys `n, fs, feed, diam, cs_sec, ce_sec, t, fx, fy, fz, rpm, revs`
  - `analyse(cache: dict, x: np.ndarray, y: np.ndarray, *, mount_deg: float = 0.0, samples_per_rev: int = 256, fn_hz: float | None = None, channel: str = "fp") -> tuple[dict[str, np.ndarray], dict]` returning `(columns, metrics)`

`columns` is the D1AN column dict; `metrics` is the JSON-serialisable metrics record. `channel` selects which of the frame-transformed axes drives the pipeline, defaulting to `"fp"` (the unrotated dyno Z axis, matching the app's own FRM colour-axis default) rather than `"fc"`, since Fc/Ff are not a real tool-frame decomposition until a real `mount_deg` exists (see the design spec's Phase 6).

The D1LC reader mirrors `apps/force-app/backend/app/d1lc.py` and `plugins/filter-service/app/d1lc.py`. Those are already documented as byte-identical copies; this is a third, and its docstring must say so.

- [ ] **Step 1: Write the failing test**

```python
# tests/scripts/diag/test_pipeline.py
import os
import struct
import sys

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", "scripts"))

from diag.pipeline import analyse, read_d1lc

SPR = 256


def _write_d1lc(path, t, fx, fy, fz, rpm, revs, fs):
    head = struct.pack(
        "<IIIfffff", 0x44314C43, 1, t.size, float(fs), 0.05, 80.0, 0.0, float(t[-1])
    )
    with open(path, "wb") as f:
        f.write(head)
        for a in (t, fx, fy, fz, rpm, revs):
            f.write(np.ascontiguousarray(a, dtype="<f4").tobytes())


def _synthetic_cut(n_rev=40, spr=SPR, anomaly_rev=25.0, anomaly_span=0.05):
    """A clean spiral with one implanted force anomaly at a known revolution."""
    n = n_rev * spr
    revs = np.arange(n, dtype=np.float64) / spr
    fs = 25_000.0
    t = revs * 60.0 / 1200.0
    # repeatable per-rev signature + noise
    phase = 2 * np.pi * revs
    fz = 120.0 + 4.0 * np.sin(phase) + 1.5 * np.sin(3 * phase)
    rng = np.random.default_rng(7)
    fz = fz + rng.normal(scale=0.4, size=n)
    hit = np.abs(revs - anomaly_rev) < anomaly_span
    fz[hit] += 30.0
    fx = np.zeros(n)
    fy = np.zeros(n)
    rpm = np.full(n, 1200.0)
    rho = 40.0 - 0.05 * revs
    x, y = rho * np.cos(phase), rho * np.sin(phase)
    return t, fx, fy, fz, rpm, revs, x, y, fs, hit


def test_d1lc_round_trip(tmp_path):
    t, fx, fy, fz, rpm, revs, _, _, fs, _ = _synthetic_cut(n_rev=4)
    p = str(tmp_path / "c.bin")
    _write_d1lc(p, t, fx, fy, fz, rpm, revs, fs)
    c = read_d1lc(p)
    assert c["n"] == t.size
    np.testing.assert_allclose(c["fz"], fz.astype(np.float32), rtol=1e-6)


def test_pipeline_recovers_implanted_anomaly_location():
    """The test that validates the science: an anomaly implanted at a known revolution
    must come back as the strongest residual at that same revolution."""
    t, fx, fy, fz, rpm, revs, x, y, fs, hit = _synthetic_cut()
    cache = {
        "n": t.size, "fs": fs, "feed": 0.05, "diam": 80.0,
        "cs_sec": 0.0, "ce_sec": float(t[-1]),
        "t": t, "fx": fx, "fy": fy, "fz": fz, "rpm": rpm, "revs": revs,
    }
    cols, metrics = analyse(cache, x, y, samples_per_rev=SPR)
    peak_rev = cols["rev"][int(np.argmax(np.abs(cols["resid_z"])))]
    assert abs(peak_rev - 25.0) < 0.2
    assert metrics["n_points"] == cols["resid_z"].size


def test_pipeline_columns_are_aligned_and_finite():
    t, fx, fy, fz, rpm, revs, x, y, fs, _ = _synthetic_cut(n_rev=8)
    cache = {
        "n": t.size, "fs": fs, "feed": 0.05, "diam": 80.0,
        "cs_sec": 0.0, "ce_sec": float(t[-1]),
        "t": t, "fx": fx, "fy": fy, "fz": fz, "rpm": rpm, "revs": revs,
    }
    cols, _ = analyse(cache, x, y, samples_per_rev=SPR)
    sizes = {k: v.size for k, v in cols.items()}
    assert len(set(sizes.values())) == 1, sizes
    for k, v in cols.items():
        assert np.all(np.isfinite(v)), k
        assert v.dtype == np.float32, k


def test_metrics_record_effective_nyquist_and_validity():
    t, fx, fy, fz, rpm, revs, x, y, fs, _ = _synthetic_cut(n_rev=8)
    cache = {
        "n": t.size, "fs": fs, "feed": 0.05, "diam": 80.0,
        "cs_sec": 0.0, "ce_sec": float(t[-1]),
        "t": t, "fx": fx, "fy": fy, "fz": fz, "rpm": rpm, "revs": revs,
    }
    _, metrics = analyse(cache, x, y, samples_per_rev=SPR, fn_hz=2300.0)
    assert metrics["effective_fs_hz"] > 0
    assert metrics["effective_nyquist_hz"] == metrics["effective_fs_hz"] / 2
    # Kistler's own guidance: valid quantitative range is fn/5.
    assert abs(metrics["quantitative_limit_hz"] - 460.0) < 1e-6
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/scripts/diag/test_pipeline.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'diag.pipeline'`

- [ ] **Step 3: Write the D1LC reader**

```python
# scripts/diag/d1lc.py
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
```

- [ ] **Step 4: Write the pipeline**

```python
# scripts/diag/pipeline.py
"""One analysis pass: D1LC cache + spiral coordinates -> D1AN columns + metrics.

Phase 1 scope. Emits t, rev, tsa_resid and resid_z; the spatial statistics columns
(gi_star, gi_sig, glosh, cluster_id) and env_band arrive in later phases.

No geometry is recomputed here. process_force.m owns the spiral, the cut window and drift
compensation; this module consumes revs_cum and (x, y) as given. Recomputing either would
reintroduce exactly the divergence the pipeline already guards against elsewhere.

Channel choice: frame_transform always returns (Fc, Ff, Fp), but until a real tool-setup
record supplies a genuine `mount_deg` (deferred — see the design spec's Phase 6), Fc/Ff are
just a rotation of Fx/Fy by whatever default angle was passed in, not a real tool-frame
decomposition. The app's own FRM colour axis already defaults to Fz (RecordConfig.axis), so
Phase 1 analyses `Fp` (the unrotated dyno Z axis) by default, and only switches to Fc/Ff once
a caller supplies a real mount_deg for a real setup.
"""

from __future__ import annotations

import numpy as np

from .angular import angular_resample, order_spectrum, tsa
from .d1lc import read_d1lc
from .detrend import radial_detrend
from .frames import frame_transform

__all__ = ["analyse", "read_d1lc"]

DEFAULT_SAMPLES_PER_REV = 256
_CHANNELS = ("fc", "ff", "fp")


def analyse(
    cache: dict,
    x: np.ndarray,
    y: np.ndarray,
    *,
    mount_deg: float = 0.0,
    samples_per_rev: int = DEFAULT_SAMPLES_PER_REV,
    fn_hz: float | None = None,
    channel: str = "fp",
) -> tuple[dict[str, np.ndarray], dict]:
    """Run the Phase 1 analysis.

    `cache` is a read_d1lc() result. `x`/`y` are the spiral coordinates for the same samples.
    `channel` selects which of the frame-transformed axes ('fc', 'ff', 'fp') drives the TSA /
    order-spectrum / detrend pipeline; see the module docstring for why this defaults to 'fp'.
    Returns (columns, metrics): `columns` is the D1AN column dict (all float32, all the same
    length), `metrics` is JSON-serialisable.

    The returned columns are shorter than the input: TSA truncates to whole revolutions, and
    resampling puts everything on an angular grid. `rev` and `t` are emitted alongside so a
    consumer never has to reconstruct the mapping back to the original samples.
    """
    if channel not in _CHANNELS:
        raise ValueError(f"channel must be one of {_CHANNELS}, got {channel!r}")
    revs = np.asarray(cache["revs"], dtype=np.float64)
    t_in = np.asarray(cache["t"], dtype=np.float64)
    frame = dict(zip(_CHANNELS, frame_transform(cache["fx"], cache["fy"], cache["fz"], mount_deg)))
    sig = frame[channel]

    rev_grid, sig_ang = angular_resample(revs, sig, samples_per_rev)
    _, t_ang = angular_resample(revs, t_in, samples_per_rev)
    _, x_ang = angular_resample(revs, np.asarray(x, dtype=np.float64), samples_per_rev)
    _, y_ang = angular_resample(revs, np.asarray(y, dtype=np.float64), samples_per_rev)

    signature, residual = tsa(sig_ang, samples_per_rev)
    n = residual.size  # whole revolutions only
    rev_grid, t_ang, x_ang, y_ang = (a[:n] for a in (rev_grid, t_ang, x_ang, y_ang))

    r = np.hypot(x_ang, y_ang)
    resid_z = radial_detrend(r, residual)

    orders, amp = order_spectrum(sig_ang, samples_per_rev)
    keep = orders <= 16.0

    span_sec = float(t_in[-1] - t_in[0]) if t_in.size > 1 else 0.0
    eff_fs = (t_in.size / span_sec) if span_sec > 0 else 0.0
    metrics: dict = {
        "n_points": int(n),
        "n_revolutions": int(n // samples_per_rev),
        "samples_per_rev": int(samples_per_rev),
        "cached_fs_hz": float(cache.get("fs", 0.0)),
        "effective_fs_hz": eff_fs,
        "effective_nyquist_hz": eff_fs / 2.0,
        "mount_deg": float(mount_deg),
        "channel": channel,
        "tsa_signature": [float(v) for v in signature],
        "order_spectrum": {
            "orders": [float(v) for v in orders[keep]],
            "amplitude": [float(v) for v in amp[keep]],
        },
        "resid_z_p99": float(np.percentile(np.abs(resid_z), 99)) if n else 0.0,
    }
    if fn_hz is not None and fn_hz > 0:
        metrics["dyno_fn_hz"] = float(fn_hz)
        metrics["quantitative_limit_hz"] = float(fn_hz) / 5.0

    columns = {
        "t": t_ang.astype(np.float32),
        "rev": rev_grid.astype(np.float32),
        "tsa_resid": residual.astype(np.float32),
        "resid_z": resid_z.astype(np.float32),
    }
    return columns, metrics
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/scripts/diag/ -v`
Expected: all pass

- [ ] **Step 6: Lint and commit**

```bash
ruff check scripts/diag tests/scripts/diag
git add scripts/diag/d1lc.py scripts/diag/pipeline.py tests/scripts/diag/test_pipeline.py
git commit -m "feat(diag): add D1LC reader and phase-1 analysis pipeline"
```

---

### Task 6: Database columns

**Files:**
- Create: `db/migrations/20260830000104_diag_workbench.sql`

**Interfaces:**
- Consumes: nothing
- Produces: columns `diag_status`, `diag_path`, `diag_points`, `diag_error`, `diag_requested_at`, `diag_version`, `diag_metrics` on `machining_force_analysis`

- [ ] **Step 1: Write the migration**

```sql
-- migrate:up
ALTER TABLE machining_force_analysis
    ADD COLUMN IF NOT EXISTS diag_status        text,
    ADD COLUMN IF NOT EXISTS diag_path          text,
    ADD COLUMN IF NOT EXISTS diag_points        bigint,
    ADD COLUMN IF NOT EXISTS diag_error         text,
    ADD COLUMN IF NOT EXISTS diag_requested_at  timestamptz,
    ADD COLUMN IF NOT EXISTS diag_version       integer,
    ADD COLUMN IF NOT EXISTS diag_metrics       jsonb;

-- migrate:down
ALTER TABLE machining_force_analysis
    DROP COLUMN IF EXISTS diag_status,
    DROP COLUMN IF EXISTS diag_path,
    DROP COLUMN IF EXISTS diag_points,
    DROP COLUMN IF EXISTS diag_error,
    DROP COLUMN IF EXISTS diag_requested_at,
    DROP COLUMN IF EXISTS diag_version,
    DROP COLUMN IF EXISTS diag_metrics;
```

- [ ] **Step 2: Apply and verify**

Run: `dbmate up`, then check `\d machining_force_analysis` lists all seven `diag_*` columns.

- [ ] **Step 3: Verify down is reversible**

Run: `dbmate down && dbmate up` — both must succeed.

- [ ] **Step 4: Commit**

```bash
git add db/migrations/20260830000104_diag_workbench.sql
git commit -m "feat(diag): add diag_* columns to machining_force_analysis"
```

---

### Task 7: Orchestrator handler

**Files:**
- Modify: `scripts/force_orchestrator.py`

**Interfaces:**
- Consumes: `diag.pipeline.{analyse, read_d1lc}`, `diag.d1an.write_d1an`, and the existing `_read_octree_bin`, `_patch_octree_climits`, `mlq`, `unc_for`, `_ml_literal`, `OCTREE_DIR`, `MATLAB_SRC`
- Produces: `claim_diag(conn, limit=1)`, `process_diag_row(conn, row, exe, timeout, matlab_opts, potree_exe) -> str`, `handle_diags(conn, exe) -> int`

`DIAG_CACHE_POINTS = 5_000_000` — the analysis needs its own high-resolution cache, not the dashboard's 250 000-point one.

- [ ] **Step 1: Add constants and the claim function**

```python
DIAG_CACHE_POINTS = 5_000_000
DIAG_VERSION = 1
DIAG_SAMPLES_PER_REV = 256
```

```python
def claim_diag(conn, limit: int = 1):
    """Claim pending diagnostics rows. Concurrency is deliberately 1: this host also serves
    Directus, and a clustering pass that starves the database mid-experiment is a worse
    outcome than a slow queue."""
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            """UPDATE machining_force_analysis SET diag_status='processing', updated_at=now()
                 WHERE id IN (SELECT id FROM machining_force_analysis
                               WHERE diag_status='pending'
                               ORDER BY diag_requested_at NULLS LAST LIMIT %s
                                 FOR UPDATE SKIP LOCKED)
             RETURNING id, operation_id, archive_path, pulses_per_rev, inner_diameter,
                       outer_diameter, filter_chain::text AS filter_chain""",
            [limit],
        )
        rows = cur.fetchall()
    conn.commit()
    return rows
```

- [ ] **Step 2: Add the row processor**

```python
def process_diag_row(
    conn, row, exe: str, timeout: int, matlab_opts: dict, potree_exe: str
) -> str:
    """One MATLAB launch emits both the spiral cloud and a dense live cache; the diag package
    turns them into D1AN attribute columns; laspy + PotreeConverter publish the diag octree
    under OCTREE_DIR/diag/<op_id>/."""
    import laspy
    import numpy as np

    sys.path.insert(0, str(SCRIPT_DIR))
    from diag.angular import angular_resample
    from diag.d1an import write_d1an
    from diag.pipeline import analyse, read_d1lc

    outdir = tempfile.mkdtemp(prefix="diag_", dir=os.environ.get("FORCE_WORKDIR"))
    try:
        if not row.get("archive_path"):
            raise ValueError("no archive .mat linked to this analysis row")
        binp = str(Path(outdir) / "cloud.bin")
        opts = {k: int(v) for k, v in matlab_opts.items()}
        ppr = row.get("pulses_per_rev")
        if ppr and int(ppr) > 0:
            opts["pulses_per_rev"] = int(ppr)
        inner = row.get("inner_diameter")
        if inner and float(inner) > 0:
            opts["inner_diam"] = float(inner)
        outer = row.get("outer_diameter")
        if outer and float(outer) > 0:
            opts["outer_diam"] = float(outer)
        fchain = row.get("filter_chain")
        if fchain:
            opts["filter_chain"] = str(fchain)
        opts["octree_out"] = binp
        opts["live_cache_points"] = DIAG_CACHE_POINTS
        stmt = (
            f"addpath('{mlq(str(MATLAB_SRC))}'); "
            f"process_force('{mlq(unc_for(row['archive_path']))}','{mlq(outdir)}',{_ml_literal(opts)})"
        )
        p = subprocess.run(
            [exe, "-batch", stmt], capture_output=True, text=True, timeout=timeout
        )
        cache_path = Path(outdir) / "live_cache.bin"
        if p.returncode != 0 or not Path(binp).exists() or not cache_path.exists():
            tail = (p.stderr or p.stdout or "").strip().splitlines()[-5:]
            raise RuntimeError("matlab diag emit failed: " + " | ".join(tail))

        n_pts, x, y, fx, fy, fz = _read_octree_bin(binp)
        if n_pts == 0:
            raise RuntimeError("empty cloud")
        cache = read_d1lc(str(cache_path))
        if cache["n"] != n_pts:
            raise RuntimeError(
                f"cache/cloud length mismatch: {cache['n']} vs {n_pts} — the live cache and "
                "the octree cloud must come from the same decimation to be index-aligned"
            )

        columns, metrics = analyse(
            cache, x, y, samples_per_rev=DIAG_SAMPLES_PER_REV
        )
        n = columns["t"].size
        write_d1an(str(Path(outdir) / "attrs.d1an"), columns)

        revs = np.asarray(cache["revs"], dtype=np.float64)
        _, xa = angular_resample(revs, np.asarray(x, np.float64), DIAG_SAMPLES_PER_REV)
        _, ya = angular_resample(revs, np.asarray(y, np.float64), DIAG_SAMPLES_PER_REV)
        _, fza = angular_resample(revs, np.asarray(fz, np.float64), DIAG_SAMPLES_PER_REV)
        xa, ya, fza = xa[:n], ya[:n], fza[:n]

        las_path = str(Path(outdir) / "diag.las")
        h = laspy.LasHeader(point_format=3)
        h.offsets = [float(xa.min()), float(ya.min()), 0.0]
        h.scales = [0.001, 0.001, 0.001]
        for nm in columns:
            h.add_extra_dim(laspy.ExtraBytesParams(name=nm, type=np.float32))
        las = laspy.LasData(h)
        las.x = xa.astype(np.float64)
        las.y = ya.astype(np.float64)
        las.z = np.zeros(n)
        for nm, arr in columns.items():
            setattr(las, nm, arr)
        lo, hi = float(fza.min()), float(fza.max())
        las.intensity = np.clip(
            (fza - lo) / ((hi - lo) or 1.0) * 65535, 0, 65535
        ).astype(np.uint16)
        las.write(las_path)

        octmp = str(Path(outdir) / "octree")
        pc = subprocess.run(
            [potree_exe, las_path, "-o", octmp],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        if pc.returncode != 0 or not (Path(octmp) / "metadata.json").exists():
            tail = (pc.stderr or pc.stdout or "").strip().splitlines()[-5:]
            raise RuntimeError("PotreeConverter failed: " + " | ".join(tail))

        op = str(row["operation_id"])
        dst = OCTREE_DIR / "diag" / op
        if dst.exists():
            shutil.rmtree(dst, ignore_errors=True)
        dst.mkdir(parents=True, exist_ok=True)
        for fn in ("metadata.json", "hierarchy.bin", "octree.bin"):
            shutil.copy2(Path(octmp) / fn, dst / fn)

        with conn.cursor() as cur:
            cur.execute(
                "UPDATE machining_force_analysis SET diag_status='done', diag_path=%s, "
                "diag_points=%s, diag_version=%s, diag_metrics=%s, diag_error=NULL, "
                "updated_at=now() WHERE id=%s",
                [op, int(n), DIAG_VERSION, json.dumps(metrics), row["id"]],
            )
        conn.commit()
        log.info("[DIAG] %s -> %s (%d pts)", Path(row["archive_path"]).stem, op, n)
        return "done"
    except Exception as e:  # noqa: BLE001
        conn.rollback()
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE machining_force_analysis SET diag_status='error', diag_error=%s, "
                "updated_at=now() WHERE id=%s",
                [str(e)[:2000], row["id"]],
            )
        conn.commit()
        log.error("[DIAG-ERR] %s", e)
        return "error"
    finally:
        shutil.rmtree(outdir, ignore_errors=True)
```

- [ ] **Step 3: Add the queue handler**

```python
def handle_diags(conn, exe: str) -> int:
    """Build diagnostics octrees for any pending requests. Needs PotreeConverter + laspy +
    the diag package; if any is missing, requests are left pending (logged once)."""
    potree_exe = detect_potree_converter()
    if not potree_exe:
        return 0
    try:
        import laspy  # noqa: F401
    except ImportError:
        log.warning("laspy not installed (pip install laspy) — diag requests left pending")
        return 0
    rows = claim_diag(conn, limit=1)
    done = 0
    for row in rows:
        if process_diag_row(conn, row, exe, 3600, load_sampling_opts(conn), potree_exe) == "done":
            done += 1
    return done
```

- [ ] **Step 4: Wire into the queue and daemon loop**

Add a `handle_diags(conn, exe)` call immediately after every `handle_octrees(` call site (in `run_queue` and the daemon loop).

- [ ] **Step 5: Verify the module still imports and lints, smoke test against one real operation**

Run: `python -c "import sys; sys.path.insert(0,'scripts'); import force_orchestrator"`, then `ruff check scripts/force_orchestrator.py scripts/diag`, then set one `diag_status='pending'` row and `python scripts/force_orchestrator.py --run -v`, and confirm `diag_status='done'` with a non-null `diag_points`.

- [ ] **Step 6: Commit**

```bash
git add scripts/force_orchestrator.py
git commit -m "feat(diag): add diagnostics octree handler to the orchestrator"
```

---

## Later Phases (coarse)

These are deliberately not broken into TDD steps yet. Phase 1 must be running against real cuts before their details are worth fixing — in particular, the choice of Getis-Ord neighbourhood size and the HDBSCAN reduction ratio should be set from observed data, not guessed now.

### Phase 2 — Workbench shell

`DiagnosticsWorkbench.vue` in `packages/force-plotting`, exported from `index.ts`, with thin host wrappers mirroring `DirectusForceDashboard.vue` and `StandaloneForceDashboard.vue`. Panels A (signal) and B (spatial). WorkingSet loader with the ≥5M floor and lazy per-attribute fetch. Predicate selections as shader uniforms; `FrmOctree`'s axis uniform generalised to a channel uniform. Selection Inspector. Bandwidth-validity strip driven by `diag_metrics`. Web worker for debounced recompute. `vue-tsc --noEmit` must pass separately from vitest.

### Phase 3 — Spatial statistics

Adds `scripts/diag/spatial.py`: Getis-Ord Gi* with Benjamini-Hochberg FDR, and HDBSCAN via `sklearn.cluster.HDBSCAN` on a grid-reduced set with nearest-neighbour assignment back to the full cloud. Emits `gi_star`, `gi_sig`, `glosh`, `cluster_id` into D1AN; bumps `DIAG_VERSION` to 2 so existing rows requeue. Panel D and the cluster overlay. Requires adding `scikit-learn>=1.3` to the orchestrator host's environment.

### Phase 4 — Event band

Adds `scripts/diag/envelope.py`: band-pass around the dynamometer resonance, Hilbert envelope, envelope spectrum. Emits `env_band`; bumps `DIAG_VERSION` to 3. **Must refuse rather than alias** when the effective Nyquist recorded in `metrics` falls below the configured resonance band, recording the refusal in `diag_metrics`. Panel C carries the order spectrum and the envelope spectrum, the latter labelled non-quantitative.

### Phase 5 — Pass-to-pass differencing

Angular-domain alignment of two cuts and their difference. Cheap once Phase 1 exists, and the highest-information single feature for separating material variation from machine behaviour. Extends the existing multi-pass query pattern in `WearTrend.vue`.

### Phase 6 — Tool-setup record and the local tier

Two spec components with no Phase 1 task, deliberately deferred but tracked here so they are not lost:

**Tool-setup record (spec Component 4).** Task 2 builds `frame_transform` with a `mount_deg` parameter, but nothing yet supplies a real angle — Task 7 leaves it at the `0.0` default, so Phase 1 ships the tool frame as a pass-through. A `tool_setup` record (or fields on the operation) must own the mount geometry **and** the H-matrix FRF, with cuts referencing a setup rather than each carrying a near-duplicate matrix. Until then `Fc/Ff` are XY under another name, and the workbench must not present them as tool-frame quantities.

**Local tier (spec Component 8).** A deliberately thin addition to the standalone app's FastAPI sidecar, run against `.d1raw` before upload: cut-window detect, clipping/validity flags, quick order spectrum, drift check. Its only justification is that the operator is at the machine with the part still in the chuck. **Hard rule: never runs during recording** — the acquisition loop writes 25 kHz × 10 channels with a disk watcher that force-stops runs under pressure, and a dropped sample is unrecoverable in a way a slow analysis never is.

---

## Prerequisites

Before Task 7's smoke test:

- `laspy` and PotreeConverter available on the host (already required by the existing octree handlers — if octrees build today, this is satisfied).
- MATLAB available with `scripts/matlab/process_force.m` on the path (likewise).
- `DATABASE_URL` set, and `dbmate` on PATH for Task 6.

Tasks 1–5 need only NumPy and pytest and can be completed on any machine.

## Note on this document's provenance

Like the design spec it implements, this plan was written and executed during Phase 1
(all seven tasks above were actually built, tested, and committed exactly as described) but
was never itself committed — an oversight only caught while scoping Phase 5. Reconstructed
from the conversation's own record once the gap was found. The self-review fixes already
applied to the original before it was lost are preserved here: the `handle_diags` truthy-
comparison fix (`== "done"`, not just checking the return value), the redundant
`numpy as _np` import removal, and the order-spectrum metrics slice fix (`orders <= 16.0`,
not a no-op index expression).
