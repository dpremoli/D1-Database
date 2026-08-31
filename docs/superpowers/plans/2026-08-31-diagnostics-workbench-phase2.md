# Diagnostics Workbench Phase 2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the Diagnostics Workbench's shell UI — a shared Vue component reachable from both hosts, showing the diag octree (Panel B) linked to a time-series/residual view (Panel A) via a shared selection, with a Selection Inspector and a bandwidth-validity strip.

**Architecture:** Reuse over new code wherever the existing codebase already solves the problem: `ForceChart.vue`'s existing `cropStart`/`cropEnd` drag-brush becomes the time-range selection for Panel A with zero new charting code; `FrmOctree.vue`'s attribute-uniform `ShaderMaterial` pattern generalizes directly to the new D1AN channels plus a selection-highlight uniform for Panel B. New shared logic (D1AN parsing, selection predicates, WorkingSet stats) is pure TypeScript, unit-tested; the `.vue` wiring layers are typecheck-verified only, matching this package's existing convention (no `@vue/test-utils` dependency here).

**Tech Stack:** Vue 3 `<script setup>` + TypeScript, three.js + potree-core (existing), Vitest, `vue-tsc`.

**Spec:** `docs/superpowers/specs/2026-08-30-diagnostics-workbench-design.md` (Components 5–7), continuing `docs/superpowers/plans/2026-08-30-diagnostics-workbench.md`'s "Phase 2 — Workbench shell".

## Global Constraints

- New shared code lives in `packages/force-plotting/src/`. Never import from `apps/force-app/*` there — the dependency direction is app → package, not the reverse.
- `.vue` components in this package are **not** unit-tested (no `@vue/test-utils` dependency). Verify them with `npx vue-tsc --noEmit`, run from `packages/force-plotting/`. Pure `.ts` logic **is** unit-tested with Vitest — follow the existing pattern in `liveCloud.test.ts` / `host.test.ts` / `filterChain.test.ts`.
- The D1AN binary layout (magic `0x4431414E`, version `1`, header `u32 magic|u32 version|u32 n|u32 n_cols`, then `n_cols` × 16-byte ASCII names, then `n_cols` column-major `float32[n]` arrays) is fixed by `scripts/diag/d1an.py` from Phase 1. The TypeScript reader must byte-for-byte match it — do not invent a different layout.
- No live diag octree exists in production yet (a pre-existing, unrelated MATLAB/archive regression blocks a fresh build — see the Phase 1 session notes). Every task here must be verifiable with synthetic/hand-built data, not a live fetch.
- Never claim a step passes without running it and reading the output.

---

## Scope note: a real gap found in Phase 1's output, closed by Task 1

Phase 1's `write_d1an(...)` call in `process_diag_row` writes `attrs.d1an` into a **temp directory that gets deleted** (`finally: shutil.rmtree(outdir, ...)`) — nothing ever publishes it. The browser has no way to fetch per-point analysis attributes for JS-side statistics; `FrmOctree`'s existing attribute-uniform mechanism only gets Fx/Fy/Fz onto the GPU via the Potree-converted octree, not the D1AN file. Task 1 closes this gap: it publishes `attrs.d1an` next to the octree files, and adds `x`/`y` to it (computed already, currently discarded) so the file is self-contained for spatial statistics without also having to parse the Potree binary format in the browser.

## File Structure

**New in `packages/force-plotting/src/`:**

| File | Responsibility |
|---|---|
| `diagAttrs.ts` | Parse the published D1AN binary into named `Float32Array` columns |
| `selection.ts` | Selection predicate types (time / attribute / lasso), matching, and stats over a `WorkingSet` |
| `DiagOctreeView.vue` | `FrmOctree.vue`'s pattern, generalized to diag channels + a selection-highlight uniform |
| `SelectionInspector.vue` | Small readout: n points, t-span, r-range, mean residual |
| `BandwidthStrip.vue` | Quantitative-vs-event band validity strip, driven by `diag_metrics` |
| `WorkbenchPanel.vue` | Shared dockable-panel chrome (title bar, drag handle, close button) — this package's own copy of the pattern `apps/force-app/web/src/record/panels/PanelFrame.vue` already establishes; force-plotting cannot import app-local files |
| `DiagnosticsWorkbench.vue` | The shell: `GridLayout`, owns selection state, wires Panels A/B + inspector + strip |

**Modified:**

| File | Change |
|---|---|
| `scripts/diag/pipeline.py` | `analyse()` also returns `x`/`y` columns (already computed, currently discarded) |
| `scripts/force_orchestrator.py` | `process_diag_row` publishes `attrs.d1an` alongside the octree files; drops its now-redundant separate x/y angular-resample (reuses `columns['x']`/`columns['y']`) |
| `packages/force-plotting/src/index.ts` | Export the new public API |

**Tests:** `packages/force-plotting/src/diagAttrs.test.ts`, `packages/force-plotting/src/selection.test.ts`, `tests/scripts/diag/test_pipeline.py` (extended).

**Explicitly deferred** (not in this plan): figure export, Z-height/pinch-zoom gestures, spatial lasso *drawing* UI (the predicate and point-in-polygon test are built; the mouse-drag-to-draw interaction is Phase 2.5), attribute-threshold slider UI (the predicate and stats are built; the control widget is Phase 2.5), HDBSCAN cluster overlay and Getis-Ord hotspot rendering (Phase 3, no data exists yet), envelope/order spectrum panel (Phase 4).

---

### Task 1: Publish `attrs.d1an` with x/y, close the WorkingSet data gap

**Files:**
- Modify: `scripts/diag/pipeline.py`
- Modify: `scripts/force_orchestrator.py`
- Test: `tests/scripts/diag/test_pipeline.py`

**Interfaces:**
- Consumes: existing `angular_resample`, `tsa`, `radial_detrend` (Task 3/4 of Phase 1, unchanged)
- Produces: `analyse()` now returns `columns` with keys `{t, rev, x, y, tsa_resid, resid_z}` (previously missing `x`, `y`)

- [ ] **Step 1: Write the failing test**

Add to `tests/scripts/diag/test_pipeline.py`:

```python
def test_pipeline_columns_include_spatial_coordinates():
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
    cols, _ = analyse(cache, x, y, samples_per_rev=SPR)
    assert set(cols) == {"t", "rev", "x", "y", "tsa_resid", "resid_z"}
    # x/y must land on the same radius the spiral actually has at that revolution --
    # not just be finite/present. rho = 40.0 - 0.05*revs in _synthetic_cut.
    r = np.hypot(cols["x"], cols["y"])
    expected_r = 40.0 - 0.05 * cols["rev"]
    np.testing.assert_allclose(r, expected_r, atol=0.05)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd C:\Users\WS-X180-PC\Documents\GitHub\D1-Database\.claude\worktrees\diagnostics-workbench && python -m pytest tests/scripts/diag/test_pipeline.py::test_pipeline_columns_include_spatial_coordinates -v`
Expected: FAIL — `assert {'t', 'rev', 'tsa_resid', 'resid_z'} == {'t', 'rev', 'x', 'y', 'tsa_resid', 'resid_z'}`

- [ ] **Step 3: Add x/y to `analyse()`'s returned columns**

In `scripts/diag/pipeline.py`, the `columns` dict at the end of `analyse()` currently reads:

```python
    columns = {
        "t": t_ang.astype(np.float32),
        "rev": rev_grid.astype(np.float32),
        "tsa_resid": residual.astype(np.float32),
        "resid_z": resid_z.astype(np.float32),
    }
    return columns, metrics
```

`x_ang`/`y_ang` are already computed a few lines above (truncated to `n` alongside `t_ang`/`rev_grid`) and currently discarded. Change the dict to:

```python
    columns = {
        "t": t_ang.astype(np.float32),
        "rev": rev_grid.astype(np.float32),
        "x": x_ang.astype(np.float32),
        "y": y_ang.astype(np.float32),
        "tsa_resid": residual.astype(np.float32),
        "resid_z": resid_z.astype(np.float32),
    }
    return columns, metrics
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/scripts/diag/ -v`
Expected: all pass, including the new test (25 total: the prior 24 plus this one)

- [ ] **Step 5: Publish `attrs.d1an` from the orchestrator and drop the redundant x/y resample**

In `scripts/force_orchestrator.py`, `process_diag_row` currently re-derives `xa`/`ya` for the LAS positions via its own separate `angular_resample` calls, duplicating work `analyse()` already did (and previously had to, since `analyse()` didn't return them). Now that it does, simplify: pull `xa`/`ya` from `columns` instead, and copy the D1AN file into the publish directory.

Find this block (added in Phase 1 Task 7):

```python
        columns, metrics = analyse(cache, x, y, samples_per_rev=DIAG_SAMPLES_PER_REV)
        n = columns["t"].size
        write_d1an(str(Path(outdir) / "attrs.d1an"), columns)

        # The analysis grid is shorter than the cloud (TSA truncates to whole revolutions and
        # resampling moves onto an angular grid), so re-sample the spatial coordinates onto
        # the same grid rather than assuming a 1:1 index match.
        revs = np.asarray(cache["revs"], dtype=np.float64)
        _, xa = angular_resample(revs, np.asarray(x, np.float64), DIAG_SAMPLES_PER_REV)
        _, ya = angular_resample(revs, np.asarray(y, np.float64), DIAG_SAMPLES_PER_REV)
        _, fza = angular_resample(revs, np.asarray(fz, np.float64), DIAG_SAMPLES_PER_REV)
        xa, ya, fza = xa[:n], ya[:n], fza[:n]
```

Replace it with:

```python
        columns, metrics = analyse(cache, x, y, samples_per_rev=DIAG_SAMPLES_PER_REV)
        n = columns["t"].size
        d1an_path = Path(outdir) / "attrs.d1an"
        write_d1an(str(d1an_path), columns)

        # analyse() now returns x/y on the same angular grid as every other column (Task 1,
        # Phase 2) -- reuse them instead of re-resampling. Force (for the LAS intensity ramp)
        # still needs its own resample: it isn't one of analyse()'s returned columns.
        xa, ya = columns["x"].astype(np.float64), columns["y"].astype(np.float64)
        revs = np.asarray(cache["revs"], dtype=np.float64)
        _, fza = angular_resample(revs, np.asarray(fz, np.float64), DIAG_SAMPLES_PER_REV)
        fza = fza[:n]
```

Then find the publish step (copies `metadata.json`/`hierarchy.bin`/`octree.bin`):

```python
        op = str(row["operation_id"])
        dst = OCTREE_DIR / "diag" / op
        if dst.exists():
            shutil.rmtree(dst, ignore_errors=True)
        dst.mkdir(parents=True, exist_ok=True)
        for fn in ("metadata.json", "hierarchy.bin", "octree.bin"):
            shutil.copy2(Path(octmp) / fn, dst / fn)
```

Add the D1AN file to the same publish step:

```python
        op = str(row["operation_id"])
        dst = OCTREE_DIR / "diag" / op
        if dst.exists():
            shutil.rmtree(dst, ignore_errors=True)
        dst.mkdir(parents=True, exist_ok=True)
        for fn in ("metadata.json", "hierarchy.bin", "octree.bin"):
            shutil.copy2(Path(octmp) / fn, dst / fn)
        shutil.copy2(d1an_path, dst / "attrs.d1an")
```

The `import numpy as np` at the top of `process_diag_row` (already present from Phase 1 for the LAS extra-dim dtype) covers the `.astype(np.float64)` calls above; no new import needed.

- [ ] **Step 6: Verify the module still imports and lints**

Run: `python -c "import sys; sys.path.insert(0,'scripts'); import force_orchestrator"`
Expected: no output, exit 0

Run: `python -m ruff check scripts/force_orchestrator.py scripts/diag`
Expected: no findings

- [ ] **Step 7: Commit**

```bash
git add scripts/diag/pipeline.py scripts/force_orchestrator.py tests/scripts/diag/test_pipeline.py
git commit -m "feat(diag): publish attrs.d1an with x/y for the browser WorkingSet"
```

---

### Task 2: TypeScript D1AN reader

**Files:**
- Create: `packages/force-plotting/src/diagAttrs.ts`
- Test: `packages/force-plotting/src/diagAttrs.test.ts`

**Interfaces:**
- Consumes: nothing
- Produces:
  - `interface DiagAttrs { n: number; columns: Record<string, Float32Array>; }`
  - `parseD1an(buf: ArrayBuffer): DiagAttrs`
  - `fetchD1an(url: string): Promise<DiagAttrs>`
  - `const D1AN_MAGIC = 0x4431414e`

- [ ] **Step 1: Write the failing test**

```typescript
// packages/force-plotting/src/diagAttrs.test.ts
import { describe, expect, it } from 'vitest';
import { D1AN_MAGIC, parseD1an } from './diagAttrs';

const NAME_BYTES = 16;
const HEADER_SIZE = 16;

function buildD1an(columns: Record<string, Float32Array>, opts?: { magic?: number; version?: number }): ArrayBuffer {
	const names = Object.keys(columns);
	const n = columns[names[0]]?.length ?? 0;
	const nCols = names.length;
	const buf = new ArrayBuffer(HEADER_SIZE + nCols * NAME_BYTES + nCols * n * 4);
	const dv = new DataView(buf);
	dv.setUint32(0, opts?.magic ?? D1AN_MAGIC, true);
	dv.setUint32(4, opts?.version ?? 1, true);
	dv.setUint32(8, n, true);
	dv.setUint32(12, nCols, true);
	let off = HEADER_SIZE;
	const enc = new TextEncoder();
	for (const name of names) {
		const bytes = new Uint8Array(buf, off, NAME_BYTES);
		bytes.set(enc.encode(name).subarray(0, NAME_BYTES));
		off += NAME_BYTES;
	}
	for (const name of names) {
		new Float32Array(buf, off, n).set(columns[name]);
		off += n * 4;
	}
	return buf;
}

describe('parseD1an', () => {
	it('round-trips named float32 columns', () => {
		const t = new Float32Array([0, 0.5, 1, 1.5]);
		const residZ = new Float32Array([-1.2, 0.3, 5.7, -0.9]);
		const buf = buildD1an({ t, resid_z: residZ });
		const parsed = parseD1an(buf);
		expect(parsed.n).toBe(4);
		expect(Array.from(parsed.columns.t)).toEqual(Array.from(t));
		expect(Array.from(parsed.columns.resid_z)).toEqual(Array.from(residZ));
	});

	it('rejects a bad magic number', () => {
		const buf = buildD1an({ t: new Float32Array([1, 2]) }, { magic: 0xdeadbeef });
		expect(() => parseD1an(buf)).toThrow(/magic/);
	});

	it('rejects an unsupported version', () => {
		const buf = buildD1an({ t: new Float32Array([1, 2]) }, { version: 2 });
		expect(() => parseD1an(buf)).toThrow(/version/);
	});

	it('handles a name shorter than the 16-byte slot (null-padded)', () => {
		const buf = buildD1an({ t: new Float32Array([1, 2, 3]) });
		const parsed = parseD1an(buf);
		expect(Object.keys(parsed.columns)).toEqual(['t']);
	});

	it('handles the full 16-byte name with no null terminator', () => {
		// 'tsa_resid_test16' is exactly 16 ASCII bytes -- the name field has no room for a
		// null terminator, which the parser must not require.
		const name = 'tsa_resid_test16';
		expect(name.length).toBe(16);
		const buf = buildD1an({ [name]: new Float32Array([9, 8, 7]) });
		const parsed = parseD1an(buf);
		expect(Object.keys(parsed.columns)).toEqual([name]);
		expect(Array.from(parsed.columns[name])).toEqual([9, 8, 7]);
	});
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd packages/force-plotting && npx vitest run src/diagAttrs.test.ts`
Expected: FAIL — cannot resolve `./diagAttrs`

- [ ] **Step 3: Write the implementation**

```typescript
// packages/force-plotting/src/diagAttrs.ts
// D1AN analysis-attribute binary reader -- the browser-side mirror of scripts/diag/d1an.py.
// Byte layout is fixed by that file; this must match it exactly:
//   magic u32 | version u32 | n u32 | n_cols u32
//   n_cols * 16-byte ASCII column names (null-padded, or exactly 16 bytes with no terminator)
//   n_cols * float32[n], column-major
//
// Published by the diag orchestrator handler alongside the octree files (see
// scripts/force_orchestrator.py's process_diag_row) at
// <octreeUrl>/diag/<operationId>/attrs.d1an -- this is the WorkingSet's data source for
// JS-side statistics (Selection Inspector, spatial predicates). Per-point GPU rendering reads
// the SAME underlying values a different way: as LAS extra-dim attributes streamed by the
// Potree octree itself (see DiagOctreeView.vue), not by fetching this file.

export const D1AN_MAGIC = 0x4431414e; // 'D1AN'
const D1AN_VERSION = 1;
const HEADER_SIZE = 16; // 4 * u32
const NAME_BYTES = 16;

export interface DiagAttrs {
	n: number;
	columns: Record<string, Float32Array>;
}

export function parseD1an(buf: ArrayBuffer): DiagAttrs {
	if (buf.byteLength < HEADER_SIZE) throw new Error('D1AN buffer too short for header');
	const dv = new DataView(buf);
	const magic = dv.getUint32(0, true);
	if (magic !== D1AN_MAGIC) {
		throw new Error(`bad D1AN magic 0x${magic.toString(16)}`);
	}
	const version = dv.getUint32(4, true);
	if (version !== D1AN_VERSION) {
		throw new Error(`unsupported D1AN version ${version}`);
	}
	const n = dv.getUint32(8, true);
	const nCols = dv.getUint32(12, true);

	const decoder = new TextDecoder('ascii');
	const names: string[] = [];
	let off = HEADER_SIZE;
	for (let i = 0; i < nCols; i++) {
		const bytes = new Uint8Array(buf, off, NAME_BYTES);
		const nul = bytes.indexOf(0);
		names.push(decoder.decode(bytes.subarray(0, nul < 0 ? NAME_BYTES : nul)));
		off += NAME_BYTES;
	}

	// off is now HEADER_SIZE + nCols*NAME_BYTES, always a multiple of 4 (both terms are
	// multiples of 4), so each column below can be a zero-copy Float32Array view rather than
	// a copy -- important at multi-million-point sizes.
	const columns: Record<string, Float32Array> = {};
	const bytesNeeded = off + nCols * n * 4;
	if (buf.byteLength < bytesNeeded) {
		throw new Error(
			`D1AN buffer truncated: need ${bytesNeeded} bytes, have ${buf.byteLength}`,
		);
	}
	for (let i = 0; i < nCols; i++) {
		columns[names[i]] = new Float32Array(buf, off, n);
		off += n * 4;
	}
	return { n, columns };
}

export async function fetchD1an(url: string): Promise<DiagAttrs> {
	const res = await fetch(url, { cache: 'no-store' });
	if (!res.ok) throw new Error(`D1AN fetch failed: ${res.status} ${res.statusText}`);
	return parseD1an(await res.arrayBuffer());
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd packages/force-plotting && npx vitest run src/diagAttrs.test.ts`
Expected: 5 passed

- [ ] **Step 5: Typecheck and commit**

```bash
cd packages/force-plotting && npx vue-tsc --noEmit
git add packages/force-plotting/src/diagAttrs.ts packages/force-plotting/src/diagAttrs.test.ts
git commit -m "feat(force-plotting): add D1AN binary reader"
```

---

### Task 3: Selection predicates and WorkingSet stats

**Files:**
- Create: `packages/force-plotting/src/selection.ts`
- Test: `packages/force-plotting/src/selection.test.ts`

**Interfaces:**
- Consumes: `DiagAttrs` from `diagAttrs.ts` (Task 2)
- Produces:
  - `interface WorkingSet { n: number; t: Float32Array; rev: Float32Array; x: Float32Array; y: Float32Array; tsaResid: Float32Array; residZ: Float32Array; }`
  - `workingSetFromD1an(attrs: DiagAttrs): WorkingSet`
  - `type Selection = { kind: 'time'; t0: number; t1: number } | { kind: 'attribute'; column: 'residZ' | 'tsaResid'; min: number; max: number } | { kind: 'lasso'; polygon: [number, number][] } | null`
  - `matches(ws: WorkingSet, sel: Selection, i: number): boolean`
  - `interface SelectionStats { n: number; tMin: number; tMax: number; rMin: number; rMax: number; meanResidZ: number; }`
  - `computeStats(ws: WorkingSet, sel: Selection): SelectionStats`

- [ ] **Step 1: Write the failing test**

```typescript
// packages/force-plotting/src/selection.test.ts
import { describe, expect, it } from 'vitest';
import type { DiagAttrs } from './diagAttrs';
import { computeStats, matches, workingSetFromD1an } from './selection';
import type { Selection } from './selection';

function makeAttrs(): DiagAttrs {
	// 5 points on a line, spiralling outward in r for variety.
	return {
		n: 5,
		columns: {
			t: new Float32Array([0, 1, 2, 3, 4]),
			rev: new Float32Array([0, 1, 2, 3, 4]),
			x: new Float32Array([10, 12, 14, 16, 18]),
			y: new Float32Array([0, 0, 0, 0, 0]),
			tsa_resid: new Float32Array([0.1, 0.2, 0.3, 0.4, 0.5]),
			resid_z: new Float32Array([-5, -1, 0, 1, 5]),
		},
	};
}

describe('workingSetFromD1an', () => {
	it('maps snake_case D1AN columns to the WorkingSet shape', () => {
		const ws = workingSetFromD1an(makeAttrs());
		expect(ws.n).toBe(5);
		expect(Array.from(ws.residZ)).toEqual([-5, -1, 0, 1, 5]);
		expect(Array.from(ws.tsaResid)).toEqual([0.1, 0.2, 0.3, 0.4, 0.5]);
	});

	it('throws when a required column is missing', () => {
		const attrs = makeAttrs();
		delete attrs.columns.resid_z;
		expect(() => workingSetFromD1an(attrs)).toThrow(/resid_z/);
	});
});

describe('matches', () => {
	const ws = workingSetFromD1an(makeAttrs());

	it('null selection matches everything', () => {
		for (let i = 0; i < ws.n; i++) expect(matches(ws, null, i)).toBe(true);
	});

	it('time selection matches an inclusive range', () => {
		const sel: Selection = { kind: 'time', t0: 1, t1: 3 };
		expect([0, 1, 2, 3, 4].map((i) => matches(ws, sel, i))).toEqual([false, true, true, true, false]);
	});

	it('attribute selection matches an inclusive range on resid_z', () => {
		const sel: Selection = { kind: 'attribute', column: 'residZ', min: -1, max: 1 };
		expect([0, 1, 2, 3, 4].map((i) => matches(ws, sel, i))).toEqual([false, true, true, true, false]);
	});

	it('lasso selection matches points inside the polygon', () => {
		const sel: Selection = { kind: 'lasso', polygon: [[11, -1], [13, -1], [13, 1], [11, 1]] };
		// only point 1 (x=12,y=0) falls inside [11,13]x[-1,1]
		expect([0, 1, 2, 3, 4].map((i) => matches(ws, sel, i))).toEqual([false, true, false, false, false]);
	});
});

describe('computeStats', () => {
	const ws = workingSetFromD1an(makeAttrs());

	it('computes stats over the full set with no selection', () => {
		const s = computeStats(ws, null);
		expect(s.n).toBe(5);
		expect(s.tMin).toBe(0);
		expect(s.tMax).toBe(4);
		expect(s.meanResidZ).toBeCloseTo(0, 6);
	});

	it('computes stats restricted to a time selection', () => {
		const s = computeStats(ws, { kind: 'time', t0: 1, t1: 3 });
		expect(s.n).toBe(3);
		expect(s.tMin).toBe(1);
		expect(s.tMax).toBe(3);
		expect(s.meanResidZ).toBeCloseTo(0, 6); // (-1+0+1)/3
	});

	it('returns a zeroed result for an empty selection rather than NaN', () => {
		const s = computeStats(ws, { kind: 'time', t0: 100, t1: 200 });
		expect(s).toEqual({ n: 0, tMin: 0, tMax: 0, rMin: 0, rMax: 0, meanResidZ: 0 });
	});
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd packages/force-plotting && npx vitest run src/selection.test.ts`
Expected: FAIL — cannot resolve `./selection`

- [ ] **Step 3: Write the implementation**

```typescript
// packages/force-plotting/src/selection.ts
// Shared selection state for the Diagnostics Workbench: a WorkingSet is the decimated,
// off-GPU point set the D1AN file provides; a Selection is a predicate over it, evaluated the
// same way regardless of which panel produced it (time brush in Panel A, attribute threshold
// or spatial lasso in Panel B) -- that symmetry is what makes cross-panel highlighting work
// without each panel needing to know about the others.
import type { DiagAttrs } from './diagAttrs';

export interface WorkingSet {
	n: number;
	t: Float32Array;
	rev: Float32Array;
	x: Float32Array;
	y: Float32Array;
	tsaResid: Float32Array;
	residZ: Float32Array;
}

const REQUIRED_COLUMNS = ['t', 'rev', 'x', 'y', 'tsa_resid', 'resid_z'] as const;

export function workingSetFromD1an(attrs: DiagAttrs): WorkingSet {
	for (const col of REQUIRED_COLUMNS) {
		if (!(col in attrs.columns)) {
			throw new Error(`D1AN file is missing required column '${col}'`);
		}
	}
	return {
		n: attrs.n,
		t: attrs.columns.t,
		rev: attrs.columns.rev,
		x: attrs.columns.x,
		y: attrs.columns.y,
		tsaResid: attrs.columns.tsa_resid,
		residZ: attrs.columns.resid_z,
	};
}

export type Selection =
	| { kind: 'time'; t0: number; t1: number }
	| { kind: 'attribute'; column: 'residZ' | 'tsaResid'; min: number; max: number }
	| { kind: 'lasso'; polygon: [number, number][] }
	| null;

// Standard even-odd ray-casting point-in-polygon test.
function pointInPolygon(px: number, py: number, poly: [number, number][]): boolean {
	let inside = false;
	for (let i = 0, j = poly.length - 1; i < poly.length; j = i++) {
		const [xi, yi] = poly[i];
		const [xj, yj] = poly[j];
		const crosses = yi > py !== yj > py;
		if (crosses && px < ((xj - xi) * (py - yi)) / (yj - yi) + xi) inside = !inside;
	}
	return inside;
}

export function matches(ws: WorkingSet, sel: Selection, i: number): boolean {
	if (sel == null) return true;
	switch (sel.kind) {
		case 'time':
			return ws.t[i] >= sel.t0 && ws.t[i] <= sel.t1;
		case 'attribute': {
			const v = sel.column === 'residZ' ? ws.residZ[i] : ws.tsaResid[i];
			return v >= sel.min && v <= sel.max;
		}
		case 'lasso':
			return pointInPolygon(ws.x[i], ws.y[i], sel.polygon);
		default:
			return false;
	}
}

export interface SelectionStats {
	n: number;
	tMin: number;
	tMax: number;
	rMin: number;
	rMax: number;
	meanResidZ: number;
}

const ZERO_STATS: SelectionStats = { n: 0, tMin: 0, tMax: 0, rMin: 0, rMax: 0, meanResidZ: 0 };

export function computeStats(ws: WorkingSet, sel: Selection): SelectionStats {
	let n = 0;
	let tMin = Infinity;
	let tMax = -Infinity;
	let rMin = Infinity;
	let rMax = -Infinity;
	let sum = 0;
	for (let i = 0; i < ws.n; i++) {
		if (!matches(ws, sel, i)) continue;
		n++;
		const t = ws.t[i];
		if (t < tMin) tMin = t;
		if (t > tMax) tMax = t;
		const r = Math.hypot(ws.x[i], ws.y[i]);
		if (r < rMin) rMin = r;
		if (r > rMax) rMax = r;
		sum += ws.residZ[i];
	}
	if (n === 0) return { ...ZERO_STATS };
	return { n, tMin, tMax, rMin, rMax, meanResidZ: sum / n };
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd packages/force-plotting && npx vitest run src/selection.test.ts`
Expected: 10 passed

- [ ] **Step 5: Typecheck and commit**

```bash
cd packages/force-plotting && npx vue-tsc --noEmit
git add packages/force-plotting/src/selection.ts packages/force-plotting/src/selection.test.ts
git commit -m "feat(force-plotting): add selection predicates and WorkingSet stats"
```

---

### Task 4: `DiagOctreeView.vue` — generalize the octree shader to diag channels + selection highlight

This is the highest-risk task: it edits a working shader. Follow `FrmOctree.vue`'s existing structure closely rather than redesigning it — the goal is the smallest change that adds diag channels and a highlight uniform, not a rewrite.

**Files:**
- Create: `packages/force-plotting/src/DiagOctreeView.vue`

**Interfaces:**
- Consumes: `Selection` and `matches`-equivalent logic re-expressed as GPU uniforms (see below); potree-core's existing octree-loading API, identical to `FrmOctree.vue`'s usage
- Produces: a `channel` prop selecting among `'Fx' | 'Fy' | 'Fz' | 'tsaResid' | 'residZ'`; a `selection` prop of type `Selection` (imported from `./selection`) that drives per-point highlighting

**Design decision — GPU-side selection, not JS-side:** Re-testing `matches()` in JavaScript for every rendered point every frame would mean walking the WorkingSet on every camera move, entirely defeating LOD streaming. Instead, the *same three predicate kinds* are re-expressed as shader uniforms and evaluated per-vertex in GLSL, exactly the way `uAxis`/`uRange` already select and normalize a colour channel. A point outside the active selection is drawn as before but at reduced opacity, rather than hidden — so an empty or wrong selection never reads as "no data loaded."

- [ ] **Step 1: Copy `FrmOctree.vue` as the starting point**

```bash
cd packages/force-plotting/src
cp FrmOctree.vue DiagOctreeView.vue
```

- [ ] **Step 2: Extend the props to diag channels and a selection**

In `DiagOctreeView.vue`, replace the props block:

```typescript
const props = defineProps<{
	octreePath: string;                       // served subdir: /octrees/diag/<octreePath>/
	channel: 'Fx' | 'Fy' | 'Fz' | 'tsaResid' | 'residZ';
	colormap: string;
	pointSize: number;
	cmin?: number | null;
	cmax?: number | null;
	totalPoints?: number;
	minNodePx?: number;
	budgetCap?: number;
	selection?: Selection;
}>();
```

and its import line:

```typescript
import type { Selection } from './selection';
```

Remove the `zSeries`/`zScale`/`fill`/`cellSize` props and the `zscale`/`climits` emit machinery entirely (the Z-height and grid-fill features are `FrmOctree`-specific and out of scope here — see the plan's deferred list); keep the `points`/`climits` emits.

- [ ] **Step 3: Add the new attributes and the channel picker to the shader**

The octree carries `Fx`/`Fy`/`Fz` (unchanged, still LAS extra dims) *and now also* `tsa_resid`/`resid_z` as LAS extra dims (Phase 1 Task 7 already writes these — see `process_diag_row`'s `for nm in columns: h.add_extra_dim(...)`). Extend `makeMaterial`'s vertex shader:

```glsl
attribute float Fx; attribute float Fy; attribute float Fz;
attribute float tsa_resid; attribute float resid_z;
uniform vec2 uRange; uniform float uChannel; uniform float uSize;
uniform float uSelKind;      // 0 = none, 1 = time, 2 = attribute, 3 = lasso
uniform vec2 uSelTimeRange;  // [t0, t1], only meaningful when uSelKind == 1.0
uniform vec2 uSelAttrRange;  // [min, max] on the selected attribute, uSelKind == 2.0
uniform float uSelAttrChannel; // which attribute the range selection reads: 0=residZ,1=tsaResid
attribute float t;
varying float vT;
varying float vSelected;
float pick(float i) {
	if (i < 0.5) return Fx;
	if (i < 1.5) return Fy;
	if (i < 2.5) return Fz;
	if (i < 3.5) return tsa_resid;
	return resid_z;
}
void main() {
	float v = pick(uChannel);
	vT = clamp((v - uRange.x) / max(1e-6, uRange.y - uRange.x), 0.0, 1.0);
	vSelected = 1.0;
	if (uSelKind > 0.5 && uSelKind < 1.5) {
		vSelected = (t >= uSelTimeRange.x && t <= uSelTimeRange.y) ? 1.0 : 0.0;
	} else if (uSelKind > 1.5 && uSelKind < 2.5) {
		float av = uSelAttrChannel < 0.5 ? resid_z : tsa_resid;
		vSelected = (av >= uSelAttrRange.x && av <= uSelAttrRange.y) ? 1.0 : 0.0;
	}
	gl_Position = projectionMatrix * modelViewMatrix * vec4(position.xy, 0.0, 1.0);
	gl_PointSize = uSize;
}
```

and the fragment shader:

```glsl
precision mediump float;
uniform sampler2D uGradient; varying float vT; varying float vSelected;
void main() {
	vec2 d = gl_PointCoord - vec2(0.5); if (dot(d, d) > 0.25) discard;
	vec3 c = texture2D(uGradient, vec2(vT, 0.5)).rgb;
	// Unselected points stay visible but muted -- an empty or wrong selection must never
	// read as "the map failed to load".
	float a = mix(0.15, 1.0, vSelected);
	gl_FragColor = vec4(c, a);
}
```

Note the lasso spatial predicate (`kind: 'lasso'`) is **not** wired into the shader here — a polygon test needs a variable-length uniform array or a texture-encoded polygon, which is real complexity deferred per the plan's scope note. `uSelKind` simply never reaches `3.0` yet; passing a lasso `Selection` currently has no visible effect on this view (it still drives Panel A / the Inspector via the JS-side `matches()`/`computeStats()` from Task 3). Leave a comment saying so at the top of the uniforms block.

Update `makeMaterial`'s uniform initialization to match (replace `uAxis` with `uChannel`, add the four new `uSel*` uniforms defaulting to `{ value: 0 }` / `{ value: new THREE.Vector2(0, 0) }` as appropriate), and update the `AXIS_IDX` map:

```typescript
const CHANNEL_IDX: Record<string, number> = { Fx: 0, Fy: 1, Fz: 2, tsaResid: 3, residZ: 4 };
const SEL_KIND_IDX: Record<string, number> = { time: 1, attribute: 2, lasso: 3 };
```

- [ ] **Step 4: Wire the selection prop to the new uniforms**

Add a function alongside the existing `applyRange`/`applyZ` pattern:

```typescript
function applySelection() {
	if (!material) return;
	const sel = props.selection;
	if (!sel) {
		material.uniforms.uSelKind.value = 0;
		invalidate();
		return;
	}
	material.uniforms.uSelKind.value = SEL_KIND_IDX[sel.kind];
	if (sel.kind === 'time') {
		material.uniforms.uSelTimeRange.value.set(sel.t0, sel.t1);
	} else if (sel.kind === 'attribute') {
		material.uniforms.uSelAttrRange.value.set(sel.min, sel.max);
		material.uniforms.uSelAttrChannel.value = sel.column === 'residZ' ? 0 : 1;
	}
	invalidate();
}
```

and a watcher next to the existing ones:

```typescript
watch(() => props.selection, applySelection, { deep: true });
```

Call `applySelection()` once at the end of `load()`, in the same place `applyRange()` is currently called (remove the `applyZ()` call there — the Z feature was removed in Step 2).

- [ ] **Step 5: Update the `ranges`/`channel` watcher and remove dead Z/fill code**

Rename the `ranges` map's keys and the axis watcher:

```typescript
const ranges: Record<string, [number, number]> = { Fx: [0, 1], Fy: [0, 1], Fz: [0, 1], tsaResid: [0, 1], residZ: [0, 1] };
```

```typescript
watch(() => props.channel, () => { if (material) { material.uniforms.uChannel.value = CHANNEL_IDX[props.channel] ?? 4; applyRange(); } });
```

Update `applyRange()`'s `ranges[props.axis]` reference to `ranges[props.channel]`. Delete `applyZ`, the `baseSpan`/Z-related pointer-gesture code (`onPtrDown`/`onPtrMove`/`onPtrUp`/`zPointers`/`avgVals`/`zBaseY`), the `fill`/`cellSize`/`uFill`/`uCell`/`uPxPerMm` uniform wiring, and their watchers — none of it applies here per the Step 2 scope cut. Keep `frameCamera`, `setupGL`, the render loop, `loadMeta` (update its attribute-name loop to check `a.name in ranges` against the new key set), `exportViewport`/`currentBounds` (unchanged), and the mount/unmount lifecycle as-is.

- [ ] **Step 6: Typecheck**

Run: `cd packages/force-plotting && npx vue-tsc --noEmit`
Expected: no errors. If `Selection`'s import path or the `ranges`/`CHANNEL_IDX` key sets don't line up with the `channel` prop's literal union, this is where it surfaces — fix before moving on.

- [ ] **Step 7: Commit**

```bash
git add packages/force-plotting/src/DiagOctreeView.vue
git commit -m "feat(force-plotting): add DiagOctreeView with channel + selection-highlight uniforms"
```

---

### Task 5: `WorkbenchPanel.vue` — shared dockable-panel chrome

**Files:**
- Create: `packages/force-plotting/src/WorkbenchPanel.vue`

**Interfaces:**
- Consumes: nothing
- Produces: a `<WorkbenchPanel :title :icon? :closable?>` component with a default slot and a `footer` slot, emitting `close`

This is `apps/force-app/web/src/record/panels/PanelFrame.vue`'s pattern, copied rather than imported (force-plotting cannot depend on app-local files — see Global Constraints), with the same CSS variable names (`--bg-2`, `--border`, `--text-dim`, `--danger`) this package's other components already rely on (see `FrmOctree.vue`'s `.fc-msg`/`.fc-count` styles).

- [ ] **Step 1: Write the component**

```vue
<script setup lang="ts">
// Shared dockable-panel chrome for the Diagnostics Workbench. Deliberately the same shape as
// apps/force-app/web/src/record/panels/PanelFrame.vue -- that component is app-local and
// force-plotting cannot import across the app/package boundary, so this is a copy, not a
// wrapper. Keep the two in sync by eye if one changes; they are small on purpose.
defineProps<{ title: string; icon?: string; closable?: boolean }>();
defineEmits<{ close: [] }>();
</script>

<template>
	<div class="wb-panel">
		<div class="wb-panel-handle">
			<span v-if="icon" class="material-symbols-rounded">{{ icon }}</span>
			<span class="wb-panel-title">{{ title }}</span>
			<span class="wb-panel-grip material-symbols-rounded">drag_indicator</span>
			<button v-if="closable" class="wb-panel-close" title="Close panel" @pointerdown.stop @click.stop="$emit('close')">
				<span class="material-symbols-rounded">close</span>
			</button>
		</div>
		<div class="wb-panel-body"><slot /></div>
		<div v-if="$slots.footer" class="wb-panel-footer"><slot name="footer" /></div>
	</div>
</template>

<style scoped>
.wb-panel { display: flex; flex-direction: column; height: 100%; background: color-mix(in srgb, var(--bg-2) 62%, transparent); border: 1px solid var(--border); border-radius: 12px; overflow: hidden; }
.wb-panel-handle { display: flex; align-items: center; gap: 7px; padding: 8px 12px; cursor: move; background: rgba(255,255,255,0.03); border-bottom: 1px solid var(--border); user-select: none; }
.wb-panel-handle .material-symbols-rounded { font-size: 17px; color: var(--text-dim); }
.wb-panel-title { font-size: 12.5px; font-weight: 640; letter-spacing: 0.01em; }
.wb-panel-grip { margin-left: auto; opacity: 0.5; }
.wb-panel-close { display: inline-flex; align-items: center; justify-content: center; width: 20px; height: 20px; padding: 0; border: none; background: transparent; color: var(--text-dim); cursor: pointer; border-radius: 5px; }
.wb-panel-close:hover { color: var(--danger); background: rgba(239,68,68,0.12); }
.wb-panel-close .material-symbols-rounded { font-size: 15px; }
.wb-panel-body { flex: 1; min-height: 0; overflow-y: auto; overflow-x: hidden; padding: 12px; }
.wb-panel-footer { flex-shrink: 0; padding: 10px 12px; border-top: 1px solid var(--border); background: color-mix(in srgb, var(--bg-2) 80%, transparent); }
</style>
```

- [ ] **Step 2: Typecheck and commit**

```bash
cd packages/force-plotting && npx vue-tsc --noEmit
git add packages/force-plotting/src/WorkbenchPanel.vue
git commit -m "feat(force-plotting): add shared WorkbenchPanel chrome"
```

---

### Task 6: `SelectionInspector.vue` and `BandwidthStrip.vue`

**Files:**
- Create: `packages/force-plotting/src/SelectionInspector.vue`
- Create: `packages/force-plotting/src/BandwidthStrip.vue`

**Interfaces:**
- Consumes: `SelectionStats` from `selection.ts` (Task 3)
- Produces: `<SelectionInspector :stats>` and `<BandwidthStrip :metrics>` presentational components

- [ ] **Step 1: Write `SelectionInspector.vue`**

```vue
<script setup lang="ts">
import type { SelectionStats } from './selection';

const props = defineProps<{ stats: SelectionStats }>();
const fmt = (v: number, digits = 2) => (Number.isFinite(v) ? v.toFixed(digits) : '—');
</script>

<template>
	<div class="sel-inspector">
		<div class="sel-field"><span class="sel-label">points</span><span class="sel-value">{{ props.stats.n.toLocaleString() }}</span></div>
		<div class="sel-field"><span class="sel-label">t-span</span><span class="sel-value">{{ fmt(props.stats.tMin) }} – {{ fmt(props.stats.tMax) }} s</span></div>
		<div class="sel-field"><span class="sel-label">r-range</span><span class="sel-value">{{ fmt(props.stats.rMin) }} – {{ fmt(props.stats.rMax) }} mm</span></div>
		<div class="sel-field"><span class="sel-label">mean resid_z</span><span class="sel-value">{{ fmt(props.stats.meanResidZ) }}</span></div>
	</div>
</template>

<style scoped>
.sel-inspector { display: flex; flex-wrap: wrap; gap: 14px; padding: 8px 12px; font-size: 12px; color: var(--text-dim); border-top: 1px solid var(--border); }
.sel-field { display: flex; flex-direction: column; gap: 2px; }
.sel-label { font-size: 10px; text-transform: uppercase; letter-spacing: 0.04em; opacity: 0.7; }
.sel-value { font-variant-numeric: tabular-nums; color: var(--text, #e5e7eb); }
</style>
```

- [ ] **Step 2: Write `BandwidthStrip.vue`**

`diag_metrics` (the JSON column populated by `process_diag_row`) may or may not carry `dyno_fn_hz`/`quantitative_limit_hz` — Phase 1's `analyse()` only sets them when a caller passes `fn_hz`, which nothing currently does (no setup record exists yet — see the design spec's deferred Component 4). The strip must degrade honestly rather than show a fabricated limit.

```vue
<script setup lang="ts">
const props = defineProps<{
	metrics: {
		effective_fs_hz?: number;
		effective_nyquist_hz?: number;
		dyno_fn_hz?: number;
		quantitative_limit_hz?: number;
	} | null;
}>();
const fmtHz = (v: number | undefined) => (typeof v === 'number' && Number.isFinite(v) ? `${v.toFixed(0)} Hz` : null);
</script>

<template>
	<div class="bw-strip">
		<template v-if="props.metrics?.quantitative_limit_hz">
			<span class="bw-seg bw-quant">quantitative &lt; {{ fmtHz(props.metrics.quantitative_limit_hz) }}</span>
			<span class="bw-seg bw-event">event only above {{ fmtHz(props.metrics.quantitative_limit_hz) }}</span>
		</template>
		<template v-else>
			<span class="bw-seg bw-unknown">
				dynamometer natural frequency not recorded for this setup — bandwidth validity unknown;
				treat all channels as event-detection only
			</span>
		</template>
		<span v-if="fmtHz(props.metrics?.effective_nyquist_hz)" class="bw-nyquist">
			effective Nyquist: {{ fmtHz(props.metrics?.effective_nyquist_hz) }}
		</span>
	</div>
</template>

<style scoped>
.bw-strip { display: flex; align-items: center; gap: 10px; padding: 5px 12px; font-size: 11px; border-top: 1px solid var(--border); flex-wrap: wrap; }
.bw-seg { padding: 2px 8px; border-radius: 4px; }
.bw-quant { background: color-mix(in srgb, #16a34a 22%, transparent); color: #86efac; }
.bw-event { background: color-mix(in srgb, #d97706 22%, transparent); color: #fcd34d; }
.bw-unknown { background: color-mix(in srgb, #64748b 22%, transparent); color: var(--text-dim); }
.bw-nyquist { margin-left: auto; color: var(--text-dim); font-variant-numeric: tabular-nums; }
</style>
```

- [ ] **Step 3: Typecheck and commit**

```bash
cd packages/force-plotting && npx vue-tsc --noEmit
git add packages/force-plotting/src/SelectionInspector.vue packages/force-plotting/src/BandwidthStrip.vue
git commit -m "feat(force-plotting): add SelectionInspector and BandwidthStrip"
```

---

### Task 7: `DiagnosticsWorkbench.vue` — the shell

**Files:**
- Create: `packages/force-plotting/src/DiagnosticsWorkbench.vue`

**Interfaces:**
- Consumes: `ForceChart` (existing), `DiagOctreeView` (Task 4), `WorkbenchPanel` (Task 5), `SelectionInspector`/`BandwidthStrip` (Task 6), `fetchD1an`/`workingSetFromD1an`/`computeStats`/`Selection` (Tasks 2–3), `useForceHost` (existing `host.ts`)
- Produces: `<DiagnosticsWorkbench :diag-path :diag-metrics :total-points>` — no props consumed from Directus/standalone specifics; the host wrapper (Task 8) supplies data, this component only needs the diag artifact locations

**Props contract:** the parent (host wrapper, or eventually a data-fetching container) passes:
- `diagPath: string` — the served octree subdir, matching `DiagOctreeView`'s `octreePath`
- `diagMetrics: object | null` — the `diag_metrics` JSON column, passed straight through to `BandwidthStrip`
- `totalPoints: number` — for LOD budget sizing, matching `DiagOctreeView`'s `totalPoints`

This task does not fetch from Directus itself — that stays the host wrapper's job (Task 8), consistent with how `ForceDashboard.vue` receives its data today (checked in Task 8's exploration). `DiagnosticsWorkbench` fetches only the D1AN file directly from the octree URL (a static asset, not a Directus API call), via `useForceHost().octreeUrl`.

- [ ] **Step 1: Write the component**

```vue
<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue';
import { GridLayout, GridItem } from 'grid-layout-plus';
import ForceChart from './ForceChart.vue';
import DiagOctreeView from './DiagOctreeView.vue';
import WorkbenchPanel from './WorkbenchPanel.vue';
import SelectionInspector from './SelectionInspector.vue';
import BandwidthStrip from './BandwidthStrip.vue';
import { fetchD1an } from './diagAttrs';
import { computeStats, workingSetFromD1an } from './selection';
import type { Selection, WorkingSet } from './selection';
import { useForceHost } from './host';

const props = defineProps<{
	diagPath: string;
	diagMetrics: Record<string, unknown> | null;
	totalPoints: number;
}>();

const workingSet = ref<WorkingSet | null>(null);
const loadError = ref<string | null>(null);
const selection = ref<Selection>(null);
const channel = ref<'Fx' | 'Fy' | 'Fz' | 'tsaResid' | 'residZ'>('residZ');

async function loadWorkingSet() {
	loadError.value = null;
	workingSet.value = null;
	try {
		const base = `${useForceHost().octreeUrl}/${props.diagPath}/`;
		const attrs = await fetchD1an(`${base}attrs.d1an`);
		workingSet.value = workingSetFromD1an(attrs);
	} catch (e: any) {
		loadError.value = e?.message || 'failed to load analysis attributes';
	}
}
onMounted(loadWorkingSet);
watch(() => props.diagPath, loadWorkingSet);

// ForceChart plots resid_z against revolution and doubles as the time-range brush -- its
// existing cropStart/cropEnd drag handles ARE the Panel A selection mechanism; no new
// brushing code is needed (see Task plan header).
//
// ForceChart's `data` shape is kind-specific (confirmed by reading its `geom` computed):
// kind='env' reads `d.t` (x-axis) plus `d.min[i]`/`d.max[i]` (envelope bounds); kind='line'
// reads `d.f`/`d.amp[i]` instead. The crop-drag rendering (the shaded [cropStart,cropEnd]
// overlay this component relies on for the brush) is only implemented for kind='env' (see
// ForceChart.vue's `if (props.kind === 'env')` branch around its cropArea computation) --
// kind='line' has no equivalent. There is only one resid_z series here, not a min/max band,
// so min and max are set equal: `geom.area`'s stroke still renders at 0.6px width regardless
// of the band's height, so a degenerate envelope still reads as a visible line, not a blank
// fill.
//
// The x-axis MUST be ws.t (real time, seconds), not ws.rev: Task 3's Selection{kind:'time'}
// and its already-tested matches()/computeStats() compare against ws.t, and ForceChart's
// cropStart/cropEnd are read back in the same units it was given on `d.t` -- plotting against
// revolution here while Selection means seconds would silently desynchronise the Panel A
// brush from what Panel B and the Inspector actually filter on.
const chartData = computed(() => {
	const ws = workingSet.value;
	if (!ws) return null;
	const resid = Array.from(ws.residZ);
	return { t: Array.from(ws.t), min: resid, max: resid };
});
function onCropStart(v: number) {
	const cur = selection.value;
	const t1 = cur && cur.kind === 'time' ? cur.t1 : (workingSet.value?.t.at(-1) ?? v);
	selection.value = { kind: 'time', t0: v, t1 };
}
function onCropEnd(v: number) {
	const cur = selection.value;
	const t0 = cur && cur.kind === 'time' ? cur.t0 : (workingSet.value?.t[0] ?? v);
	selection.value = { kind: 'time', t0, t1: v };
}

const stats = computed(() => (workingSet.value ? computeStats(workingSet.value, selection.value) : null));

const layout = ref([
	{ x: 0, y: 0, w: 7, h: 8, i: 'spatial' },
	{ x: 7, y: 0, w: 5, h: 8, i: 'signal' },
]);
</script>

<template>
	<div class="diag-workbench">
		<div v-if="loadError" class="dw-error">{{ loadError }}</div>
		<GridLayout v-model:layout="layout" :col-num="12" :row-height="40" :margin="[10, 10]" :is-resizable="true" :is-draggable="true">
			<GridItem v-for="item in layout" :key="item.i" :x="item.x" :y="item.y" :w="item.w" :h="item.h" :i="item.i" drag-allow-from=".wb-panel-handle">
				<WorkbenchPanel v-if="item.i === 'spatial'" title="Spatial" icon="scatter_plot">
					<DiagOctreeView
						:octree-path="props.diagPath"
						:channel="channel"
						colormap="viridis"
						:point-size="2.2"
						:total-points="props.totalPoints"
						:selection="selection"
					/>
					<template #footer>
						<select v-model="channel" class="dw-channel-select">
							<option value="residZ">resid_z (anomaly)</option>
							<option value="tsaResid">tsa_resid (residual)</option>
							<option value="Fx">Fx</option>
							<option value="Fy">Fy</option>
							<option value="Fz">Fz</option>
						</select>
					</template>
				</WorkbenchPanel>
				<WorkbenchPanel v-else-if="item.i === 'signal'" title="Signal" icon="show_chart">
					<ForceChart
						v-if="chartData"
						title="resid_z vs time"
						kind="env"
						:data="chartData"
						color="#f59e0b"
						x-unit="s"
						y-unit="σ"
						:crop-start="selection?.kind === 'time' ? selection.t0 : null"
						:crop-end="selection?.kind === 'time' ? selection.t1 : null"
						:crop-editable="true"
						@update:crop-start="onCropStart"
						@update:crop-end="onCropEnd"
					/>
					<div v-else class="dw-loading">loading…</div>
				</WorkbenchPanel>
			</GridItem>
		</GridLayout>
		<SelectionInspector v-if="stats" :stats="stats" />
		<BandwidthStrip :metrics="props.diagMetrics as any" />
	</div>
</template>

<style scoped>
.diag-workbench { display: flex; flex-direction: column; height: 100%; min-height: 0; }
.diag-workbench :deep(.vgl-layout) { flex: 1; min-height: 0; }
.dw-error { padding: 8px 12px; color: var(--danger, #fca5a5); font-size: 12px; }
.dw-loading { display: flex; align-items: center; justify-content: center; height: 100%; color: var(--text-dim); font-size: 12px; }
.dw-channel-select { width: 100%; font-size: 12px; padding: 4px 6px; background: var(--bg-2); color: var(--text, #e5e7eb); border: 1px solid var(--border); border-radius: 6px; }
</style>
```

- [ ] **Step 2: Typecheck**

Run: `cd packages/force-plotting && npx vue-tsc --noEmit`
Expected: no errors

- [ ] **Step 3: Commit**

```bash
git add packages/force-plotting/src/DiagnosticsWorkbench.vue
git commit -m "feat(force-plotting): add DiagnosticsWorkbench shell"
```

---

### Task 8: Export and host wrappers

**Files:**
- Modify: `packages/force-plotting/src/index.ts`
- Create: `core/extensions/d1-force-dashboard/src/DirectusDiagnosticsWorkbench.vue`
- Create: `apps/force-app/web/src/force/StandaloneDiagnosticsWorkbench.vue`

**Interfaces:**
- Consumes: `DiagnosticsWorkbench` (Task 7)
- Produces: the package's public export surface; two thin per-host wrapper components mirroring `DirectusForceDashboard.vue`/`StandaloneForceDashboard.vue`'s existing pattern (`setForceHost(...)` then render)

- [ ] **Step 1: Export the new public API**

Add to `packages/force-plotting/src/index.ts`:

```typescript
export { default as DiagnosticsWorkbench } from './DiagnosticsWorkbench.vue';
export { default as DiagOctreeView } from './DiagOctreeView.vue';
export { fetchD1an, parseD1an, D1AN_MAGIC } from './diagAttrs';
export type { DiagAttrs } from './diagAttrs';
export { workingSetFromD1an, matches, computeStats } from './selection';
export type { WorkingSet, Selection, SelectionStats } from './selection';
```

- [ ] **Step 2: Directus host wrapper**

`DirectusForceDashboard.vue` calls `setForceHost(...)` once, at module scope, per component instance — but `setForceHost` is a *module-level singleton* (see `host.ts`'s comment: "A module-level singleton rather than Vue provide/inject"). If both `DirectusForceDashboard` and this new wrapper are ever mounted in the same page, the second `setForceHost` call silently overwrites the first with identical values (both set the same host shape) — safe, but worth knowing rather than being surprised by. This wrapper needs `operationId`/`diagPath`/`diagMetrics`/`totalPoints` from wherever the surrounding admin page determines the current operation — passed in as props, not fetched here, matching this task's Interfaces contract for `DiagnosticsWorkbench` itself.

```vue
<script setup lang="ts">
import { useApi, useStores } from '@directus/extensions-sdk';
import { useRouter } from 'vue-router';
import { DiagnosticsWorkbench, setForceHost } from '@d1/force-plotting';

const props = defineProps<{
	diagPath: string;
	diagMetrics: Record<string, unknown> | null;
	totalPoints: number;
}>();

const api = useApi();
const router = useRouter();
const { useUserStore } = useStores();
const userStore = useUserStore();

setForceHost({
	api,
	currentUser: () => userStore.currentUser,
	filterUrl: '/filter',
	octreeUrl: `${window.location.origin}/octrees`,
	authHeaders: () => ({}),
	fetchCredentials: 'include',
	openRecord: (collection, id) => { router.push(`/content/${collection}/${id}`); },
	downloadAsset: async (fileId) => {
		const a = document.createElement('a');
		a.href = `/assets/${fileId}?download`;
		a.rel = 'noopener';
		document.body.appendChild(a); a.click(); a.remove();
	},
	dense: false,
});
</script>

<template>
	<DiagnosticsWorkbench :diag-path="props.diagPath" :diag-metrics="props.diagMetrics" :total-points="props.totalPoints" />
</template>
```

- [ ] **Step 3: Standalone host wrapper**

```vue
<script setup lang="ts">
import { DiagnosticsWorkbench, setForceHost } from '@d1/force-plotting';
import { api, authHeaders } from '../directusClient';
import { authStore } from '../authStore';
import { getConfig } from '../config';

const props = defineProps<{
	diagPath: string;
	diagMetrics: Record<string, unknown> | null;
	totalPoints: number;
}>();

setForceHost({
	api,
	currentUser: () => authStore.currentUser.value,
	get filterUrl() { return getConfig().filterUrl; },
	get octreeUrl() { return getConfig().octreeUrl; },
	authHeaders,
	fetchCredentials: 'omit',
	openRecord: (collection, id) => {
		window.open(`${getConfig().directusUrl}/admin/content/${collection}/${id}`, '_blank', 'noopener');
	},
	downloadAsset: async (fileId) => {
		try {
			const res = await api.get(`/assets/${fileId}`, { params: { download: '' }, responseType: 'blob' });
			const url = URL.createObjectURL(res.data as Blob);
			const a = document.createElement('a');
			a.href = url; a.download = String(fileId);
			document.body.appendChild(a); a.click(); a.remove();
			setTimeout(() => URL.revokeObjectURL(url), 10_000);
		} catch { /* best-effort */ }
	},
	dense: true,
});
</script>

<template>
	<DiagnosticsWorkbench :diag-path="props.diagPath" :diag-metrics="props.diagMetrics" :total-points="props.totalPoints" />
</template>
```

Neither wrapper is routed/linked from anywhere yet — that's a real product decision (where does a user navigate from to reach this?) outside this plan's scope. Leaving them unrouted but present and typechecked is the correct stopping point for Phase 2; wiring a route/nav entry is a follow-up task once there's a real diag octree to point it at.

- [ ] **Step 4: Typecheck everything touched**

Run: `cd packages/force-plotting && npx vue-tsc --noEmit`
Run: `cd core/extensions/d1-force-dashboard && npx vue-tsc --noEmit` (if this extension has its own tsconfig; otherwise confirm via `npm run build -w directus-extension-d1-force-dashboard` per the root `package.json`'s `build:extension` script)
Run: `cd apps/force-app/web && npx vue-tsc --noEmit`
Expected: no errors in any of the three

- [ ] **Step 5: Run the full package test suite**

Run: `cd packages/force-plotting && npx vitest run`
Expected: all tests pass, including the new `diagAttrs.test.ts` (5) and `selection.test.ts` (10) alongside the existing suite

- [ ] **Step 6: Commit**

```bash
git add packages/force-plotting/src/index.ts core/extensions/d1-force-dashboard/src/DirectusDiagnosticsWorkbench.vue apps/force-app/web/src/force/StandaloneDiagnosticsWorkbench.vue
git commit -m "feat(force-plotting): export DiagnosticsWorkbench and add per-host wrappers"
```

---

## Self-Review Notes

**Spec coverage:** Component 6's WorkingSet (≥5M floor) — Phase 1's pipeline output is already at that order of magnitude; no additional decimation logic was added in this plan, matching the spec's note that D1AN is already sized appropriately. Component 6's three selection kinds — all three types exist in `selection.ts` (Task 3); only `lasso`'s GPU rendering is deferred (Task 4, explicitly noted), its JS-side predicate and stats are not. Component 7's layout — `GridLayout`/`GridItem` per the existing pattern, `WorkbenchPanel` chrome, Selection Inspector, bandwidth strip all present. Component 5's "browser computes nothing" principle — `DiagOctreeView`'s selection highlighting is GPU-evaluated per-vertex, matching this exactly.

**Known gap carried forward, not silently dropped:** the lasso selection's polygon test has no shader implementation (Task 4, Step 3's note) — spatial-lasso drawing UI and its GPU highlight are both explicitly deferred to "Phase 2.5" in the File Structure table, not forgotten.

**Type consistency check:** `Selection`'s `column: 'residZ' | 'tsaResid'` (Task 3) matches `DiagOctreeView`'s `uSelAttrChannel` mapping (`residZ` → 0, `tsaResid` → 1, Task 4 Step 3) and `SelectionInspector`'s `meanResidZ` field naming (Task 6) — all three agree on camelCase `residZ`/`tsaResid`, distinct from the D1AN file's own snake_case `resid_z`/`tsa_resid` column names, which only `diagAttrs.ts`/`selection.ts`'s `workingSetFromD1an` ever see.
