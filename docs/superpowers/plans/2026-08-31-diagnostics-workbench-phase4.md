# Diagnostics Workbench Phase 4 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add event-band (envelope) analysis to the diagnostics pipeline — a band-pass-plus-Hilbert-envelope technique that recovers a repetition rate the dynamometer can amplify but not directly measure, gated so it refuses rather than silently aliasing when the data can't actually support it.

**Architecture:** A new pure-function module, `scripts/diag/envelope.py`, implements the band-pass/Hilbert/Welch chain on the full-rate raw signal — not the angular-resampled data the rest of the pipeline uses, since envelope analysis is inherently a time-domain technique. `pipeline.py`'s `analyse()` runs it conditionally on the existing `fn_hz` precondition plus a new Nyquist check, resamples the result onto the same angular grid as every other D1AN column, and records exactly why it did or didn't compute in `metrics["env_band_status"]`.

**Tech Stack:** SciPy (`scipy.signal.butter`, `filtfilt`, `hilbert`, `welch`) — already a project dependency, nothing new to add.

**Spec:** `docs/superpowers/specs/2026-08-30-diagnostics-workbench-design.md` (Component 3's envelope-analysis discussion), continuing `docs/superpowers/plans/2026-08-30-diagnostics-workbench.md`'s "Phase 4 — Event band".

## Global Constraints

- Envelope analysis runs on `sig` — the full-rate, frame-transformed signal `analyse()` already computes before angular resampling — not on `sig_ang`/`resid_z`/any other angular-domain array. Mixing domains here would silently corrupt the frequency content being extracted.
- `env_band` in D1AN must be the SAME length as every other column (`n`, whole revolutions) — resample the envelope back onto `rev_grid` and truncate exactly like `x_ang`/`y_ang` already are.
- Never emit a computed-looking `env_band` without an accompanying `env_band_status` explaining whether it's real. The two travel together, always.
- No live diag octree exists yet (the pre-existing, unrelated MATLAB/archive regression from the Phase 1 session is still unresolved). Every task here is verified with synthetic data.
- The envelope bandwidth fraction (`envelope_bandwidth_frac`) is a provisional default, not a tuned value — same discipline as Phase 3's `gi_k`/`hdbscan_grid_target`.
- Never claim a step passes without running it and reading the output.
- Python target `py312`; ruff `line-length = 88`, `select = ["E","F","I","N","UP","W"]`, `ignore = ["E501"]`.

---

## File Structure

**New:**

| File | Responsibility |
|---|---|
| `scripts/diag/envelope.py` | Band-pass + Hilbert envelope; envelope amplitude spectrum |
| `tests/scripts/diag/test_envelope.py` | Unit tests for the above |

**Modified:**

| File | Change |
|---|---|
| `scripts/diag/pipeline.py` | `analyse()` gains the `env_band` column, `envelope_bandwidth_frac` kwarg, and `env_band_status`/`envelope_spectrum` metrics fields |
| `scripts/force_orchestrator.py` | `DIAG_VERSION` → 3 |
| `tests/scripts/diag/test_pipeline.py` | new tests covering all three `env_band_status` outcomes |

**Explicitly out of scope:** Panel C UI (order spectrum + envelope spectrum display) — no real data exists to render against yet, same reasoning as Phase 3's Panel D deferral.

---

### Task 1: Band-pass envelope and envelope spectrum

**Files:**
- Create: `scripts/diag/envelope.py`
- Test: `tests/scripts/diag/test_envelope.py`

**Interfaces:**
- Consumes: nothing
- Produces:
  - `bandpass_envelope(sig: np.ndarray, fs: float, f_center: float, bandwidth_frac: float = 0.2) -> np.ndarray`
  - `envelope_spectrum(envelope: np.ndarray, fs: float, max_freq: float | None = None) -> tuple[np.ndarray, np.ndarray]` returning `(freqs, amplitude)`

- [ ] **Step 1: Write the failing test**

```python
# tests/scripts/diag/test_envelope.py
import os
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", "scripts"))

from diag.envelope import bandpass_envelope, envelope_spectrum


def _am_signal(fs, duration, carrier, mod_rate, mod_depth=0.8, noise=0.05, seed=0):
    """A carrier amplitude-modulated at mod_rate -- the synthetic stand-in for a structural
    resonance being excited at some repetition rate the dynamometer can't directly resolve."""
    t = np.arange(0, duration, 1.0 / fs)
    rng = np.random.default_rng(seed)
    sig = (1.0 + mod_depth * np.sin(2 * np.pi * mod_rate * t)) * np.sin(
        2 * np.pi * carrier * t
    )
    sig = sig + noise * rng.normal(size=t.size)
    return sig


def test_bandpass_envelope_recovers_the_modulation_rate():
    # THE ground-truth test: a carrier the dyno resonance stands in for, modulated at a rate
    # that itself is far above what could be measured directly, must come back from the
    # envelope's own spectrum -- this is the whole point of the technique.
    fs = 25_000.0
    sig = _am_signal(fs, duration=2.0, carrier=2000.0, mod_rate=50.0)
    envelope = bandpass_envelope(sig, fs, f_center=2000.0, bandwidth_frac=0.2)
    freqs, amp = envelope_spectrum(envelope, fs, max_freq=500.0)
    peak_freq = freqs[np.argmax(amp)]
    assert abs(peak_freq - 50.0) < 10.0


def test_bandpass_envelope_output_is_non_negative_and_same_length():
    fs = 25_000.0
    sig = _am_signal(fs, duration=1.0, carrier=2000.0, mod_rate=50.0)
    envelope = bandpass_envelope(sig, fs, f_center=2000.0)
    assert envelope.shape == sig.shape
    assert np.all(envelope >= 0.0)


def test_bandpass_envelope_rejects_a_band_that_does_not_fit_below_nyquist():
    fs = 1000.0  # Nyquist = 500 Hz
    sig = np.zeros(2000)
    with pytest.raises(ValueError, match="Nyquist"):
        bandpass_envelope(sig, fs, f_center=2000.0, bandwidth_frac=0.2)


def test_bandpass_envelope_rejects_a_center_frequency_at_or_below_zero():
    fs = 25_000.0
    sig = np.zeros(2000)
    with pytest.raises(ValueError, match="f_center"):
        bandpass_envelope(sig, fs, f_center=0.0)


def test_envelope_spectrum_max_freq_caps_the_returned_range():
    fs = 25_000.0
    sig = _am_signal(fs, duration=1.0, carrier=2000.0, mod_rate=50.0)
    envelope = bandpass_envelope(sig, fs, f_center=2000.0)
    freqs, amp = envelope_spectrum(envelope, fs, max_freq=100.0)
    assert freqs.max() <= 100.0
    assert amp.shape == freqs.shape
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd C:\Users\WS-X180-PC\Documents\GitHub\D1-Database\.claude\worktrees\diagnostics-workbench && python -m pytest tests/scripts/diag/test_envelope.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'diag.envelope'`

- [ ] **Step 3: Write the implementation**

```python
# scripts/diag/envelope.py
"""Event-band (envelope) analysis: recover a repetition rate the dynamometer's own
structural resonance is amplifying but cannot itself directly measure.

Above roughly fn/5 (the dynamometer's valid quantitative bandwidth -- see the design spec and
frame_transform's module docstring), the sensor stops measuring cutting force honestly and
starts ringing at its own resonance instead. That ringing is still useful: if something in
the process (chip segmentation, an impact) is exciting that resonance at some rate, the
resonance's AMPLITUDE is modulated at that rate even though its own frequency is far above
what the sensor can resolve. Band-pass around the resonance, take the Hilbert envelope, and
the envelope's own spectrum recovers the modulation rate -- the standard AM-demodulation
trick, also how bearing-fault diagnostics recovers a fault's repetition rate from a carrier
frequency the sensor can measure even when the fault rate itself is out of direct reach.

Deliberately time-domain: this operates on the FULL-RATE raw signal, not the angular-resampled
data the rest of this package's pipeline works in. The frequency content this recovers lives
in Hz (a real, physical rate), which the angular domain's orders-per-revolution deliberately
discards.
"""

from __future__ import annotations

import numpy as np
from scipy.signal import butter, filtfilt, hilbert, welch


def bandpass_envelope(
    sig: np.ndarray, fs: float, f_center: float, bandwidth_frac: float = 0.2
) -> np.ndarray:
    """Band-pass `sig` around `f_center` (width `bandwidth_frac` of `f_center`, split evenly
    above and below) and return the Hilbert envelope -- same length as `sig`, non-negative.

    Raises ValueError if `f_center` is not strictly positive, or if the requested band does
    not fit strictly inside (0, Nyquist): asking for a band that touches or exceeds Nyquist
    would alias rather than isolate the resonance, which is worse than refusing outright.
    """
    sig = np.asarray(sig, dtype=np.float64)
    if f_center <= 0:
        raise ValueError(f"f_center must be > 0, got {f_center}")
    nyquist = fs / 2.0
    lo = f_center * (1.0 - bandwidth_frac / 2.0)
    hi = f_center * (1.0 + bandwidth_frac / 2.0)
    if lo <= 0.0 or hi >= nyquist:
        raise ValueError(
            f"requested band [{lo:.1f}, {hi:.1f}] Hz does not fit strictly inside "
            f"(0, Nyquist={nyquist:.1f}) Hz at fs={fs:.1f} Hz"
        )
    b, a = butter(4, [lo / nyquist, hi / nyquist], btype="band")
    filtered = filtfilt(b, a, sig)
    return np.abs(hilbert(filtered))


def envelope_spectrum(
    envelope: np.ndarray, fs: float, max_freq: float | None = None
) -> tuple[np.ndarray, np.ndarray]:
    """Amplitude spectrum of the envelope itself (Welch), optionally capped at `max_freq` --
    the modulation-rate content lives at low frequencies relative to the carrier, so most
    callers cap this well below fs/2."""
    envelope = np.asarray(envelope, dtype=np.float64)
    nperseg = min(4096, envelope.size)
    freqs, power = welch(envelope - envelope.mean(), fs=fs, nperseg=nperseg)
    amplitude = np.sqrt(power)
    if max_freq is not None:
        keep = freqs <= max_freq
        freqs, amplitude = freqs[keep], amplitude[keep]
    return freqs, amplitude
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/scripts/diag/test_envelope.py -v`
Expected: 5 passed

- [ ] **Step 5: Lint and commit**

```bash
python -m ruff check scripts/diag tests/scripts/diag
git add scripts/diag/envelope.py tests/scripts/diag/test_envelope.py
git commit -m "feat(diag): add band-pass envelope and envelope spectrum"
```

---

### Task 2: Wire event-band analysis into `analyse()`

**Files:**
- Modify: `scripts/diag/pipeline.py`
- Modify: `tests/scripts/diag/test_pipeline.py`

**Interfaces:**
- Consumes: `bandpass_envelope`, `envelope_spectrum` (Task 1)
- Produces: `analyse()`'s `columns` gains `env_band` (float32); `metrics` gains `env_band_status` (str) and, only when computed, `envelope_spectrum` (dict); new kwarg `envelope_bandwidth_frac: float = 0.2`

**The three `env_band_status` outcomes**, in the order `analyse()` checks them:
1. `"refused: dyno_fn_hz not provided"` — no resonance frequency was given (same precondition `quantitative_limit_hz` already requires: no tool-setup record exists yet).
2. `"refused: effective_nyquist_hz (X) below required Y Hz"` — a resonance frequency was given, but this cut's effective sample rate can't support the band around it.
3. `"computed"` — both checks passed; `env_band` holds real values and `metrics["envelope_spectrum"]` is populated.

`env_band` is all zeros in both refused cases, and is never populated without `env_band_status` explaining why — the two fields always travel together.

- [ ] **Step 1: Write the failing tests**

Add to `tests/scripts/diag/test_pipeline.py`:

```python
def test_env_band_refused_when_fn_hz_not_provided():
    t, fx, fy, fz, rpm, revs, x, y, fs, _ = _synthetic_cut(n_rev=8)
    cache = {
        "n": t.size,
        "fs": fs,
        "feed": 0.05,
        "diam": 80.0,
        "cs_sec": 0.0,
        "ce_sec": float(t[-1]),
        "t": t,
        "fx": fx,
        "fy": fy,
        "fz": fz,
        "rpm": rpm,
        "revs": revs,
    }
    cols, metrics = analyse(cache, x, y, samples_per_rev=SPR)
    assert metrics["env_band_status"] == "refused: dyno_fn_hz not provided"
    assert "envelope_spectrum" not in metrics
    assert np.all(cols["env_band"] == 0.0)


def test_env_band_refused_when_nyquist_too_low_for_the_band():
    t, fx, fy, fz, rpm, revs, x, y, fs, _ = _synthetic_cut(n_rev=8)
    cache = {
        "n": t.size,
        "fs": fs,
        "feed": 0.05,
        "diam": 80.0,
        "cs_sec": 0.0,
        "ce_sec": float(t[-1]),
        "t": t,
        "fx": fx,
        "fy": fy,
        "fz": fz,
        "rpm": rpm,
        "revs": revs,
    }
    # fs is 25000 Hz (Nyquist 12500 Hz) in _synthetic_cut; a resonance far above that cannot
    # be band-passed no matter the bandwidth fraction.
    cols, metrics = analyse(cache, x, y, samples_per_rev=SPR, fn_hz=20_000.0)
    assert metrics["env_band_status"].startswith("refused: effective_nyquist_hz")
    assert "envelope_spectrum" not in metrics
    assert np.all(cols["env_band"] == 0.0)


def test_env_band_computed_when_fn_hz_fits_within_nyquist():
    t, fx, fy, fz, rpm, revs, x, y, fs, _ = _synthetic_cut(n_rev=8)
    cache = {
        "n": t.size,
        "fs": fs,
        "feed": 0.05,
        "diam": 80.0,
        "cs_sec": 0.0,
        "ce_sec": float(t[-1]),
        "t": t,
        "fx": fx,
        "fy": fy,
        "fz": fz,
        "rpm": rpm,
        "revs": revs,
    }
    # fs=25000 Hz -> Nyquist 12500 Hz; 2300 Hz with a 20% band comfortably fits.
    cols, metrics = analyse(cache, x, y, samples_per_rev=SPR, fn_hz=2300.0)
    assert metrics["env_band_status"] == "computed"
    assert "envelope_spectrum" in metrics
    assert len(metrics["envelope_spectrum"]["freqs"]) > 0
    assert len(metrics["envelope_spectrum"]["freqs"]) == len(
        metrics["envelope_spectrum"]["amplitude"]
    )
    assert cols["env_band"].shape == cols["resid_z"].shape
    assert np.all(np.isfinite(cols["env_band"]))
    assert np.all(cols["env_band"] >= 0.0)
```

Also extend `test_pipeline_columns_include_spatial_coordinates`'s column-set assertion (it already enumerates every expected key generically):

```python
    assert set(cols) == {
        "t",
        "rev",
        "x",
        "y",
        "tsa_resid",
        "resid_z",
        "gi_star",
        "gi_sig",
        "cluster_id",
        "glosh",
        "env_band",
    }
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/scripts/diag/test_pipeline.py -v`
Expected: FAIL — `KeyError: 'env_band_status'` (or the column-set mismatch)

- [ ] **Step 3: Wire event-band analysis into `analyse()`**

In `scripts/diag/pipeline.py`, add the import:

```python
from .envelope import bandpass_envelope, envelope_spectrum
```

Update the signature (add after the Phase 3 kwargs):

```python
def analyse(
    cache: dict,
    x: np.ndarray,
    y: np.ndarray,
    *,
    mount_deg: float = 0.0,
    samples_per_rev: int = DEFAULT_SAMPLES_PER_REV,
    fn_hz: float | None = None,
    channel: str = "fp",
    gi_k: int = 30,
    hdbscan_grid_target: int = 20_000,
    hdbscan_min_cluster_size: int = 10,
    envelope_bandwidth_frac: float = 0.2,
) -> tuple[dict[str, np.ndarray], dict]:
```

After the existing `if fn_hz is not None and fn_hz > 0:` block that sets `dyno_fn_hz`/`quantitative_limit_hz` in `metrics`, and BEFORE the `columns = {...}` dict is built, insert:

```python
    # Event-band (envelope) analysis runs on `sig` -- the full-rate signal, NOT sig_ang/
    # resid_z/anything angular-domain. It needs the same precondition quantitative_limit_hz
    # already requires (a real dyno_fn_hz), plus a Nyquist check specific to whether the
    # requested band actually fits: silently aliasing a band that doesn't fit is worse than
    # refusing, so refusal is recorded, never guessed past.
    env_band = np.zeros(n)
    if fn_hz is None or fn_hz <= 0:
        env_band_status = "refused: dyno_fn_hz not provided"
    else:
        half_bw = fn_hz * (envelope_bandwidth_frac / 2.0)
        hi_needed = fn_hz + half_bw
        nyquist = eff_fs / 2.0
        if nyquist < hi_needed:
            env_band_status = (
                f"refused: effective_nyquist_hz ({nyquist:.1f}) below required "
                f"{hi_needed:.1f} Hz for the resonance band"
            )
        else:
            envelope = bandpass_envelope(
                sig, eff_fs, f_center=fn_hz, bandwidth_frac=envelope_bandwidth_frac
            )
            _, env_ang = angular_resample(revs, envelope, samples_per_rev)
            env_band = env_ang[:n]
            env_band_status = "computed"
            env_f, env_amp = envelope_spectrum(envelope, eff_fs, max_freq=nyquist)
    metrics["env_band_status"] = env_band_status
    if env_band_status == "computed":
        metrics["envelope_spectrum"] = {
            "freqs": [float(v) for v in env_f],
            "amplitude": [float(v) for v in env_amp],
        }
```

`eff_fs` is already computed earlier in the function (the `span_sec`/`eff_fs` lines feeding the base `metrics` dict, well before the `if fn_hz is not None...` block this new block follows) -- no need to move or recompute anything, this block simply reuses it.

Update `columns`:

```python
    columns = {
        "t": t_ang.astype(np.float32),
        "rev": rev_grid.astype(np.float32),
        "x": x_ang.astype(np.float32),
        "y": y_ang.astype(np.float32),
        "tsa_resid": residual.astype(np.float32),
        "resid_z": resid_z.astype(np.float32),
        "gi_star": gi_star.astype(np.float32),
        "gi_sig": gi_sig.astype(np.float32),
        "cluster_id": cluster_id.astype(np.float32),
        "glosh": glosh.astype(np.float32),
        "env_band": env_band.astype(np.float32),
    }
    return columns, metrics
```

Update the module docstring's column list one more time:

```python
"""One analysis pass: D1LC cache + spiral coordinates -> D1AN columns + metrics.

Phase 1-4 scope. Emits t, rev, x, y, tsa_resid, resid_z, gi_star, gi_sig, cluster_id, glosh
and env_band -- the full column set the design spec's D1AN contract calls for.
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/scripts/diag/ -v`
Expected: all pass. If `eff_fs` ends up referenced before it's computed (a `NameError` or `UnboundLocalError`), that means the move in Step 3 wasn't applied correctly — the event-band block must come strictly after the `span_sec`/`eff_fs` lines in the function body, not before.

- [ ] **Step 5: Lint and commit**

```bash
python -m ruff check scripts/diag tests/scripts/diag
git add scripts/diag/pipeline.py tests/scripts/diag/test_pipeline.py
git commit -m "feat(diag): wire event-band envelope analysis into the pipeline"
```

---

### Task 3: Bump `DIAG_VERSION`

**Files:**
- Modify: `scripts/force_orchestrator.py`

**Interfaces:**
- Consumes: nothing new
- Produces: `DIAG_VERSION = 3`

Phase 3's `claim_diag` already requeues any `done` row whose `diag_version` is older than the current constant — no further orchestrator change is needed here, only the bump itself.

- [ ] **Step 1: Bump the constant**

Find:

```python
DIAG_CACHE_POINTS = 5_000_000
# Bump whenever analyse()'s column set or its parameters change in a way that makes an
# already-'done' row's diag_metrics/D1AN stale. claim_diag requeues 'done' rows with an
# older diag_version automatically -- see claim_diag's WHERE clause below.
DIAG_VERSION = 2
DIAG_SAMPLES_PER_REV = 256
```

Change to:

```python
DIAG_CACHE_POINTS = 5_000_000
# Bump whenever analyse()'s column set or its parameters change in a way that makes an
# already-'done' row's diag_metrics/D1AN stale. claim_diag requeues 'done' rows with an
# older diag_version automatically -- see claim_diag's WHERE clause below.
DIAG_VERSION = 3
DIAG_SAMPLES_PER_REV = 256
```

- [ ] **Step 2: Verify the module still imports and lints**

Run: `python -c "import sys; sys.path.insert(0,'scripts'); import force_orchestrator; print('DIAG_VERSION =', force_orchestrator.DIAG_VERSION)"`
Expected: `DIAG_VERSION = 3`, no other output, exit 0

Run: `python -m ruff check scripts/force_orchestrator.py`
Expected: no findings

- [ ] **Step 3: Run the full test suite one more time**

Run: `python -m pytest tests/scripts/ -v`
Expected: all pass

- [ ] **Step 4: Commit**

```bash
git add scripts/force_orchestrator.py
git commit -m "feat(diag): bump DIAG_VERSION to 3 for event-band analysis"
```

---

## Self-Review Notes

**Spec coverage:** The design spec's envelope-analysis discussion ("band-pass around the structural resonance, take the Hilbert envelope, and the spectrum of that envelope reveals the repetition rate") is implemented directly in Task 1. The master plan's explicit requirement — "must refuse rather than alias when the effective Nyquist falls below the configured resonance band, recording the refusal" — is Task 2's three-way `env_band_status`, not a single silent zero-fill.

**Known gap carried forward, not silently dropped:** Panel C UI has no task here, same reasoning as every prior phase's UI deferral — no real diag octree exists yet to render against, so building UI now would mean re-verifying it later anyway against real data.

**Type consistency check:** `env_band_status` values (`"computed"`, `"refused: dyno_fn_hz not provided"`, `"refused: effective_nyquist_hz (...) below required ... Hz..."`) are exact strings Task 2's tests match against (`==` for the first two, `.startswith(...)` for the Nyquist one, since it embeds a formatted number). `bandpass_envelope`'s and `envelope_spectrum`'s signatures in Task 2's usage match Task 1's exactly: positional `(sig, fs, f_center, bandwidth_frac=...)` and `(envelope, fs, max_freq=...)`, no renamed parameters at the call site to drift out of sync with.
