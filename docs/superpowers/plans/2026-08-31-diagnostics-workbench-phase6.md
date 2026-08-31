# Diagnostics Workbench Phase 6 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the two components the master plan deliberately deferred: (A) a real `tool_setup` record so `frame_transform`'s `mount_deg` and an optional H-matrix FRF correction stop being a `0.0`/identity pass-through, and (B) the standalone app's local tier — a quick order spectrum and a drift-detection flag computed at `finalize()` time, never during recording.

**Architecture:** Two independent parts, landing in different halves of the repo, sharing nothing but the phase number:

- **Part A (server-side, `scripts/`)** — a new `tool_setup` table that cuts reference by FK (not a near-duplicate FRF file per cut), `pipeline.analyse()` gains an optional `h_matrix` correction step applied before `frame_transform`, and `process_diag_row` looks the setup up via `claim_diag`'s existing subselect pattern (matching how `archive_path` is already resolved). A setup-less cut behaves exactly as it does today (`mount_deg=0.0`, no H correction) — this is additive, not a behavior change for existing rows.
- **Part B (standalone app, `apps/force-app/backend/`)** — `finalize.py` already computes most of Component 8's local tier (cut-window detect, per-channel clipping flags) as a side effect of building `capture.mat`/`live_cache.bin`. The two genuinely missing pieces — a quick order spectrum and a drift-detection flag distinct from the existing `drift_comp` *correction* toggle — are added to `dsp.py` and wired into `finalize()`'s existing summary-building step. `finalize()` only ever runs after `self.raw.close()` (verified in `session.py`), so the hard "never during recording" rule is structural, not something this phase has to newly enforce.

**Tech Stack:** Python (psycopg2, NumPy, SciPy), SQL (dbmate migration) — no new dependencies.

**Spec:** `docs/superpowers/specs/2026-08-30-diagnostics-workbench-design.md` (Component 4 — frame transform, Component 8 — local tier), continuing `docs/superpowers/plans/2026-08-30-diagnostics-workbench.md`'s "Phase 6 — Tool-setup record and the local tier".

## Global Constraints

- Zero behavior change for any cut with no linked `tool_setup`: `mount_deg` stays `0.0`, no H-matrix correction — matching every prior phase's output exactly.
- `DIAG_VERSION` must bump (3 → 4): `analyse()`'s metrics gain a new `h_matrix_applied` key and `mount_deg` can now be genuinely non-zero for linked cuts, both of which make an already-`done` row's `diag_metrics`/D1AN stale under the existing convention documented at `scripts/force_orchestrator.py`'s `DIAG_VERSION` constant.
- The H matrix is *applied*, not estimated — measuring one is an out-of-scope bench procedure per the spec's non-goals. The worker only ever multiplies a supplied matrix through.
- `dsp.py`'s new functions are an independent, standalone-app-local implementation, not an import of `scripts/diag/`— this repo already has D1LC readers duplicated three times across deployment boundaries (documented as intentional, byte-identical-by-convention copies) precisely because the standalone app's backend and the `d1-server` orchestrator are separate deployments with separate Python environments.
- Never claim a step passes without running it and reading the output.

---

## File Structure

**New:**

| File | Responsibility |
|---|---|
| `db/migrations/20260831000105_tool_setup.sql` | `tool_setup` table (mount geometry + H matrix) + `machining_force_analysis.tool_setup_id` FK |

**Modified:**

| File | Change |
|---|---|
| `scripts/diag/pipeline.py` | `analyse()` gains `h_matrix: np.ndarray \| None = None`, applied to (fx,fy,fz) before `frame_transform` |
| `scripts/force_orchestrator.py` | `claim_diag` resolves the linked setup's `mount_deg`/`h_matrix`; `process_diag_row` passes them through; `DIAG_VERSION` 3 → 4 |
| `tests/scripts/diag/test_pipeline.py` | Ground-truth test that an H-matrix correction changes which channel carries a known signal |
| `apps/force-app/backend/app/dsp.py` | `order_spectrum_quick()`, `drift_check()` |
| `apps/force-app/backend/app/finalize.py` | Call both, write `summary["local_diag"]` |
| `apps/force-app/backend/tests/test_pipeline.py` | Assert `local_diag.order_spectrum_status == "computed"` in the existing end-to-end test |
| `apps/force-app/backend/tests/test_drift_cut.py` | Drift-check-detects / drift-check-clean tests, alongside the existing `drift_comp` tests |

---

## Task 1: `tool_setup` record + H-matrix correction in the pipeline

**Files:**
- Create: `db/migrations/20260831000105_tool_setup.sql`
- Modify: `scripts/diag/pipeline.py`
- Test: `tests/scripts/diag/test_pipeline.py`

**Interfaces:**
- Produces: `analyse(cache, x, y, *, mount_deg=0.0, h_matrix: np.ndarray | None = None, samples_per_rev=256, fn_hz=None, channel="fp", gi_k=30, hdbscan_grid_target=20_000, hdbscan_min_cluster_size=10, envelope_bandwidth_frac=0.2) -> (columns, metrics)`. New behavior only: `metrics["h_matrix_applied"]: bool`.

- [ ] **Step 1: Write the migration**

```sql
-- migrate:up
-- Diagnostics Workbench Phase 6: mount geometry + H-matrix FRF correction, owned by a setup
-- record rather than duplicated per cut. Component 4 (frame transform) needs a real mount_deg
-- to turn Fc/Ff from "XY under another name" into an actual tool-frame decomposition; the FRF
-- is setup-dependent (workpiece mass, fixturing), so binding it to the cut instead would
-- produce many near-identical files with no way to tell which one was valid for a given cut.
CREATE TABLE tool_setup (
    setup_id    UUID        NOT NULL DEFAULT uuid_generate_v4(),
    setup_code  VARCHAR(64) NOT NULL,
    mount_deg   NUMERIC     NOT NULL DEFAULT 0,  -- static dyno->tool mounting angle (turning)
    h_matrix    JSONB,                            -- optional 3x3 FRF correction, applied not estimated
    notes       TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    version     INTEGER     NOT NULL DEFAULT 1,
    CONSTRAINT tool_setup_pkey PRIMARY KEY (setup_id),
    CONSTRAINT tool_setup_code_unique UNIQUE (setup_code)
);

COMMENT ON TABLE tool_setup IS
    'Mount geometry + H-matrix FRF correction for a dynamometer setup. Cuts reference a setup by FK (machining_force_analysis.tool_setup_id) rather than each carrying a near-duplicate FRF file.';
COMMENT ON COLUMN tool_setup.h_matrix IS
    'Optional 3x3 correction matrix (row-major JSON array of arrays), applied to (Fx,Fy,Fz) before frame_transform. NULL = no correction (identity). Measuring an FRF is a bench procedure, out of scope for this app -- the worker only applies a supplied matrix.';

ALTER TABLE machining_force_analysis
    ADD COLUMN IF NOT EXISTS tool_setup_id UUID REFERENCES tool_setup(setup_id) ON DELETE SET NULL;

COMMENT ON COLUMN machining_force_analysis.tool_setup_id IS
    'Optional link to the tool_setup that supplies this cut''s mount_deg and h_matrix for the diagnostics pipeline. NULL means the pipeline uses the mount_deg=0.0/no-correction defaults, unchanged from Phases 1-5.';

-- migrate:down
ALTER TABLE machining_force_analysis DROP COLUMN IF EXISTS tool_setup_id;
DROP TABLE IF EXISTS tool_setup;
```

- [ ] **Step 2: Write the failing test**

```python
# tests/scripts/diag/test_pipeline.py -- append

def test_h_matrix_correction_moves_signal_between_channels():
    """A synthetic case where the ONLY way the anomaly-bearing signal ends up on Ff is
    through the H-matrix correction: fx carries the signature, fy is flat. An h_matrix that
    swaps x<->y must move that signature onto ff; without it (h_matrix=None), ff stays flat.
    This is the ground-truth test for Task 1 -- it fails if h_matrix is silently ignored.
    """
    n_rev, spr = 30, SPR
    n = n_rev * spr
    revs = np.arange(n, dtype=np.float64) / spr
    fs = 25_000.0
    t = revs * 60.0 / 1200.0
    phase = 2 * np.pi * revs
    signature = 50.0 + 5.0 * np.sin(phase) + 2.0 * np.sin(3 * phase)
    fx = signature
    fy = np.zeros(n)
    fz = np.full(n, 10.0)  # placeholder, channel under test is 'ff'
    rpm = np.full(n, 1200.0)
    rho = 40.0 - 0.05 * revs / (2 * np.pi)
    theta = 2 * np.pi * revs
    x = rho * np.cos(theta)
    y = rho * np.sin(theta)

    cache = dict(n=n, fs=fs, feed=0.05, diam=80.0, cs_sec=0.0, ce_sec=float(t[-1]),
                 t=t, fx=fx, fy=fy, fz=fz, rpm=rpm, revs=revs)

    # No correction: ff = fy = 0 throughout -- no signature to find.
    _, metrics_plain = analyse(cache, x, y, channel="ff", samples_per_rev=spr)
    assert metrics_plain["h_matrix_applied"] is False
    assert max(abs(v) for v in metrics_plain["tsa_signature"]) < 1e-6

    # h_matrix swaps x and y: corrected fx' = fy = 0, fy' = fx = signature.
    # With mount_deg=0 (identity rotation), ff = fy' = signature.
    swap = np.array([[0.0, 1.0, 0.0], [1.0, 0.0, 0.0], [0.0, 0.0, 1.0]])
    columns, metrics = analyse(cache, x, y, channel="ff", h_matrix=swap, samples_per_rev=spr)
    assert metrics["h_matrix_applied"] is True
    assert max(abs(v) for v in metrics["tsa_signature"]) > 3.0  # the signature is now on ff
```

- [ ] **Step 3: Run test to verify it fails**

Run: `cd tests/scripts/diag && python -m pytest test_pipeline.py::test_h_matrix_correction_moves_signal_between_channels -v`
Expected: FAIL with `TypeError: analyse() got an unexpected keyword argument 'h_matrix'`

- [ ] **Step 4: Implement `h_matrix` in `analyse()`**

In `scripts/diag/pipeline.py`, change the signature and add the correction step immediately before the existing `frame = dict(...)` line:

```python
def analyse(
    cache: dict,
    x: np.ndarray,
    y: np.ndarray,
    *,
    mount_deg: float = 0.0,
    h_matrix: np.ndarray | None = None,
    samples_per_rev: int = DEFAULT_SAMPLES_PER_REV,
    fn_hz: float | None = None,
    channel: str = "fp",
    gi_k: int = 30,
    hdbscan_grid_target: int = 20_000,
    hdbscan_min_cluster_size: int = 10,
    envelope_bandwidth_frac: float = 0.2,
) -> tuple[dict[str, np.ndarray], dict]:
```

Docstring addition: `` `h_matrix` is an optional 3x3 FRF correction applied to (Fx,Fy,Fz) before the frame transform -- the worker applies a supplied matrix, it does not estimate one (see Component 4/8 non-goals in the design spec). ``

```python
    fx_raw = np.asarray(cache["fx"], dtype=np.float64)
    fy_raw = np.asarray(cache["fy"], dtype=np.float64)
    fz_raw = np.asarray(cache["fz"], dtype=np.float64)
    h_applied = h_matrix is not None
    if h_applied:
        h = np.asarray(h_matrix, dtype=np.float64)
        if h.shape != (3, 3):
            raise ValueError(f"h_matrix must be 3x3, got shape {h.shape}")
        corrected = h @ np.vstack([fx_raw, fy_raw, fz_raw])
        fx_raw, fy_raw, fz_raw = corrected[0], corrected[1], corrected[2]
    frame = dict(zip(_CHANNELS, frame_transform(fx_raw, fy_raw, fz_raw, mount_deg)))
    sig = frame[channel]
```

Remove the old `frame = dict(...)` line this replaces. Add to the `metrics` dict (near the existing `"mount_deg": float(mount_deg),` line):

```python
        "h_matrix_applied": h_applied,
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd tests/scripts/diag && python -m pytest test_pipeline.py -v`
Expected: PASS, all tests in the file including the new one and every pre-existing test unchanged.

- [ ] **Step 6: Wire the setup lookup into the orchestrator**

In `scripts/force_orchestrator.py`, bump the version comment target and constant:

```python
DIAG_VERSION = 4
```

In `claim_diag`'s `RETURNING` clause, add two subselects alongside the existing `archive_path` one (same pattern — resolve via a subselect rather than a JOIN, since a row's setup is optional and a JOIN would need to be a LEFT JOIN with column collisions to avoid):

```python
         RETURNING a.id, a.operation_id, a.pulses_per_rev, a.inner_diameter, a.outer_diameter, a.filter_chain::text AS filter_chain,
                   (SELECT metadata->>'archive_path' FROM directus_files WHERE id = a.directus_files_id) AS archive_path,
                   (SELECT mount_deg FROM tool_setup WHERE setup_id = a.tool_setup_id) AS setup_mount_deg,
                   (SELECT h_matrix FROM tool_setup WHERE setup_id = a.tool_setup_id) AS setup_h_matrix
```

In `process_diag_row`, immediately before the `columns, metrics = analyse(...)` line, resolve the two optional fields and pass them through:

```python
        mount_deg = float(row["setup_mount_deg"]) if row.get("setup_mount_deg") is not None else 0.0
        h_matrix_raw = row.get("setup_h_matrix")
        h_matrix = np.array(h_matrix_raw, dtype=np.float64) if h_matrix_raw is not None else None

        columns, metrics = analyse(
            cache, x, y, mount_deg=mount_deg, h_matrix=h_matrix, samples_per_rev=DIAG_SAMPLES_PER_REV
        )
```

(Replaces the existing `columns, metrics = analyse(cache, x, y, samples_per_rev=DIAG_SAMPLES_PER_REV)` line.)

- [ ] **Step 7: Sanity-check the orchestrator change with ruff (no live DB needed for this step)**

Run: `python -m ruff check scripts/force_orchestrator.py scripts/diag/pipeline.py`
Expected: no new findings.

- [ ] **Step 8: Commit**

```bash
git add db/migrations/20260831000105_tool_setup.sql scripts/diag/pipeline.py scripts/force_orchestrator.py tests/scripts/diag/test_pipeline.py
git commit -m "feat(diag): tool_setup record + H-matrix FRF correction in the pipeline"
```

---

## Task 2: Local tier — quick order spectrum + drift check

**Files:**
- Modify: `apps/force-app/backend/app/dsp.py`
- Modify: `apps/force-app/backend/app/finalize.py`
- Test: `apps/force-app/backend/tests/test_drift_cut.py`
- Test: `apps/force-app/backend/tests/test_pipeline.py`

**Interfaces:**
- Consumes: nothing new from Task 1 (Part B is independent of Part A).
- Produces: `dsp.order_spectrum_quick(revs: np.ndarray, sig: np.ndarray, samples_per_rev: int = 64) -> tuple[list[float], list[float]]` (orders, amplitude — orders ≤ 16 only, mirroring `scripts/diag/pipeline.py`'s own metrics-payload cap). `dsp.drift_check(t: np.ndarray, axes: dict[str, np.ndarray], thresh_frac: float = 0.1) -> dict` — per-axis `{"slope_n_per_sec": float, "excursion_frac": float, "detected": bool}` for `"Fx"`, `"Fy"`, `"Fz"`, plus a top-level `"detected": bool` (`any` of the three).

- [ ] **Step 1: Write the failing tests for `drift_check`**

```python
# apps/force-app/backend/tests/test_drift_cut.py -- append

from app.dsp import drift_check, order_spectrum_quick


def test_drift_check_flags_a_strong_linear_trend():
    fs, n = 4000, 8000
    t = np.arange(n) / fs
    axes = {
        "Fx": np.full(n, 40.0),
        "Fy": np.full(n, 60.0),
        "Fz": 5.0 + 40.0 * t,  # same strong drift as test_drift_comp_removes_linear_trend
    }
    result = drift_check(t, axes)
    assert result["Fz"]["detected"] is True
    assert result["detected"] is True
    assert result["Fx"]["detected"] is False


def test_drift_check_clean_signal_not_flagged():
    fs, n = 4000, 8000
    t = np.arange(n) / fs
    rng = np.random.default_rng(3)
    axes = {
        "Fx": 40.0 + rng.normal(scale=1.0, size=n),
        "Fy": 60.0 + rng.normal(scale=1.0, size=n),
        "Fz": 120.0 + rng.normal(scale=1.0, size=n),
    }
    result = drift_check(t, axes)
    assert result["detected"] is False


def test_order_spectrum_quick_recovers_known_order():
    # 5 revolutions/sec worth of angle, a force with a clean 3rd-order component.
    spr = 64
    n_rev = 40
    revs = np.arange(n_rev * spr, dtype=np.float64) / spr
    sig = 100.0 + 8.0 * np.sin(2 * np.pi * 3.0 * revs)  # order 3
    orders, amp = order_spectrum_quick(revs, sig, samples_per_rev=spr)
    orders = np.asarray(orders)
    amp = np.asarray(amp)
    mask = orders > 0.5  # drop DC
    orders_f, amp_f = orders[mask], amp[mask]
    peak_order = orders_f[np.argmax(amp_f)]
    assert abs(peak_order - 3.0) < 0.2
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd apps/force-app/backend && python -m pytest tests/test_drift_cut.py -v -k "drift_check or order_spectrum_quick"`
Expected: FAIL with `ImportError: cannot import name 'drift_check'`

- [ ] **Step 3: Implement in `dsp.py`**

Append to `apps/force-app/backend/app/dsp.py`:

```python
def order_spectrum_quick(
    revs: np.ndarray, sig: np.ndarray, samples_per_rev: int = 64, max_order: float = 16.0
) -> tuple[list[float], list[float]]:
    """A deliberately cheap order spectrum for the local tier (Component 8): resample onto a
    uniform revolution grid at a coarse `samples_per_rev`, then rfft. Independent of (and much
    lower-resolution than) scripts/diag/angular.py's order_spectrum -- that one runs server-side
    against a >=5M-point cache; this one runs at the machine, against whatever a single cut's
    live_cache holds, and only needs to answer "is there an obvious repeating pattern" before the
    operator walks away from the part.

    `revs` must be monotonically non-decreasing (revs_cum). Returns (orders, amplitude), orders
    capped to `max_order` -- consistent with the server pipeline's own metrics-payload cap, and
    for the same reason: everything diagnostically interesting (insert passing, its harmonics,
    the non-integer chatter orders between them) lives in the low orders.
    """
    revs = np.asarray(revs, dtype=np.float64)
    sig = np.asarray(sig, dtype=np.float64)
    if revs.size < samples_per_rev * 2:
        return [], []
    n_rev = int(revs[-1] - revs[0])
    if n_rev < 2:
        return [], []
    grid = revs[0] + np.arange(n_rev * samples_per_rev) / samples_per_rev
    resampled = np.interp(grid, revs, sig)
    spec = np.fft.rfft(resampled - np.mean(resampled))
    orders = np.fft.rfftfreq(resampled.size, d=1.0 / samples_per_rev)
    amp = np.abs(spec) / resampled.size
    keep = orders <= max_order
    return orders[keep].tolist(), amp[keep].tolist()


def drift_check(t: np.ndarray, axes: dict[str, np.ndarray], thresh_frac: float = 0.1) -> dict:
    """Flag whether each summed axis shows a linear baseline drift large enough to matter,
    independent of whether drift_comp correction is enabled -- this is a diagnostic check, not
    the correction itself (see finalize.py's drift_comp, which unconditionally detrends when the
    operator opts in). "Large enough to matter" is the trend's total excursion over the capture
    (|slope| * duration) exceeding `thresh_frac` of the axis's own peak-to-peak amplitude, so a
    small drift on a small, quiet signal isn't judged by the same absolute-Newtons yardstick as
    a small drift on a violently noisy one.
    """
    t = np.asarray(t, dtype=np.float64)
    duration = float(t[-1] - t[0]) if t.size > 1 else 0.0
    out: dict = {}
    any_detected = False
    for name, sig in axes.items():
        sig = np.asarray(sig, dtype=np.float64)
        if sig.size < 2 or duration <= 0:
            out[name] = {"slope_n_per_sec": 0.0, "excursion_frac": 0.0, "detected": False}
            continue
        slope = float(np.polyfit(t, sig, 1)[0])
        ptp = float(np.ptp(sig))
        excursion_frac = (abs(slope) * duration / ptp) if ptp > 1e-9 else 0.0
        detected = excursion_frac > thresh_frac
        any_detected = any_detected or detected
        out[name] = {
            "slope_n_per_sec": slope,
            "excursion_frac": excursion_frac,
            "detected": detected,
        }
    out["detected"] = any_detected
    return out
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd apps/force-app/backend && python -m pytest tests/test_drift_cut.py -v -k "drift_check or order_spectrum_quick"`
Expected: PASS (all 3 new tests), and re-run the full file to confirm no regressions: `python -m pytest tests/test_drift_cut.py -v`

- [ ] **Step 5: Wire into `finalize()`**

In `apps/force-app/backend/app/finalize.py`, add the import:

```python
from .dsp import drift_check, order_spectrum_quick, rpm_from_tacho, sum_axes, tacho_column
```

(replaces the existing `from .dsp import rpm_from_tacho, sum_axes, tacho_column` line)

After the existing `rpm, tacho_measured = rpm_from_tacho(tacho, fs, cfg.ppr)` / `revs_cum = ...` lines and before the `.mat` write, add the local-tier computation:

```python
    # Local tier (Component 8, deliberately thin): a quick order spectrum + a drift-detection
    # flag, computed here because finalize() only ever runs after the acquisition loop has
    # stopped (see session.py's _run -> self.raw.close() -> _finalize_async) -- this is what
    # makes "never runs during recording" structural rather than a rule this function has to
    # separately enforce. The order spectrum needs a real revs_cum to resample against; without
    # a measured tacho there is no revolution axis to resample onto, so it refuses rather than
    # guessing one (same refusal-over-aliasing pattern as scripts/diag/pipeline.py's envelope
    # analysis).
    if tacho_measured:
        os_orders, os_amp = order_spectrum_quick(revs_cum, axes["Fz"])
        os_status = "computed" if os_orders else "refused: cut too short for a revolution grid"
    else:
        os_orders, os_amp = [], []
        os_status = "refused: tacho not measured"
    local_diag = {
        "order_spectrum_status": os_status,
        "order_spectrum": {"orders": os_orders, "amplitude": os_amp} if os_orders else None,
        "drift": drift_check(t, axes),
    }
```

Add `"local_diag": local_diag,` to the `summary` dict (near the existing `"drift_comp": bool(cfg.drift_comp),` line).

- [ ] **Step 6: Write the failing end-to-end assertion**

In `apps/force-app/backend/tests/test_pipeline.py`, extend `test_session_end_to_end` (after the existing `assert "CNMG-1204" in str(m["metadata"]["Insert"])` line) with:

```python
    summ = json.load(open(os.path.join(d, "summary.json")))
    assert summ["local_diag"]["order_spectrum_status"] == "computed"
    assert len(summ["local_diag"]["order_spectrum"]["orders"]) > 0
    assert "detected" in summ["local_diag"]["drift"]
```

Add `import json` at the top of the file if not already present (it is not, per the current imports list — `json`, `os`, `numpy`, `scipy.io.loadmat`).

- [ ] **Step 7: Run test to verify it fails, then passes**

Run: `cd apps/force-app/backend && python -m pytest tests/test_pipeline.py::test_session_end_to_end -v`
Expected first: FAIL with `KeyError: 'local_diag'` (before Step 5's edit is picked up — if Step 5 is already applied when this runs, skip straight to the pass check).
Expected after Step 5: PASS.

- [ ] **Step 8: Run the full backend test suite**

Run: `cd apps/force-app/backend && python -m pytest -v`
Expected: PASS, 0 failures, no regressions in `test_drift_cut.py`, `test_pipeline.py`, or any other file touched by earlier phases this session.

- [ ] **Step 9: Commit**

```bash
git add apps/force-app/backend/app/dsp.py apps/force-app/backend/app/finalize.py apps/force-app/backend/tests/test_drift_cut.py apps/force-app/backend/tests/test_pipeline.py
git commit -m "feat(force-app): local-tier order spectrum + drift check in finalize()"
```

---

## Not in scope for this phase

- **No Directus UI for creating/editing `tool_setup` rows.** The table is a plain Postgres table an admin can populate directly (via Directus's generic Data Studio, which already surfaces any table, or `psql`); a bespoke management screen is not justified by current usage (there is no working end-to-end diag octree yet — see the master plan's parked MATLAB/archive regression — so there is nothing to link a setup to for a real smoke test today).
- **No frontend surfacing of `local_diag`** in `CapturesSettings.vue`/`EditCaptureMetadataDialog.vue`. It lands in `summary.json`, available for a future UI slice; adding UI here would be new-surface-without-a-consumer, the same reason Phases 3-5 didn't add Vue panels beyond Phase 2's workbench shell.
- **FRF estimation.** Explicitly out of scope per the design spec's non-goals — the worker applies a supplied `h_matrix`, it never measures one.
