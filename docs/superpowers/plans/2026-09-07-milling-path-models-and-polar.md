# Milling Path Models & Polar Plot Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the hardcoded turning spiral in the force-app's point-cloud visualiser with a
pluggable path-model seam, add spindle-angle derivation and the rotating→fixed frame transform,
plumb torque (Mz) through the channel model, and ship a live polar-plot panel — without changing
one bit of today's turning/FRM output.

**Architecture:** Three new pure TypeScript modules (`path.ts`, `angle.ts`, `polar.ts`) sit between
the parsed `Cache` and `buildCloud`. `buildCloud` is refactored to consume a `PathResult` instead
of computing positions itself, and `Cloud.pos` becomes stride-3. The D1LC cache format gains an
additive v2 trailer (Mz/X/Y/Z), the backend channel model gains a rotating-dyno preset, and a new
`PolarPlot.vue` + `PolarPanel.vue` render torque-vs-angle as a live Record panel with pop-out.

**Tech Stack:** TypeScript/Vue 3 (`packages/force-plotting`, `apps/force-app/web`), Python/FastAPI
(`apps/force-app/backend`), Vitest, pytest.

**Spec:** `docs/superpowers/specs/2026-09-07-milling-path-models-and-polar-design.md`

## Global Constraints

- **No assertion in `packages/force-plotting/src/liveCloud.test.ts`,
  `packages/force-plotting/src/liveCache.test.ts`, or `apps/force-app/desktop/tests/*.spec.ts` may
  be weakened, deleted, or edited to match new behaviour.** Only the `makeCache()`/`baseParams()`
  helpers in `liveCloud.test.ts` may change shape; their expectations do not.
- `turning_spiral` is the default path model; a capture with no path configuration renders exactly
  as it does today.
- D1LC v1 files parse to today's exact `Cache`; v2 is written only when extras are non-empty.
- `FrmCloud.vue`'s existing prop surface (`axis`, `feed`, `diam`, …) is unchanged; `axis` becomes a
  deprecated alias for `channel`.
- `to_record_channels` refuses a rotating-dyno config rather than mis-mapping it into the
  stationary 9-column layout.
- Every new pure module is unit-testable against fabricated `Float32Array`s — no cache file, no
  hardware.
- `npm run test --workspaces` and `npm run typecheck --workspaces` (from repo root) plus backend
  `pytest` must be green before any task is considered done.

---

## File Structure

| File | Responsibility |
|---|---|
| `packages/force-plotting/src/liveCloud.golden.test.ts` (new) | Pre-refactor characterisation snapshot of today's `buildCloud`. |
| `packages/force-plotting/src/path.ts` (new) | `buildPath`: turning-spiral / linear-feed / machine-xyz position generation, stride-3, index-tracked. |
| `packages/force-plotting/src/path.test.ts` (new) | Unit tests for `buildPath`. |
| `packages/force-plotting/src/angle.ts` (new) | `spindleAngle`, `toFixedFrame`, `AngleSourceUnavailableError`. |
| `packages/force-plotting/src/angle.test.ts` (new) | Unit tests for angle derivation and the frame transform. |
| `packages/force-plotting/src/polar.ts` (new) | `buildPolar`: (r, φ) pairs from a `Cache`. |
| `packages/force-plotting/src/polar.test.ts` (new) | Unit tests for `buildPolar`, including the 4-lobe check. |
| `packages/force-plotting/src/liveCloud.ts` (modify) | `buildCloud` refactored to positions×colours; `CloudChannel`; `gridCloud` keeps Z. |
| `packages/force-plotting/src/liveCloud.test.ts` (modify, additive) | Helpers adapted to new `CloudParams`; existing expectations preserved; new stride-3/grid-Z cases added. |
| `packages/force-plotting/src/FrmCloud.vue` (modify) | Consumes stride-3 `pos`/`bounds`; new optional `path`/`channel` props; `axis` alias kept. |
| `packages/force-plotting/src/frmExport.ts` | **No change** — confirmed during implementation (Task 4 Step 6): it builds its own `{xmin,xmax,ymin,ymax}` object from `fitCx`/`fitSpan` in `FrmCloud.vue`, never touches `Cloud.bounds` directly. |
| `packages/force-plotting/src/liveCache.ts` (modify) | D1LC v2 trailer parsing; `version` field; `decimateCache` extended. |
| `packages/force-plotting/src/liveCache.test.ts` (modify, additive) | v1 exactness test kept; v2 trailer tests added. |
| `packages/force-plotting/src/PolarPlot.vue` (new) | Canvas-2D polar renderer. |
| `packages/force-plotting/src/index.ts` (modify) | Export the new modules/components. |
| `apps/force-app/backend/app/d1lc.py` (modify) | `write_d1lc` gains optional `extras`; writes v2 only when non-empty. |
| `apps/force-app/backend/app/channels.py` (modify) | `Mz`/`Index` roles, `rotating_4` preset, N·m/V gain field, `to_record_channels` refusal. |
| `apps/force-app/backend/tests/test_channels.py` (new) | Backend channel-model tests. |
| `apps/force-app/backend/tests/test_d1lc.py` (new) | `write_d1lc` byte-identity + extras round-trip. |
| `apps/force-app/web/src/record/panels/PolarPanel.vue` (new) | Record-page polar panel, mirrors `FrmPanel.vue`. |
| `apps/force-app/web/src/record/RecordPage.vue` (modify) | Register the `polar` panel type. |
| `apps/force-app/web/src/record/LivePanelWindow.vue` (modify) | `polar` branch for the pop-out window. |
| `apps/force-app/web/src/record/workspace.ts` (modify) | `plot.polarRadius`/`polarAngleSource`/`polarBins`. |
| `docs/hardware/rotating-dynamometer.md` (new) | Manual-derived reference constants. |

---

## Task 0: Characterisation goldens (no production code changes)

**Files:**
- Create: `packages/force-plotting/src/liveCloud.golden.test.ts`

**Interfaces:**
- Consumes: today's `buildCloud`, `CloudParams`, `COLORMAPS` from `./liveCloud` (unchanged signatures).
- Produces: a committed Vitest snapshot fixture (`__snapshots__/liveCloud.golden.test.ts.snap`) that
  Task 6 (the `buildCloud` refactor) must reproduce.

- [ ] **Step 1: Write the golden test**

```ts
// packages/force-plotting/src/liveCloud.golden.test.ts
//
// Characterisation test, written BEFORE the path-model refactor (see
// docs/superpowers/specs/2026-09-07-milling-path-models-and-polar-design.md,
// "Protecting what works today"). It pins today's exact buildCloud() output across a
// representative parameter matrix. The refactored buildPath()+buildCloud() MUST
// reproduce these values exactly (x/y agree; the new stride-3 pos carries z=0).
// DO NOT edit the committed snapshot file to make a later change pass — a snapshot
// diff here means the refactor changed geometry, which is exactly what this guards.
import { describe, expect, it } from 'vitest';
import { buildCloud, COLORMAPS, type CloudParams } from './liveCloud';
import type { Cache } from './liveCache';

function makeCache(): Cache {
	const N = 60;
	const t = Float32Array.from({ length: N }, (_, i) => i * 0.01);
	const revs = Float32Array.from({ length: N }, (_, i) => i * 0.03);
	const mk = (f: (i: number) => number) => Float32Array.from({ length: N }, (_, i) => f(i));
	return {
		N, Fs: 1000, feed: 0.05, diam: 80, csSec: 0, ceSec: (N - 1) * 0.01,
		t, revs,
		Fx: mk((i) => Math.sin(i * 0.2) * 30),
		Fy: mk((i) => Math.cos(i * 0.2) * 30),
		Fz: mk((i) => Math.sin(i * 0.31) * 50 + 10),
		rpm: mk(() => 1200),
	};
}

function baseParams(overrides: Partial<CloudParams> = {}): CloudParams {
	return {
		axis: 'Fz', feed: 0.05, diam: 80, innerDiam: 0, speedMode: 'measured',
		rpm: 1200, vc: 0, timeScale: 1, ppr: 1,
		cropStartSec: 0, cropEndSec: 1e9,
		stride: 1, gridding: false, gridN: 20,
		colormap: COLORMAPS.viridis,
		cmin: null, cmax: null, zSeries: 'none',
		...overrides,
	};
}

// Each case name documents which axis of the matrix it exercises.
const CASES: [string, Partial<CloudParams>][] = [
	['measured-raw', {}],
	['rpm-model', { speedMode: 'rpm', rpm: 900 }],
	['vc-model', { speedMode: 'vc', vc: 120 }],
	['gridded', { gridding: true, gridN: 12 }],
	['stride-5', { stride: 5 }],
	['inner-diam-20', { innerDiam: 20 }],
	['z-series-fx', { zSeries: 'Fx' }],
	['truncating-crop', { cropStartSec: 0.1, cropEndSec: 0.3 }],
	['manual-climits', { cmin: -10, cmax: 10 }],
];

describe('buildCloud golden values (pre-refactor characterisation)', () => {
	const cache = makeCache();
	for (const [name, overrides] of CASES) {
		it(`matches the frozen snapshot: ${name}`, () => {
			const cloud = buildCloud(cache, baseParams(overrides));
			expect(cloud).not.toBeNull();
			expect({
				count: cloud!.count,
				pos: Array.from(cloud!.pos),
				col: Array.from(cloud!.col),
				bounds: [cloud!.minX, cloud!.maxX, cloud!.minY, cloud!.maxY],
				climits: [cloud!.cmin, cloud!.cmax],
				zv: cloud!.zv ? Array.from(cloud!.zv) : null,
			}).toMatchSnapshot();
		});
	}
});
```

- [ ] **Step 2: Run it to generate and commit the snapshot**

Run: `npm run test -w @d1/force-plotting -- liveCloud.golden`
Expected: 9 passed (first run writes `packages/force-plotting/src/__snapshots__/liveCloud.golden.test.ts.snap`).

- [ ] **Step 3: Commit**

```bash
git add packages/force-plotting/src/liveCloud.golden.test.ts packages/force-plotting/src/__snapshots__/liveCloud.golden.test.ts.snap
git commit -m "test(force-plotting): freeze today's buildCloud output before the path-model refactor"
```

---

## Task 1: `path.ts` — the path-model seam

**Files:**
- Create: `packages/force-plotting/src/path.ts`
- Test: `packages/force-plotting/src/path.test.ts`

**Interfaces:**
- Consumes: `Cache` from `./liveCache` (existing shape; `Mz`/`X`/`Y`/`Z` fields added in Task 5 are
  read here as `c.X`/`c.Y`/`c.Z`, typed optional).
- Produces: `PathKind`, `SpeedMode`, `PathWindow`, `TurningSpiralParams`, `LinearFeedParams`,
  `MachineXyzParams`, `PathParams`, `PathBounds`, `PathResult`, `buildPath(c, p, w)`. Task 3
  (`buildCloud` refactor) and Task 4 (`angle.ts`) both import from here.

- [ ] **Step 1: Write the failing tests**

```ts
// packages/force-plotting/src/path.test.ts
import { describe, expect, it } from 'vitest';
import { buildPath, type Cache as _Cache } from './path';
import type { Cache } from './liveCache';

function makeCache(overrides: Partial<Cache> = {}): Cache {
	const N = overrides.N ?? 50;
	const t = overrides.t ?? Float32Array.from({ length: N }, (_, i) => i * 0.01);
	const revs = overrides.revs ?? Float32Array.from({ length: N }, (_, i) => i * 0.02);
	return {
		N, Fs: 1000, feed: 0.05, diam: 80, csSec: 0, ceSec: (N - 1) * 0.01,
		t, revs,
		Fx: overrides.Fx ?? Float32Array.from({ length: N }, () => 1),
		Fy: overrides.Fy ?? Float32Array.from({ length: N }, () => 1),
		Fz: overrides.Fz ?? Float32Array.from({ length: N }, () => 1),
		rpm: overrides.rpm ?? Float32Array.from({ length: N }, () => 1200),
		...overrides,
	};
}
const WINDOW = { cropStartSec: 0, cropEndSec: 1e9, stride: 1 };

describe('buildPath / turning_spiral', () => {
	it('spirals inward and stops at innerDiam', () => {
		const c = makeCache();
		const r = buildPath(c, {
			kind: 'turning_spiral', feed: 1, diam: 80, innerDiam: 20,
			speedMode: 'measured', rpm: 0, vc: 0, timeScale: 1, ppr: 1,
		}, WINDOW);
		expect(r).not.toBeNull();
		expect(r!.count).toBeGreaterThan(0);
		expect(r!.count).toBeLessThan(c.N);   // the innerDiam break must cut it short
		expect(r!.pos.length).toBe(r!.count * 3);
		for (let k = 0; k < r!.count; k++) expect(r!.pos[k * 3 + 2]).toBe(0);   // z=0
	});

	it('idx maps each emitted point back to its source sample', () => {
		const c = makeCache({ N: 20 });
		const r = buildPath(c, {
			kind: 'turning_spiral', feed: 0.05, diam: 80, innerDiam: 0,
			speedMode: 'measured', rpm: 0, vc: 0, timeScale: 1, ppr: 1,
		}, { cropStartSec: 0, cropEndSec: 1e9, stride: 3 });
		expect(r).not.toBeNull();
		expect(r!.idx.length).toBe(r!.count);
		for (let k = 1; k < r!.count; k++) expect(r!.idx[k]).toBe(r!.idx[k - 1] + 3);
	});

	it('rpm speed model advances angle linearly in time', () => {
		const c = makeCache({ N: 100 });
		const r = buildPath(c, {
			kind: 'turning_spiral', feed: 0, diam: 80, innerDiam: 0,
			speedMode: 'rpm', rpm: 600, vc: 0, timeScale: 1, ppr: 1,
		}, WINDOW);
		expect(r).not.toBeNull();
		// feed=0 => radius is constant => positions trace a circle of radius 40.
		for (let k = 0; k < r!.count; k++) {
			const x = r!.pos[k * 3], y = r!.pos[k * 3 + 1];
			expect(Math.hypot(x, y)).toBeCloseTo(40, 4);
		}
	});

	it('vc speed model shrinks radius per the K coefficient', () => {
		const c = makeCache({ N: 100 });
		const r = buildPath(c, {
			kind: 'turning_spiral', feed: 0.1, diam: 80, innerDiam: 0,
			speedMode: 'vc', rpm: 0, vc: 120, timeScale: 1, ppr: 1,
		}, WINDOW);
		expect(r).not.toBeNull();
		const rad0 = Math.hypot(r!.pos[0], r!.pos[1]);
		const radLast = Math.hypot(r!.pos[(r!.count - 1) * 3], r!.pos[(r!.count - 1) * 3 + 1]);
		expect(radLast).toBeLessThan(rad0);
	});
});

describe('buildPath / linear_feed', () => {
	it('advances x at feedRate mm/min, holds y and z constant', () => {
		const c = makeCache({ N: 601, t: Float32Array.from({ length: 601 }, (_, i) => i * 0.01) }); // 6s
		const r = buildPath(c, {
			kind: 'linear_feed', feedRate: 100, timeScale: 1, yOffset: 5, zOffset: -2,
		}, WINDOW);
		expect(r).not.toBeNull();
		expect(r!.pos[0]).toBeCloseTo(0, 5);
		const lastX = r!.pos[(r!.count - 1) * 3];
		expect(lastX).toBeCloseTo(10, 1); // 100 mm/min * 6s/60 = 10mm
		for (let k = 0; k < r!.count; k++) {
			expect(r!.pos[k * 3 + 1]).toBeCloseTo(5, 6);
			expect(r!.pos[k * 3 + 2]).toBeCloseTo(-2, 6);
		}
	});
});

describe('buildPath / machine_xyz', () => {
	it('zeroes the start under first_sample origin', () => {
		const N = 10;
		const c = makeCache({
			N,
			X: Float32Array.from({ length: N }, (_, i) => 10 + i),
			Y: Float32Array.from({ length: N }, (_, i) => 5 - i * 0.5),
			Z: Float32Array.from({ length: N }, () => 1),
		} as Partial<Cache>);
		const r = buildPath(c, {
			kind: 'machine_xyz', xKey: 'X', yKey: 'Y', zKey: 'Z', scale: 1, origin: 'first_sample',
		}, WINDOW);
		expect(r).not.toBeNull();
		expect(r!.pos[0]).toBeCloseTo(0, 6);
		expect(r!.pos[1]).toBeCloseTo(0, 6);
		expect(r!.pos[2]).toBeCloseTo(0, 6);
	});

	it('keeps absolute coordinates under origin=absolute', () => {
		const N = 5;
		const c = makeCache({ N, X: Float32Array.from({ length: N }, () => 42) } as Partial<Cache>);
		const r = buildPath(c, {
			kind: 'machine_xyz', xKey: 'X', yKey: 'X', zKey: 'X', scale: 1, origin: 'absolute',
		}, WINDOW);
		expect(r!.pos[0]).toBeCloseTo(42, 6);
	});

	it('returns null when a named array is missing', () => {
		const c = makeCache({ N: 5 });
		const r = buildPath(c, {
			kind: 'machine_xyz', xKey: 'X', yKey: 'Y', zKey: 'Z', scale: 1, origin: 'absolute',
		}, WINDOW);
		expect(r).toBeNull();
	});

	it('returns null when a named array has the wrong length', () => {
		const c = makeCache({ N: 5, X: Float32Array.from({ length: 3 }, () => 1) } as Partial<Cache>);
		const r = buildPath(c, {
			kind: 'machine_xyz', xKey: 'X', yKey: 'X', zKey: 'X', scale: 1, origin: 'absolute',
		}, WINDOW);
		expect(r).toBeNull();
	});
});

describe('buildPath / degenerate input', () => {
	it('returns null for an empty cache', () => {
		const c = makeCache({ N: 0, t: new Float32Array(0), revs: new Float32Array(0) });
		const r = buildPath(c, {
			kind: 'turning_spiral', feed: 0.05, diam: 80, innerDiam: 0,
			speedMode: 'measured', rpm: 0, vc: 0, timeScale: 1, ppr: 1,
		}, WINDOW);
		expect(r).toBeNull();
	});

	it('returns null when the crop selects nothing', () => {
		const c = makeCache({ N: 20 });
		const r = buildPath(c, {
			kind: 'turning_spiral', feed: 0.05, diam: 80, innerDiam: 0,
			speedMode: 'measured', rpm: 0, vc: 0, timeScale: 1, ppr: 1,
		}, { cropStartSec: 1000, cropEndSec: 2000, stride: 1 });
		expect(r).toBeNull();
	});
});
```

Note: `Cache` here is imported from `./liveCache`, which does not yet declare `X`/`Y`/`Z` (that
lands in Task 5). Cast the `machine_xyz` test fixtures with `as Partial<Cache>` as shown — this
keeps Task 1 independent of Task 5's cache-format change, exactly as the sequencing requires.

- [ ] **Step 2: Run tests to verify they fail**

Run: `npm run test -w @d1/force-plotting -- path.test`
Expected: FAIL — `path.ts` does not exist yet.

- [ ] **Step 3: Implement `path.ts`**

```ts
// packages/force-plotting/src/path.ts
//
// The tool-path seam: turns a Cache + parameters into a stride-3 array of positions.
// Extracted so the geometry that used to be hardwired into buildCloud() (a turning
// spiral) is one of three interchangeable models. See
// docs/superpowers/specs/2026-09-07-milling-path-models-and-polar-design.md §1.
import type { Cache } from './liveCache';

export type PathKind = 'turning_spiral' | 'linear_feed' | 'machine_xyz';
export type SpeedMode = 'measured' | 'rpm' | 'vc';

export interface PathWindow {
	cropStartSec: number;
	cropEndSec: number;
	stride: number;
}

export interface TurningSpiralParams {
	kind: 'turning_spiral';
	feed: number;
	diam: number;
	innerDiam: number;
	speedMode: SpeedMode;
	rpm: number;
	vc: number;
	timeScale: number;
	ppr: number;
}

export interface LinearFeedParams {
	kind: 'linear_feed';
	feedRate: number;   // mm/min along +X
	timeScale: number;
	yOffset: number;
	zOffset: number;
}

export interface MachineXyzParams {
	kind: 'machine_xyz';
	xKey: 'X' | 'Y' | 'Z';
	yKey: 'X' | 'Y' | 'Z';
	zKey: 'X' | 'Y' | 'Z';
	scale: number;
	origin: 'first_sample' | 'absolute';
}

export type PathParams = TurningSpiralParams | LinearFeedParams | MachineXyzParams;

export interface PathBounds {
	minX: number; maxX: number;
	minY: number; maxY: number;
	minZ: number; maxZ: number;
}

export interface PathResult {
	pos: Float32Array;   // stride 3
	idx: Int32Array;
	count: number;
	bounds: PathBounds;
}

// Same binary search as liveCloud.ts's idxOfTime: first index with t[i] >= sec.
function idxOfTime(t: Float32Array, sec: number): number {
	if (t.length === 0) return -1;
	let lo = 0, hi = t.length - 1, ans = t.length - 1;
	while (lo <= hi) { const m = (lo + hi) >> 1; if (t[m] >= sec) { ans = m; hi = m - 1; } else lo = m + 1; }
	return ans;
}

function emptyBounds(): PathBounds {
	return { minX: 0, maxX: 0, minY: 0, maxY: 0, minZ: 0, maxZ: 0 };
}

export function buildPath(c: Cache, p: PathParams, w: PathWindow): PathResult | null {
	const t = c.t;
	if (!t || t.length === 0 || c.N === 0) return null;
	const cs = idxOfTime(t, w.cropStartSec);
	if (cs < 0) return null;
	const stride = Math.max(1, Math.round(w.stride) || 1);

	if (p.kind === 'turning_spiral') return buildTurningSpiral(c, p, w, cs, stride);
	if (p.kind === 'linear_feed') return buildLinearFeed(c, p, w, cs, stride);
	return buildMachineXyz(c, p, w, cs, stride);
}

function buildTurningSpiral(
	c: Cache, p: TurningSpiralParams, w: PathWindow, cs: number, stride: number,
): PathResult | null {
	const t = c.t, revs = c.revs;
	const F = p.feed, rho0 = p.diam / 2;
	const innerR = Math.max(0, (p.innerDiam || 0) / 2);
	const revsCs = revs[cs], tCs = t[cs];
	const revPerSec = p.rpm / 60;
	const ts = p.timeScale > 0 ? p.timeScale : 1;
	const ppr = p.ppr > 0 ? p.ppr : 1;
	const K = F * p.vc * 1000 / (Math.PI * 120);

	const cap = Math.max(1, Math.ceil((c.N - cs) / stride) + 1);
	const pos = new Float32Array(cap * 3);
	const idx = new Int32Array(cap);
	let m = 0;
	let minX = Infinity, maxX = -Infinity, minY = Infinity, maxY = -Infinity;
	for (let i = cs; i < c.N; i += stride) {
		if (t[i] > w.cropEndSec) break;
		let r: number, rho: number;
		if (p.speedMode === 'vc') {
			const under = rho0 * rho0 - 2 * K * (t[i] - tCs) * ts;
			if (under < innerR * innerR) break;
			rho = Math.sqrt(under);
			r = (rho0 - rho) / F;
		} else {
			r = p.speedMode === 'rpm' ? revPerSec * (t[i] - tCs) * ts : (revs[i] - revsCs) / ppr;
			rho = rho0 - F * r;
			if (rho < innerR) break;
		}
		const theta = 2 * Math.PI * r;
		const x = rho * Math.cos(theta), y = rho * Math.sin(theta);
		pos[m * 3] = x; pos[m * 3 + 1] = y; pos[m * 3 + 2] = 0;
		idx[m] = i;
		m++;
		if (x < minX) minX = x; if (x > maxX) maxX = x;
		if (y < minY) minY = y; if (y > maxY) maxY = y;
	}
	if (!m) return null;
	return {
		pos: pos.subarray(0, m * 3), idx: idx.subarray(0, m), count: m,
		bounds: { minX, maxX, minY, maxY, minZ: 0, maxZ: 0 },
	};
}

function buildLinearFeed(
	c: Cache, p: LinearFeedParams, w: PathWindow, cs: number, stride: number,
): PathResult | null {
	const t = c.t;
	const ts = p.timeScale > 0 ? p.timeScale : 1;
	const vPerSec = p.feedRate / 60;   // mm/s
	const tCs = t[cs];
	const cap = Math.max(1, Math.ceil((c.N - cs) / stride) + 1);
	const pos = new Float32Array(cap * 3);
	const idx = new Int32Array(cap);
	let m = 0;
	let minX = Infinity, maxX = -Infinity;
	for (let i = cs; i < c.N; i += stride) {
		if (t[i] > w.cropEndSec) break;
		const x = vPerSec * (t[i] - tCs) * ts;
		pos[m * 3] = x; pos[m * 3 + 1] = p.yOffset; pos[m * 3 + 2] = p.zOffset;
		idx[m] = i;
		m++;
		if (x < minX) minX = x; if (x > maxX) maxX = x;
	}
	if (!m) return null;
	return {
		pos: pos.subarray(0, m * 3), idx: idx.subarray(0, m), count: m,
		bounds: { minX, maxX, minY: p.yOffset, maxY: p.yOffset, minZ: p.zOffset, maxZ: p.zOffset },
	};
}

function buildMachineXyz(
	c: Cache, p: MachineXyzParams, w: PathWindow, cs: number, stride: number,
): PathResult | null {
	const src = { X: (c as any).X, Y: (c as any).Y, Z: (c as any).Z } as Record<string, Float32Array | undefined>;
	const xs = src[p.xKey], ys = src[p.yKey], zs = src[p.zKey];
	if (!xs || !ys || !zs) return null;
	if (xs.length !== c.N || ys.length !== c.N || zs.length !== c.N) return null;

	const t = c.t;
	const ox = p.origin === 'first_sample' ? xs[cs] : 0;
	const oy = p.origin === 'first_sample' ? ys[cs] : 0;
	const oz = p.origin === 'first_sample' ? zs[cs] : 0;
	const cap = Math.max(1, Math.ceil((c.N - cs) / stride) + 1);
	const pos = new Float32Array(cap * 3);
	const idx = new Int32Array(cap);
	let m = 0;
	let minX = Infinity, maxX = -Infinity, minY = Infinity, maxY = -Infinity, minZ = Infinity, maxZ = -Infinity;
	for (let i = cs; i < c.N; i += stride) {
		if (t[i] > w.cropEndSec) break;
		const x = (xs[i] - ox) * p.scale, y = (ys[i] - oy) * p.scale, z = (zs[i] - oz) * p.scale;
		pos[m * 3] = x; pos[m * 3 + 1] = y; pos[m * 3 + 2] = z;
		idx[m] = i;
		m++;
		if (x < minX) minX = x; if (x > maxX) maxX = x;
		if (y < minY) minY = y; if (y > maxY) maxY = y;
		if (z < minZ) minZ = z; if (z > maxZ) maxZ = z;
	}
	if (!m) return null;
	return { pos: pos.subarray(0, m * 3), idx: idx.subarray(0, m), count: m, bounds: { minX, maxX, minY, maxY, minZ, maxZ } };
}
```

Note: `buildPath` currently reads `Mz`/`X`/`Y`/`Z` via `(c as any)` because Task 5 (the D1LC v2
`Cache` type widening) has not run yet in the sequence. When Task 5 lands, come back and change
the three `(c as any)` casts in `buildMachineXyz` to plain `c.X`/`c.Y`/`c.Z` now that they are
real optional fields on `Cache` — this is a one-line cleanup, tracked here so it isn't forgotten.

- [ ] **Step 4: Run tests to verify they pass**

Run: `npm run test -w @d1/force-plotting -- path.test`
Expected: PASS (14 tests)

- [ ] **Step 5: Commit**

```bash
git add packages/force-plotting/src/path.ts packages/force-plotting/src/path.test.ts
git commit -m "feat(force-plotting): path.ts -- turning_spiral/linear_feed/machine_xyz seam"
```

---

## Task 2: `angle.ts` — spindle angle and the fixed-frame transform

**Files:**
- Create: `packages/force-plotting/src/angle.ts`
- Test: `packages/force-plotting/src/angle.test.ts`

**Interfaces:**
- Consumes: `Cache` from `./liveCache`.
- Produces: `AngleSource`, `AngleParams`, `AngleSourceUnavailableError`, `spindleAngle(c, p, idx, out)`,
  `FixedFrame`, `toFixedFrame(fx, fy, phi, idx)`. Task 3 (`polar.ts`) and the follow-up derived-Ff/FfN
  channel both import from here.

- [ ] **Step 1: Write the failing tests**

```ts
// packages/force-plotting/src/angle.test.ts
import { describe, expect, it } from 'vitest';
import { spindleAngle, toFixedFrame, AngleSourceUnavailableError, type AngleParams } from './angle';
import type { Cache } from './liveCache';

function makeCache(overrides: Partial<Cache> = {}): Cache {
	const N = overrides.N ?? 40;
	return {
		N, Fs: 1000, feed: 0.05, diam: 80, csSec: 0, ceSec: (N - 1) * 0.01,
		t: overrides.t ?? Float32Array.from({ length: N }, (_, i) => i * 0.01),
		revs: overrides.revs ?? Float32Array.from({ length: N }, (_, i) => i * 0.075), // 3 revs total
		Fx: overrides.Fx ?? Float32Array.from({ length: N }, () => 1),
		Fy: overrides.Fy ?? Float32Array.from({ length: N }, () => 1),
		Fz: overrides.Fz ?? Float32Array.from({ length: N }, () => 1),
		rpm: overrides.rpm ?? Float32Array.from({ length: N }, () => 1200),
		...overrides,
	};
}
function baseAngleParams(overrides: Partial<AngleParams> = {}): AngleParams {
	return { source: 'tacho', ppr: 1, offsetDeg: 0, direction: 1, engagementN: 5, ...overrides };
}
const wrap2pi = (x: number) => ((x % (2 * Math.PI)) + 2 * Math.PI) % (2 * Math.PI);

describe('spindleAngle / tacho', () => {
	it('produces a monotonic sawtooth in [0, 2*PI) across 3 revolutions', () => {
		const c = makeCache({ N: 30, revs: Float32Array.from({ length: 30 }, (_, i) => i * 0.1) }); // 3 revs
		const idx = Int32Array.from({ length: 30 }, (_, i) => i);
		const out = new Float32Array(30);
		spindleAngle(c, baseAngleParams(), idx, out);
		for (const v of out) { expect(v).toBeGreaterThanOrEqual(0); expect(v).toBeLessThan(2 * Math.PI); }
		// three full cycles => at least two wrap-arounds (angle drops sharply then climbs again)
		let wraps = 0;
		for (let i = 1; i < out.length; i++) if (out[i] < out[i - 1] - Math.PI) wraps++;
		expect(wraps).toBeGreaterThanOrEqual(2);
	});

	it('ppr divides the raw revs_cum', () => {
		const c = makeCache({ N: 10, revs: Float32Array.from({ length: 10 }, (_, i) => i * 0.2) });
		const idx = Int32Array.from({ length: 10 }, (_, i) => i);
		const out1 = new Float32Array(10), out2 = new Float32Array(10);
		spindleAngle(c, baseAngleParams({ ppr: 1 }), idx, out1);
		spindleAngle(c, baseAngleParams({ ppr: 2 }), idx, out2);
		expect(wrap2pi(out2[5] * 2)).toBeCloseTo(wrap2pi(out1[5]), 4);
	});

	it('direction=-1 mirrors the angle', () => {
		const c = makeCache({ N: 10, revs: Float32Array.from({ length: 10 }, (_, i) => i * 0.05) });
		const idx = Int32Array.from({ length: 10 }, (_, i) => i);
		const fwd = new Float32Array(10), rev = new Float32Array(10);
		spindleAngle(c, baseAngleParams({ direction: 1 }), idx, fwd);
		spindleAngle(c, baseAngleParams({ direction: -1 }), idx, rev);
		for (let i = 0; i < 10; i++) expect(wrap2pi(fwd[i] + rev[i])).toBeCloseTo(0, 3) || expect(wrap2pi(fwd[i] + rev[i])).toBeCloseTo(2 * Math.PI, 3);
	});

	it('offsetDeg rotates the zero point', () => {
		const c = makeCache({ N: 5, revs: new Float32Array(5) });
		const idx = Int32Array.from({ length: 5 }, (_, i) => i);
		const out = new Float32Array(5);
		spindleAngle(c, baseAngleParams({ offsetDeg: 90 }), idx, out);
		expect(out[0]).toBeCloseTo(Math.PI / 2, 4);
	});
});

describe('spindleAngle / force_vector', () => {
	it('recovers the angle of a synthetic rotating force vector', () => {
		const N = 16;
		const Fx = new Float32Array(N), Fy = new Float32Array(N);
		const expected = new Float32Array(N);
		for (let i = 0; i < N; i++) {
			const phi = (i / N) * 2 * Math.PI;
			Fx[i] = 50 * Math.cos(phi); Fy[i] = 50 * Math.sin(phi);
			expected[i] = wrap2pi(phi);
		}
		const c = makeCache({ N, Fx, Fy });
		const idx = Int32Array.from({ length: N }, (_, i) => i);
		const out = new Float32Array(N);
		spindleAngle(c, baseAngleParams({ source: 'force_vector', engagementN: 5 }), idx, out);
		for (let i = 0; i < N; i++) expect(Math.abs(out[i] - expected[i])).toBeLessThan(1e-4);
	});

	it('emits NaN when |Fxy| is below the engagement threshold', () => {
		const N = 4;
		const c = makeCache({ N, Fx: new Float32Array(N).fill(0.01), Fy: new Float32Array(N).fill(0.01) });
		const idx = Int32Array.from({ length: N }, (_, i) => i);
		const out = new Float32Array(N);
		spindleAngle(c, baseAngleParams({ source: 'force_vector', engagementN: 5 }), idx, out);
		for (const v of out) expect(Number.isNaN(v)).toBe(true);
	});
});

describe('spindleAngle / index_pulse', () => {
	it('throws AngleSourceUnavailableError', () => {
		const c = makeCache({ N: 3 });
		const idx = Int32Array.from({ length: 3 }, (_, i) => i);
		const out = new Float32Array(3);
		expect(() => spindleAngle(c, baseAngleParams({ source: 'index_pulse' }), idx, out))
			.toThrow(AngleSourceUnavailableError);
	});
});

describe('toFixedFrame', () => {
	it('at phi=90deg, Ff=Fx and FfN=Fy (RCD 9170B Fig. 37)', () => {
		const fx = Float32Array.from([12]), fy = Float32Array.from([-7]);
		const phi = Float32Array.from([Math.PI / 2]);
		const idx = Int32Array.from([0]);
		const { Ff, FfN } = toFixedFrame(fx, fy, phi, idx);
		expect(Ff[0]).toBeCloseTo(12, 5);
		expect(FfN[0]).toBeCloseTo(-7, 5);
	});

	it('preserves magnitude at an arbitrary angle', () => {
		const fx = Float32Array.from([8]), fy = Float32Array.from([-3]);
		const phi = Float32Array.from([0.73]);
		const idx = Int32Array.from([0]);
		const { Ff, FfN } = toFixedFrame(fx, fy, phi, idx);
		const before = fx[0] ** 2 + fy[0] ** 2;
		const after = Ff[0] ** 2 + FfN[0] ** 2;
		expect(after).toBeCloseTo(before, 4);
	});
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `npm run test -w @d1/force-plotting -- angle.test`
Expected: FAIL — `angle.ts` does not exist yet.

- [ ] **Step 3: Implement `angle.ts`**

```ts
// packages/force-plotting/src/angle.ts
//
// Spindle angle derivation and the RCD rotating->fixed frame transform. See
// docs/superpowers/specs/2026-09-07-milling-path-models-and-polar-design.md §2.
import type { Cache } from './liveCache';

export type AngleSource = 'tacho' | 'force_vector' | 'index_pulse';

export interface AngleParams {
	source: AngleSource;
	ppr: number;
	offsetDeg: number;
	direction: 1 | -1;
	engagementN: number;
}

export class AngleSourceUnavailableError extends Error {
	constructor(public readonly source: AngleSource) {
		super(`angle source "${source}" is not implemented yet`);
		this.name = 'AngleSourceUnavailableError';
	}
}

const TWO_PI = 2 * Math.PI;
function wrap2pi(x: number): number { const m = x % TWO_PI; return m < 0 ? m + TWO_PI : m; }

/**
 * Spindle angle phi (radians, [0, 2*PI)) for each entry in `idx`, written into `out`.
 * `out` must be at least `idx.length` long. NaN marks "angle unknown at this sample".
 */
export function spindleAngle(c: Cache, p: AngleParams, idx: Int32Array, out: Float32Array): void {
	const offset = (p.offsetDeg * Math.PI) / 180;
	const ppr = p.ppr > 0 ? p.ppr : 1;

	if (p.source === 'index_pulse') throw new AngleSourceUnavailableError('index_pulse');

	if (p.source === 'tacho') {
		const revs = c.revs;
		const revs0 = revs[idx[0]] ?? 0;
		for (let k = 0; k < idx.length; k++) {
			const i = idx[k];
			const r = ((revs[i] - revs0) / ppr) * p.direction;
			out[k] = wrap2pi(r * TWO_PI + offset);
		}
		return;
	}

	// force_vector
	for (let k = 0; k < idx.length; k++) {
		const i = idx[k];
		const fx = c.Fx[i], fy = c.Fy[i];
		if (Math.hypot(fx, fy) < p.engagementN) { out[k] = NaN; continue; }
		const raw = Math.atan2(fy, fx) * p.direction;
		out[k] = wrap2pi(raw + offset);
	}
}

export interface FixedFrame { Ff: Float32Array; FfN: Float32Array }

/**
 * RCD 9170B §8.1.1: rotate the tool-frame radial forces Fx/Fy into the workpiece
 * (fixed) frame using the immersion angle phi. At phi=90deg the frames coincide
 * (Fig. 37): Ff=Fx, FfN=Fy.
 *
 * VERIFICATION DEBT: the sign convention and phi=0 reference depend on spindle
 * rotation sense and where the tool's reference edge sits relative to the
 * dynamometer's engraved X marking. This is a correct rotation; it has not been
 * checked against a real cut. `AngleParams.offsetDeg`/`direction` (upstream, in the
 * phi this consumes) exist to calibrate that without touching this formula.
 */
export function toFixedFrame(
	fx: Float32Array, fy: Float32Array, phi: Float32Array, idx: Int32Array,
): FixedFrame {
	const n = idx.length;
	const Ff = new Float32Array(n), FfN = new Float32Array(n);
	for (let k = 0; k < n; k++) {
		const i = idx[k];
		const s = Math.sin(phi[k]), co = Math.cos(phi[k]);
		Ff[k] = fx[i] * s + fy[i] * co;
		FfN[k] = -fx[i] * co + fy[i] * s;
	}
	return { Ff, FfN };
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `npm run test -w @d1/force-plotting -- angle.test`
Expected: PASS (9 tests)

- [ ] **Step 5: Commit**

```bash
git add packages/force-plotting/src/angle.ts packages/force-plotting/src/angle.test.ts
git commit -m "feat(force-plotting): angle.ts -- spindle angle sources + fixed-frame transform"
```

---

## Task 3: `polar.ts` — polar (radius, angle) pairs

**Files:**
- Create: `packages/force-plotting/src/polar.ts`
- Test: `packages/force-plotting/src/polar.test.ts`

**Interfaces:**
- Consumes: `Cache` from `./liveCache`; `AngleParams`, `spindleAngle` from `./angle`.
- Produces: `PolarRadius`, `PolarParams`, `PolarResult`, `buildPolar(c, p)`. `PolarPlot.vue`
  (Task 8) consumes this.

- [ ] **Step 1: Write the failing tests**

```ts
// packages/force-plotting/src/polar.test.ts
import { describe, expect, it } from 'vitest';
import { buildPolar, type PolarParams } from './polar';
import type { AngleParams } from './angle';
import type { Cache } from './liveCache';

function makeCache(overrides: Partial<Cache> = {}): Cache {
	const N = overrides.N ?? 40;
	return {
		N, Fs: 1000, feed: 0.05, diam: 80, csSec: 0, ceSec: (N - 1) * 0.01,
		t: overrides.t ?? Float32Array.from({ length: N }, (_, i) => i * 0.01),
		revs: overrides.revs ?? Float32Array.from({ length: N }, (_, i) => i * 0.02),
		Fx: overrides.Fx ?? Float32Array.from({ length: N }, () => 3),
		Fy: overrides.Fy ?? Float32Array.from({ length: N }, () => 4),
		Fz: overrides.Fz ?? Float32Array.from({ length: N }, () => 1),
		rpm: overrides.rpm ?? Float32Array.from({ length: N }, () => 1200),
		...overrides,
	};
}
function angleParams(overrides: Partial<AngleParams> = {}): AngleParams {
	return { source: 'tacho', ppr: 1, offsetDeg: 0, direction: 1, engagementN: 5, ...overrides };
}
function polarParams(overrides: Partial<PolarParams> = {}): PolarParams {
	return {
		radius: 'Fxy', angle: angleParams(), window: { cropStartSec: 0, cropEndSec: 1e9, stride: 1 },
		bins: 0, ...overrides,
	};
}

describe('buildPolar', () => {
	it('Fxy radius equals hypot(Fx, Fy)', () => {
		const c = makeCache();
		const r = buildPolar(c, polarParams());
		expect(r).not.toBeNull();
		expect(r!.unit).toBe('N');
		for (const v of r!.r) expect(v).toBeCloseTo(5, 5); // hypot(3,4)=5
	});

	it('returns null when radius=Mz and the cache has no Mz channel', () => {
		const c = makeCache();
		const r = buildPolar(c, polarParams({ radius: 'Mz' }));
		expect(r).toBeNull();
	});

	it('counts dropped points for NaN angle (force_vector below engagement)', () => {
		const N = 6;
		const c = makeCache({ N, Fx: new Float32Array(N).fill(0.01), Fy: new Float32Array(N).fill(0.01) });
		const r = buildPolar(c, polarParams({ angle: angleParams({ source: 'force_vector', engagementN: 5 }) }));
		expect(r).not.toBeNull();
		expect(r!.dropped).toBe(N);
		expect(r!.count).toBe(0);
	});

	it('a synthetic 4-flute Mz signal shows four maxima across angular bins', () => {
		const N = 720;
		const t = Float32Array.from({ length: N }, (_, i) => i * 0.001);
		// One full revolution over the window; revs_cum goes 0..1.
		const revs = Float32Array.from({ length: N }, (_, i) => i / N);
		const Mz = new Float32Array(N);
		for (let i = 0; i < N; i++) {
			const phi = (i / N) * 2 * Math.PI;
			Mz[i] = 10 * (1 + 0.3 * Math.cos(4 * phi));
		}
		const c = makeCache({ N, t, revs, Mz } as Partial<Cache>);
		const bins = 36;
		const r = buildPolar(c, polarParams({ radius: 'Mz', bins }));
		expect(r).not.toBeNull();
		expect(r!.unit).toBe('N·m');
		// Reduce to per-bin means the same way the 4-lobe check needs: find local maxima count.
		const perBin = new Map<number, number[]>();
		for (let k = 0; k < r!.count; k++) {
			const b = Math.min(bins - 1, Math.floor((r!.phi[k] / (2 * Math.PI)) * bins));
			(perBin.get(b) ?? perBin.set(b, []).get(b)!).push(r!.r[k]);
		}
		const means = Array.from({ length: bins }, (_, b) => {
			const vs = perBin.get(b) ?? [];
			return vs.length ? vs.reduce((a, x) => a + x, 0) / vs.length : 0;
		});
		let maxima = 0;
		for (let b = 0; b < bins; b++) {
			const prev = means[(b - 1 + bins) % bins], next = means[(b + 1) % bins];
			if (means[b] > prev && means[b] > next) maxima++;
		}
		expect(maxima).toBe(4);
	});
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `npm run test -w @d1/force-plotting -- polar.test`
Expected: FAIL — `polar.ts` does not exist yet.

- [ ] **Step 3: Implement `polar.ts`**

```ts
// packages/force-plotting/src/polar.ts
//
// Radius/angle pairs for the polar-plot panel. See
// docs/superpowers/specs/2026-09-07-milling-path-models-and-polar-design.md §6.
import type { Cache } from './liveCache';
import { spindleAngle, type AngleParams } from './angle';
import type { PathWindow } from './path';

export type PolarRadius = 'Mz' | 'Fz' | 'Fxy';

export interface PolarParams {
	radius: PolarRadius;
	angle: AngleParams;
	window: PathWindow;
	bins: number;   // 0 = raw scatter (this field is advisory for callers; buildPolar always
	                // returns raw per-point r/phi -- binning for display is the renderer's job)
}

export interface PolarResult {
	r: Float32Array;
	phi: Float32Array;
	count: number;
	rMin: number; rMax: number;
	unit: 'N·m' | 'N';
	dropped: number;
}

function idxOfTime(t: Float32Array, sec: number): number {
	if (t.length === 0) return -1;
	let lo = 0, hi = t.length - 1, ans = t.length - 1;
	while (lo <= hi) { const m = (lo + hi) >> 1; if (t[m] >= sec) { ans = m; hi = m - 1; } else lo = m + 1; }
	return ans;
}

export function buildPolar(c: Cache, p: PolarParams): PolarResult | null {
	const t = c.t;
	if (!t || t.length === 0 || c.N === 0) return null;
	if (p.radius === 'Mz' && !(c as any).Mz) return null;

	const cs = idxOfTime(t, p.window.cropStartSec);
	if (cs < 0) return null;
	const stride = Math.max(1, Math.round(p.window.stride) || 1);

	const idxAll: number[] = [];
	for (let i = cs; i < c.N; i += stride) {
		if (t[i] > p.window.cropEndSec) break;
		idxAll.push(i);
	}
	if (!idxAll.length) return null;
	const idx = Int32Array.from(idxAll);

	const phiAll = new Float32Array(idx.length);
	spindleAngle(c, p.angle, idx, phiAll);

	const src: Float32Array = p.radius === 'Mz' ? (c as any).Mz : p.radius === 'Fz' ? c.Fz : c.Fx;
	const srcY = p.radius === 'Fxy' ? c.Fy : null;

	const r = new Float32Array(idx.length);
	const phi = new Float32Array(idx.length);
	let m = 0, dropped = 0;
	let rMin = Infinity, rMax = -Infinity;
	for (let k = 0; k < idx.length; k++) {
		if (Number.isNaN(phiAll[k])) { dropped++; continue; }
		const i = idx[k];
		const v = srcY ? Math.hypot(src[i], srcY[i]) : src[i];
		r[m] = v; phi[m] = phiAll[k];
		if (v < rMin) rMin = v; if (v > rMax) rMax = v;
		m++;
	}
	if (!m) return { r: new Float32Array(0), phi: new Float32Array(0), count: 0, rMin: 0, rMax: 0, unit: p.radius === 'Mz' ? 'N·m' : 'N', dropped };
	return {
		r: r.subarray(0, m), phi: phi.subarray(0, m), count: m, rMin, rMax,
		unit: p.radius === 'Mz' ? 'N·m' : 'N', dropped,
	};
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `npm run test -w @d1/force-plotting -- polar.test`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add packages/force-plotting/src/polar.ts packages/force-plotting/src/polar.test.ts
git commit -m "feat(force-plotting): polar.ts -- (r, phi) pairs for the polar-plot panel"
```

---

## Task 4: `buildCloud` refactor — the risky, revert-safe step

This is the one task in the plan that touches shared, load-bearing code. It is one commit, no new
features, gated on Task 0's golden snapshot and the pre-existing `liveCloud.test.ts` /
`liveCache.test.ts` suites staying green.

**Files:**
- Modify: `packages/force-plotting/src/liveCloud.ts`
- Modify: `packages/force-plotting/src/liveCloud.test.ts` (helpers only — see Global Constraints)
- Modify: `packages/force-plotting/src/liveCloud.golden.test.ts` (adapt to new API, same fixture)
- Modify: `packages/force-plotting/src/FrmCloud.vue`
- Modify: `packages/force-plotting/src/frmExport.ts`
- Modify: `packages/force-plotting/src/index.ts`

**Interfaces:**
- Consumes: `PathParams`, `PathResult`, `buildPath` from `./path` (Task 1).
- Produces: `CloudChannel`, `Cloud` (now with `bounds: PathBounds`, stride-3 `pos`), `CloudParams`
  (now `channel`+`path`+`window` instead of the flat axis/geometry fields), `buildCloud(c, p)`
  unchanged name. `Axis` type is **unchanged** (still `'Fx'|'Fy'|'Fz'`, still exported).

- [ ] **Step 1: Rewrite `liveCloud.ts`**

Replace the whole file with:

```ts
// packages/force-plotting/src/liveCloud.ts
//
// Colourises a tool path built by path.ts into a renderable point cloud. Positions used
// to be computed here directly (a hardcoded turning spiral); that geometry now lives in
// path.ts (buildPath) so it can be swapped for a straight pass or real machine XYZ. This
// file's only job is: pick points along the path, look up their channel value, map to a
// colour. See docs/superpowers/specs/2026-09-07-milling-path-models-and-polar-design.md §3.
import type { Cache } from './liveCache';
import { buildPath, type PathBounds, type PathParams, type PathWindow } from './path';

export type SpeedMode = 'measured' | 'rpm' | 'vc';
export type Axis = 'Fx' | 'Fy' | 'Fz';
export type CloudChannel = 'Fx' | 'Fy' | 'Fz' | 'Mz';

export interface CloudParams {
	channel: CloudChannel;
	path: PathParams;
	window: PathWindow;
	gridding: boolean;
	gridN: number;
	colormap: (x: number) => [number, number, number];
	cmin?: number | null;
	cmax?: number | null;
	zSeries?: 'none' | CloudChannel;
}

export interface Cloud {
	pos: Float32Array;   // stride 3
	col: Float32Array;   // stride 3, rgb 0..1
	count: number;
	bounds: PathBounds;
	cmin: number; cmax: number;
	zv?: Float32Array;   // centred -0.5..0.5 force-as-height, only set for flat (z=const) paths
}

function percentile(sorted: Float32Array, p: number): number {
	const i = Math.min(sorted.length - 1, Math.max(0, Math.round((p / 100) * (sorted.length - 1))));
	return sorted[i];
}

export function axisAutoLimits(c: Cache, channel: CloudChannel): [number, number] {
	const a = (c as any)[channel] as Float32Array | undefined;
	if (!a || a.length === 0) return [0, 1];
	const stride = Math.max(1, Math.floor(a.length / 400_000));
	const s = new Float32Array(Math.ceil(a.length / stride));
	for (let i = 0, k = 0; i < a.length; i += stride, k++) s[k] = a[i];
	s.sort();
	const pc = (q: number) => s[Math.min(s.length - 1, Math.max(0, Math.round((q / 100) * (s.length - 1))))];
	let lo = pc(1), hi = pc(99);
	if (!(hi > lo)) { lo = s[0]; hi = s[s.length - 1]; if (!(hi > lo)) hi = lo + 1; }
	return [lo, hi];
}

export function buildCloud(c: Cache, p: CloudParams): Cloud | null {
	const path = buildPath(c, p.path, p.window);
	if (!path) return null;

	const channelArr = (c as any)[p.channel] as Float32Array;
	const m = path.count;
	const fv = new Float32Array(m);
	for (let k = 0; k < m; k++) fv[k] = channelArr[path.idx[k]];

	const sorted = fv.slice().sort();
	let lo = Number.isFinite(p.cmin as number) ? (p.cmin as number) : percentile(sorted, 1);
	let hi = Number.isFinite(p.cmax as number) ? (p.cmax as number) : percentile(sorted, 99);
	if (!(hi > lo)) { lo = sorted[0]; hi = sorted[sorted.length - 1]; if (!(hi > lo)) hi = lo + 1; }
	const span = hi - lo || 1;

	// Optional force-as-height overlay: only meaningful for a flat (z-constant) path (the
	// turning spiral and a single linear pass both have z=0/const per point). A machine_xyz
	// path already carries real Z, so the overlay is ignored there.
	const isFlatZ = path.bounds.minZ === path.bounds.maxZ;
	let zSrc: Float32Array | null = null;
	if (isFlatZ && p.zSeries && p.zSeries !== 'none') zSrc = (c as any)[p.zSeries] as Float32Array;

	if (p.gridding) return gridCloud(path, fv, lo, span, p, zSrc);

	const pos = new Float32Array(m * 3), col = new Float32Array(m * 3);
	let zlo = Infinity, zhi = -Infinity;
	if (zSrc) for (let k = 0; k < m; k++) { const v = zSrc[path.idx[k]]; if (v < zlo) zlo = v; if (v > zhi) zhi = v; }
	const zspan = (zhi - zlo) || 1;
	let zv: Float32Array | undefined;
	if (zSrc) zv = new Float32Array(m);
	for (let k = 0; k < m; k++) {
		pos[k * 3] = path.pos[k * 3]; pos[k * 3 + 1] = path.pos[k * 3 + 1];
		pos[k * 3 + 2] = zSrc ? 0 : path.pos[k * 3 + 2];   // machine_xyz's real Z passes through when there's no overlay
		const [rr, gg, bb] = p.colormap((fv[k] - lo) / span);
		col[k * 3] = rr; col[k * 3 + 1] = gg; col[k * 3 + 2] = bb;
		if (zv && zSrc) zv[k] = (zSrc[path.idx[k]] - zlo) / zspan - 0.5;
	}
	return { pos, col, count: m, bounds: path.bounds, cmin: lo, cmax: hi, zv };
}

// Bin the scatter into a gridN x gridN grid on X/Y; emit one point per non-empty cell at its
// centre, coloured by the mean channel value there, at the MEAN Z of the points in that cell.
// This is a 2.5-D reduction: two points at the same (x,y) but different z (e.g. a repeated axial
// pass) collapse into one cell. For a flat path every z is identical so this changes nothing.
function gridCloud(
	path: { pos: Float32Array; idx: Int32Array; count: number; bounds: PathBounds },
	fv: Float32Array, lo: number, span: number, p: CloudParams, zSrc: Float32Array | null,
): Cloud {
	const { minX, maxX, minY, maxY } = path.bounds;
	const G = Math.max(8, Math.round(p.gridN) || 400);
	const wx = (maxX - minX) || 1, wy = (maxY - minY) || 1;
	const m = path.count;
	const sum = new Float64Array(G * G), sumZ = new Float64Array(G * G), cnt = new Uint32Array(G * G);
	for (let k = 0; k < m; k++) {
		const x = path.pos[k * 3], y = path.pos[k * 3 + 1], z = path.pos[k * 3 + 2];
		let gx = Math.floor(((x - minX) / wx) * (G - 1e-9));
		let gy = Math.floor(((y - minY) / wy) * (G - 1e-9));
		if (gx < 0) gx = 0; else if (gx >= G) gx = G - 1;
		if (gy < 0) gy = 0; else if (gy >= G) gy = G - 1;
		const idx2 = gy * G + gx;
		sum[idx2] += fv[k]; sumZ[idx2] += z; cnt[idx2]++;
	}
	const cx = wx / G, cy = wy / G;
	const xsg: number[] = [], ysg: number[] = [], zsg: number[] = [], cg: number[] = [];
	for (let gy = 0; gy < G; gy++) for (let gx = 0; gx < G; gx++) {
		const idx2 = gy * G + gx; const n = cnt[idx2]; if (!n) continue;
		xsg.push(minX + (gx + 0.5) * cx); ysg.push(minY + (gy + 0.5) * cy);
		zsg.push(sumZ[idx2] / n); cg.push(sum[idx2] / n);
	}
	const n = cg.length;
	const pos = new Float32Array(n * 3), col = new Float32Array(n * 3);
	for (let k = 0; k < n; k++) {
		pos[k * 3] = xsg[k]; pos[k * 3 + 1] = ysg[k]; pos[k * 3 + 2] = zSrc ? 0 : zsg[k];
		const [rr, gg, bb] = p.colormap((cg[k] - lo) / span);
		col[k * 3] = rr; col[k * 3 + 1] = gg; col[k * 3 + 2] = bb;
	}
	return { pos, col, count: n, bounds: path.bounds, cmin: lo, cmax: lo + span };
}

// ---- colormaps (0..1 -> rgb 0..1) ----
const clamp01 = (v: number) => (Number.isNaN(v) ? 0 : v < 0 ? 0 : v > 1 ? 1 : v);

const VIRIDIS_ANCHORS: [number, number, number][] = [
	[0.267004, 0.004874, 0.329415], [0.282623, 0.140926, 0.457517], [0.253935, 0.265254, 0.529983],
	[0.206756, 0.371758, 0.553117], [0.163625, 0.471133, 0.558148], [0.127568, 0.566949, 0.550556],
	[0.134692, 0.658636, 0.517649], [0.266941, 0.748751, 0.440573], [0.477504, 0.821444, 0.318195],
	[0.741388, 0.873449, 0.149561], [0.993248, 0.906157, 0.143936],
];

function lutLerp(anchors: [number, number, number][], x: number): [number, number, number] {
	x = clamp01(x);
	const last = anchors.length - 1;
	const s = x * last;
	const i = Math.min(last - 1, Math.floor(s));
	const f = s - i;
	const a = anchors[i], b = anchors[i + 1];
	return [a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f, a[2] + (b[2] - a[2]) * f];
}

function viridis(x: number): [number, number, number] { return lutLerp(VIRIDIS_ANCHORS, x); }
function inferno(x: number): [number, number, number] {
	x = clamp01(x);
	const r = -0.0002 + x * (0.1065 + x * (11.6035 + x * (-42.1403 + x * (60.1300 + x * (-35.0665 + x * 7.3641)))));
	const g = 0.0009 + x * (-0.3852 + x * (2.1873 + x * (-2.4184 + x * (2.7095 + x * (-1.8895 + x * 0.4443)))));
	const b = 0.0139 + x * (2.9950 + x * (-16.0958 + x * (40.6117 + x * (-46.3423 + x * (24.0722 + x * -4.6595)))));
	return [clamp01(r), clamp01(g), clamp01(b)];
}
function grayscale(x: number): [number, number, number] { const v = clamp01(x); return [v, v, v]; }

export const COLORMAPS: Record<string, (x: number) => [number, number, number]> = {
	viridis, inferno, grayscale,
};
```

Note: `axisAutoLimits`'s old signature took `axis: Axis`; it now takes `channel: CloudChannel`.
Every existing call site (`FrmCloud.vue`, `engine.ts`) passes an `Axis` value, which is a subset of
`CloudChannel`, so **no call site needs to change for this alone** — TypeScript accepts a narrower
literal type wherever the wider one is expected.

- [ ] **Step 2: Adapt `liveCloud.test.ts`'s helpers to the new `CloudParams` shape**

Open `packages/force-plotting/src/liveCloud.test.ts`. Replace only `baseParams()` (leave every
`it(...)` body and its assertions untouched — per the Global Constraints, expectations do not
change):

```ts
function baseParams(overrides: Partial<CloudParams> = {}): CloudParams {
	return {
		channel: 'Fz',
		path: {
			kind: 'turning_spiral', feed: 0.05, diam: 80, innerDiam: 0,
			speedMode: 'measured', rpm: 1200, vc: 0, timeScale: 1, ppr: 1,
		},
		window: { cropStartSec: 0, cropEndSec: 1e9, stride: 1 },
		gridding: false, gridN: 400,
		colormap: COLORMAPS.viridis,
		cmin: null, cmax: null, zSeries: 'none',
		...overrides,
	};
}
```

Any existing test that overrides a field the old flat shape had (e.g. `{ axis: 'Fx' }` or
`{ innerDiam: 20 }`) must be updated to the nested shape (`{ channel: 'Fx' }` or
`{ path: { ...baseParams().path, innerDiam: 20 } }`). **Read every existing test in the file before
editing it** — the goal is that each one asserts exactly what it asserted before, against the new
parameter shape. Do not change what is being asserted.

Also update the `bounds` fields used in any test that reads `cloud.minX`/`maxX`/`minY`/`maxY` to
read `cloud.bounds.minX` etc. — mechanical, not a behaviour change.

- [ ] **Step 3: Run the pre-existing suite and fix any remaining shape mismatches**

Run: `npm run test -w @d1/force-plotting -- liveCloud.test`
Expected: PASS, same 13 tests, same assertions, only fixture shape changed. If any test's
*expectation* would need to change (not just its parameter shape) to pass, STOP — that is an
unintended behaviour change per the Global Constraints. Do not edit the assertion; investigate the
implementation instead.

- [ ] **Step 4: Migrate the golden test to the new API and verify the frozen snapshot still matches**

Edit `liveCloud.golden.test.ts`: change `baseParams()` the same way as Step 2, and change the
serialised shape to compare stride-3 positions against the stride-2 snapshot by dropping z (which
must be exactly 0 for every non-`z-series` case) and by not exercising the removed
`minX/maxX/minY/maxY` fields directly (read `cloud.bounds.minX` etc. instead — same numeric
values, so the snapshot's `bounds` entries still match). Concretely, replace the `it` body's
`expect({...}).toMatchSnapshot()` object with:

```ts
it(`matches the frozen snapshot: ${name}`, () => {
	const cloud = buildCloud(cache, baseParams(overrides));
	expect(cloud).not.toBeNull();
	const n = cloud!.count;
	const pos2 = new Array<number>(n * 2);
	for (let k = 0; k < n; k++) {
		expect(cloud!.pos[k * 3 + 2]).toBe(0);   // flat turning-spiral path: z must stay 0
		pos2[k * 2] = cloud!.pos[k * 3]; pos2[k * 2 + 1] = cloud!.pos[k * 3 + 1];
	}
	expect({
		count: cloud!.count,
		pos: pos2,
		col: Array.from(cloud!.col),
		bounds: [cloud!.bounds.minX, cloud!.bounds.maxX, cloud!.bounds.minY, cloud!.bounds.maxY],
		climits: [cloud!.cmin, cloud!.cmax],
		zv: cloud!.zv ? Array.from(cloud!.zv) : null,
	}).toMatchSnapshot();
});
```

Run: `npm run test -w @d1/force-plotting -- liveCloud.golden`
Expected: PASS against the **existing, uncommitted-since-Task-0** snapshot file — no `-u` flag, no
regenerating. A failure here means the refactor changed geometry; do not update the snapshot to
make it pass, fix the implementation.

- [ ] **Step 5: Update `FrmCloud.vue`**

Read the whole file first (it is long; only the sections below change). Replace the props block:

```ts
const props = withDefaults(defineProps<{
	cacheFileId: string;
	// New: an explicit path config overrides the flat turning-spiral props below when supplied.
	path?: PathParams;
	channel?: CloudChannel;
	/** @deprecated use `channel` — kept so existing Fx/Fy/Fz toggles keep compiling. */
	axis?: Axis;
	feed: number;
	diam: number;
	innerDiam: number;
	speedMode: SpeedMode;
	rpm: number;
	vc: number;
	timeScale: number;
	ppr: number;
	cropStartSec: number;
	cropEndSec: number;
	stride: number;
	gridding: boolean;
	gridN: number;
	pointSize: number;
	colormap: string;
	cmin?: number | null;
	cmax?: number | null;
	zSeries?: 'none' | 'Fx' | 'Fy' | 'Fz';
	zScale?: number;
	sharedView?: { cx: number; cy: number; span: number; active: boolean };
	cacheOverride?: Cache | null;
	paneLabel?: string;
}>(), { initialChannel: 'residZ', noPopout: false });
```

Wait — `initialChannel`/`noPopout` belong to `SpatialPanel.vue`, not `FrmCloud.vue`; keep
`FrmCloud`'s own `withDefaults` second argument empty (`{}`) since none of its props need a
default beyond what already exists. Add the two imports at the top:

```ts
import type { PathParams } from './path';
```

(`CloudChannel` and `Axis` are already imported from `./liveCloud` — add `CloudChannel` to that
existing import list.)

Add, right after the `props` declaration, the effective-channel and effective-path resolution:

```ts
// `channel` wins when supplied; `axis` is the deprecated alias every existing caller still uses.
const effChannel = computed<CloudChannel>(() => props.channel ?? props.axis ?? 'Fz');
// `path` wins when supplied; otherwise assemble a turning_spiral from the flat props, exactly
// reproducing what this component computed inline before the path-model refactor.
const effPath = computed<PathParams>(() => props.path ?? {
	kind: 'turning_spiral', feed: props.feed, diam: props.diam, innerDiam: props.innerDiam,
	speedMode: props.speedMode, rpm: props.rpm, vc: props.vc, timeScale: props.timeScale, ppr: props.ppr,
});
```

Update `effClimits()`'s `axisAutoLimits` call and `rebuild()`'s `buildCloud` call:

```ts
function effClimits(): { cmin: number; cmax: number } {
	let auto = autoLimitsByAxis.get(effChannel.value);
	if (!auto && cache.value) { auto = axisAutoLimits(cache.value, effChannel.value); autoLimitsByAxis.set(effChannel.value, auto); }
	auto = auto || [0, 1];
	return {
		cmin: Number.isFinite(props.cmin as number) ? (props.cmin as number) : auto[0],
		cmax: Number.isFinite(props.cmax as number) ? (props.cmax as number) : auto[1],
	};
}
function rebuild() {
	if (!ready || !pointsGeom || !canvasEl.value || !cache.value) return;
	const eff = effClimits();
	cloud = buildCloud(cache.value, {
		channel: effChannel.value,
		path: effPath.value,
		window: { cropStartSec: props.cropStartSec, cropEndSec: props.cropEndSec, stride: props.stride },
		gridding: props.gridding, gridN: props.gridN,
		colormap: COLORMAPS[props.colormap] || COLORMAPS.viridis,
		cmin: eff.cmin, cmax: eff.cmax,
		zSeries: props.zSeries || 'none',
	});
	pointCount.value = cloud?.count ?? 0;
	emit('points', pointCount.value);
	if (!cloud) { climits.value = null; scaleBar.value = null; return; }

	fitCx = (cloud.bounds.minX + cloud.bounds.maxX) / 2; fitCy = (cloud.bounds.minY + cloud.bounds.maxY) / 2;
	fitSpan = Math.max(cloud.bounds.maxX - cloud.bounds.minX, cloud.bounds.maxY - cloud.bounds.minY) || 1;

	// pos is now stride-3 already — no repack loop needed (this used to expand a stride-2
	// cloud.pos into a stride-3 GPU buffer by hand).
	const n = cloud.count;
	pointsGeom.setAttribute('position', new THREE.BufferAttribute(cloud.pos, 3));
	pointsGeom.setAttribute('color', new THREE.BufferAttribute(cloud.col, 3));
	pointsGeom.setDrawRange(0, n);
	applyZScale();
	if (is3D.value && !controls) enter3D();
```

Leave the rest of `rebuild()` (the colorbar-limits block that follows) as-is.

Update the `autoLimitsByAxis` watcher and the `watch([...], scheduleRebuild)` list's `props.axis`
reference to `effChannel.value`, and add `effPath`/`effChannel` to that watch's dependency array in
place of the individual flat geometry props:

```ts
watch(() => [effChannel.value, effPath.value, props.stride, props.cropStartSec, props.cropEndSec,
	props.gridding, props.gridN, props.colormap, props.cmin, props.cmax, props.zSeries], scheduleRebuild, { deep: true });
```

Update the `exportViewport`/`frmExport` call site (search for `axis: props.axis` in the file) to
pass `axis: effChannel.value` instead — `frmExport.ts`'s `axis` field is a display label, `string`,
so `CloudChannel` satisfies it without further change there.

- [ ] **Step 6: Update `frmExport.ts`'s bounds type**

The `bounds` field it already destructures (`{ xmin, xmax, ymin, ymax }`) is unrelated to
`Cloud.bounds`'s field names (`minX`/`maxX`/...) — `exportFrmFigure`'s caller in `FrmCloud.vue`
builds that object itself from `fitCx/fitSpan` etc, not from `cloud.bounds` directly, so
**`frmExport.ts` needs no change**. Confirm this by searching the file for `cloud.` — it does not
reference the `Cloud` type at all, only the plain `{xmin,xmax,ymin,ymax}` object passed in. Skip
this step; recorded here so it isn't silently missed.

- [ ] **Step 7: Update `index.ts` exports**

```ts
export { COLORMAPS, axisAutoLimits } from './liveCloud';
export type { Axis, CloudChannel } from './liveCloud';
export type { SpeedMode } from './liveCloud';
export { buildPath } from './path';
export type { PathKind, PathParams, PathWindow, PathBounds, PathResult, TurningSpiralParams, LinearFeedParams, MachineXyzParams } from './path';
export { spindleAngle, toFixedFrame, AngleSourceUnavailableError } from './angle';
export type { AngleSource, AngleParams, FixedFrame } from './angle';
export { buildPolar } from './polar';
export type { PolarRadius, PolarParams, PolarResult } from './polar';
```
(Add these lines near the existing `liveCloud`/`liveCache` export block; do not remove anything.)

- [ ] **Step 8: Run the full package test suite and typecheck**

Run: `npm run test -w @d1/force-plotting`
Expected: all files pass, including the 13 original `liveCloud.test.ts` tests, the golden test, and
the three new Task 1-3 suites.

Run: `npm run typecheck -w @d1/force-plotting`
Expected: no errors. Pay particular attention to `FrmCloud.vue` and any other `.vue` file that
imports `Axis`/`CloudChannel`/`buildCloud` — `vue-tsc` will catch a missed call site.

- [ ] **Step 9: Grep for any other `buildCloud`/`.minX`/`.axis` call site this task missed**

Run: `grep -rn "buildCloud\|axisAutoLimits\|cloud\.minX\|cloud\.maxX\|cloud\.minY\|cloud\.maxY" packages/force-plotting/src apps/force-app/web/src --include=*.ts --include=*.vue`

Expected matches: only the ones already handled in Steps 1-7 (`liveCloud.ts`'s own definitions,
`FrmCloud.vue`, the test files, `index.ts`). If `apps/force-app/web/src/record/playback/engine.ts`
appears, open it and confirm it only calls `axisAutoLimits(cache, axis)` with an `Axis`-typed
`axis` variable — that compiles unchanged against the widened `CloudChannel` parameter, so no edit
is needed there; just confirm with `npm run typecheck -w force-app-web` in Task 9's acceptance
step.

- [ ] **Step 10: Commit**

```bash
git add packages/force-plotting/src/liveCloud.ts packages/force-plotting/src/liveCloud.test.ts \
        packages/force-plotting/src/liveCloud.golden.test.ts packages/force-plotting/src/FrmCloud.vue \
        packages/force-plotting/src/index.ts
git commit -m "refactor(force-plotting): buildCloud consumes buildPath; Cloud.pos is stride-3

Zero behaviour change for turning captures -- the golden snapshot from
the pre-refactor commit passes unmodified, and every existing
liveCloud.test.ts assertion is untouched. FrmCloud keeps its flat prop
surface; axis survives as a deprecated alias for channel."
```

---

## Task 5: D1LC v2 cache format

**Files:**
- Modify: `packages/force-plotting/src/liveCache.ts`
- Modify: `packages/force-plotting/src/liveCache.test.ts` (additive only)
- Modify: `packages/force-plotting/src/path.ts` (the `(c as any)` cleanup noted in Task 1)
- Modify: `apps/force-app/backend/app/d1lc.py`
- Create: `apps/force-app/backend/tests/test_d1lc.py`

**Interfaces:**
- Produces: `Cache` gains optional `Mz?`, `X?`, `Y?`, `Z?: Float32Array` and a required `version:
  number`. `write_d1lc(...)` gains an optional `extras: dict[str, np.ndarray] | None = None`
  keyword parameter.

- [ ] **Step 1: Write the failing TypeScript tests**

Append to `packages/force-plotting/src/liveCache.test.ts` (read the file first; add these `describe`
blocks without touching anything above them):

```ts
describe('D1LC v2 trailer', () => {
	const MAGIC = 0x44314c43;
	function v1Buffer(N = 5): ArrayBuffer {
		const buf = new ArrayBuffer(32 + N * 6 * 4);
		const dv = new DataView(buf);
		dv.setUint32(0, MAGIC, true); dv.setUint32(4, 1, true); dv.setUint32(8, N, true);
		dv.setFloat32(12, 1000, true); dv.setFloat32(16, 0.05, true); dv.setFloat32(20, 80, true);
		dv.setFloat32(24, 0, true); dv.setFloat32(28, (N - 1) * 0.01, true);
		let off = 32;
		for (let arr = 0; arr < 6; arr++) for (let i = 0; i < N; i++) { dv.setFloat32(off, arr * 10 + i, true); off += 4; }
		return buf;
	}
	function v2Buffer(N: number, extras: Record<string, number[]>): ArrayBuffer {
		const names = Object.keys(extras);
		const trailerBytes = 4 + names.reduce((s, n) => s + 8 + N * 4, 0);
		const buf = new ArrayBuffer(32 + N * 6 * 4 + trailerBytes);
		const dv = new DataView(buf);
		dv.setUint32(0, MAGIC, true); dv.setUint32(4, 2, true); dv.setUint32(8, N, true);
		dv.setFloat32(12, 1000, true); dv.setFloat32(16, 0.05, true); dv.setFloat32(20, 80, true);
		dv.setFloat32(24, 0, true); dv.setFloat32(28, (N - 1) * 0.01, true);
		let off = 32;
		for (let arr = 0; arr < 6; arr++) for (let i = 0; i < N; i++) { dv.setFloat32(off, arr * 10 + i, true); off += 4; }
		dv.setUint32(off, names.length, true); off += 4;
		for (const name of names) {
			const bytes = new Uint8Array(8);
			for (let i = 0; i < Math.min(8, name.length); i++) bytes[i] = name.charCodeAt(i);
			new Uint8Array(buf, off, 8).set(bytes); off += 8;
			for (const v of extras[name]) { dv.setFloat32(off, v, true); off += 4; }
		}
		return buf;
	}

	it('parses a v1 buffer to exactly today\'s Cache shape, optional fields undefined', () => {
		const c = parseCache(v1Buffer(5));
		expect(c.version).toBe(1);
		expect(c.N).toBe(5);
		expect(Array.from(c.t)).toEqual([0, 1, 2, 3, 4]);
		expect(Array.from(c.Fx)).toEqual([10, 11, 12, 13, 14]);
		expect(Array.from(c.Fy)).toEqual([20, 21, 22, 23, 24]);
		expect(Array.from(c.Fz)).toEqual([30, 31, 32, 33, 34]);
		expect(Array.from(c.rpm)).toEqual([40, 41, 42, 43, 44]);
		expect(Array.from(c.revs)).toEqual([50, 51, 52, 53, 54]);
		expect(c.Mz).toBeUndefined();
		expect(c.X).toBeUndefined();
		expect(c.Y).toBeUndefined();
		expect(c.Z).toBeUndefined();
	});

	it('parses a v2 buffer with Mz + X/Y/Z into the optional fields', () => {
		const N = 4;
		const buf = v2Buffer(N, {
			Mz: [1, 2, 3, 4], X: [10, 11, 12, 13], Y: [20, 21, 22, 23], Z: [30, 31, 32, 33],
		});
		const c = parseCache(buf);
		expect(c.version).toBe(2);
		expect(Array.from(c.Mz!)).toEqual([1, 2, 3, 4]);
		expect(Array.from(c.X!)).toEqual([10, 11, 12, 13]);
		expect(Array.from(c.Y!)).toEqual([20, 21, 22, 23]);
		expect(Array.from(c.Z!)).toEqual([30, 31, 32, 33]);
	});

	it('ignores an unknown trailer name without throwing', () => {
		const buf = v2Buffer(3, { Zz: [1, 2, 3] });
		expect(() => parseCache(buf)).not.toThrow();
		const c = parseCache(buf);
		expect(c.Mz).toBeUndefined();
	});

	it('decimateCache decimates the optional arrays to the same length as the mandatory ones', () => {
		const N = 9;
		const buf = v2Buffer(N, { Mz: Array.from({ length: N }, (_, i) => i) });
		const c = parseCache(buf);
		const d = decimateCache(c, 3);
		expect(d.Mz!.length).toBe(d.t.length);
		expect(Array.from(d.Mz!)).toEqual([0, 3, 6]);
	});
});
```

- [ ] **Step 2: Run to verify failure**

Run: `npm run test -w @d1/force-plotting -- liveCache.test`
Expected: FAIL — `c.version` is undefined, `c.Mz` doesn't parse.

- [ ] **Step 3: Extend `liveCache.ts`**

Read the full file first. Change the `Cache` interface and `parseCache`/`decimateCache`:

```ts
export interface Cache {
	N: number; Fs: number; feed: number; diam: number; csSec: number; ceSec: number;
	t: Float32Array; Fx: Float32Array; Fy: Float32Array; Fz: Float32Array;
	rpm: Float32Array; revs: Float32Array;
	Mz?: Float32Array; X?: Float32Array; Y?: Float32Array; Z?: Float32Array;
	version: number;
}

const MAGIC = 0x44314c43; // 'D1LC'
const KNOWN_TRAILER_NAMES = ['Mz', 'X', 'Y', 'Z'] as const;

// Parse live_cache.bin (little-endian): 32-byte header then six float32[N] arrays, then
// (version >= 2 only) a trailer of named float32[N] extras. Layout MUST match
// scripts/matlab/process_force.m's write_live_cache and apps/force-app/backend/app/d1lc.py.
export function parseCache(ab: ArrayBuffer): Cache {
	const dv = new DataView(ab);
	if (dv.getUint32(0, true) !== MAGIC) throw new Error('bad live-cache magic');
	const version = dv.getUint32(4, true);
	const N = dv.getUint32(8, true);
	const Fs = dv.getFloat32(12, true);
	const feed = dv.getFloat32(16, true);
	const diam = dv.getFloat32(20, true);
	const csSec = dv.getFloat32(24, true);
	const ceSec = dv.getFloat32(28, true);
	let off = 32;
	const take = () => { const a = new Float32Array(ab, off, N); off += N * 4; return a; };
	const t = take(), Fx = take(), Fy = take(), Fz = take(), rpm = take(), revs = take();
	const cache: Cache = { N, Fs, feed, diam, csSec, ceSec, t, Fx, Fy, Fz, rpm, revs, version };

	if (version >= 2 && off + 4 <= ab.byteLength) {
		const extraCount = dv.getUint32(off, true); off += 4;
		for (let e = 0; e < extraCount; e++) {
			if (off + 8 > ab.byteLength) break;
			const nameBytes = new Uint8Array(ab, off, 8); off += 8;
			let name = '';
			for (let i = 0; i < 8 && nameBytes[i] !== 0; i++) name += String.fromCharCode(nameBytes[i]);
			const arr = new Float32Array(ab, off, N); off += N * 4;
			if ((KNOWN_TRAILER_NAMES as readonly string[]).includes(name)) (cache as any)[name] = arr;
			// unknown names are read past (to keep `off` correct for subsequent entries) and dropped
		}
	}
	return cache;
}

export function decimateCache(c: Cache, stride: number): Cache {
	if (stride <= 1) return c;
	const pick = (a: Float32Array) => {
		const n = Math.ceil(a.length / stride);
		const o = new Float32Array(n);
		for (let i = 0, k = 0; i < a.length; i += stride, k++) o[k] = a[i];
		return o;
	};
	const out: Cache = {
		...c, N: Math.ceil(c.N / stride), t: pick(c.t), Fx: pick(c.Fx), Fy: pick(c.Fy), Fz: pick(c.Fz),
		rpm: pick(c.rpm), revs: pick(c.revs),
	};
	if (c.Mz) out.Mz = pick(c.Mz);
	if (c.X) out.X = pick(c.X);
	if (c.Y) out.Y = pick(c.Y);
	if (c.Z) out.Z = pick(c.Z);
	return out;
}
```

Leave every other function in the file (`buildSeriesEnvelope`, `bucketEnvelope`, `cacheGet`,
`cachePut`) untouched.

- [ ] **Step 4: Run TypeScript tests to verify they pass**

Run: `npm run test -w @d1/force-plotting -- liveCache.test`
Expected: PASS, including the pre-existing 14 tests (unmodified) and the 4 new ones.

- [ ] **Step 5: Clean up the `(c as any)` casts in `path.ts` from Task 1**

Now that `Cache` has real `X`/`Y`/`Z` fields, in `buildMachineXyz` replace:

```ts
const src = { X: (c as any).X, Y: (c as any).Y, Z: (c as any).Z } as Record<string, Float32Array | undefined>;
```

with:

```ts
const src: Record<'X' | 'Y' | 'Z', Float32Array | undefined> = { X: c.X, Y: c.Y, Z: c.Z };
```

Run: `npm run test -w @d1/force-plotting -- path.test` — Expected: still PASS (10 tests).

Also, in `liveCloud.ts`, the `(c as any)[p.channel]` and `(c as any)[p.zSeries]` lookups may now be
typed as `(c as any)[key] as Float32Array` still (channel/zSeries are string-indexed on a typed
interface with some optional keys) — leave those as `(c as any)` casts; narrowing them properly
would require a mapped-type refactor of `Cache` that is out of scope here, and the cast is safe
because `CloudChannel` is validated to be one of `Fx|Fy|Fz|Mz`, all real `Cache` keys.

- [ ] **Step 6: Write the failing Python test**

```python
# apps/force-app/backend/tests/test_d1lc.py
"""D1LC writer tests: v1 byte-identity and the v2 extras trailer.

See docs/superpowers/specs/2026-09-07-milling-path-models-and-polar-design.md #4.
"""
from __future__ import annotations

import struct

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
    import tempfile
    import os
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
        magic, version, n = struct.unpack_from("<III", buf, 0)
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
```

- [ ] **Step 7: Run to verify failure**

Run (from `apps/force-app/backend`): `.venv\Scripts\python -m pytest tests/test_d1lc.py -v`
Expected: FAIL — `write_d1lc` has no `extras` parameter yet; `parse_d1lc` has no `extras` key.

- [ ] **Step 8: Extend `d1lc.py`**

Read the full existing file first, then replace `write_d1lc` and `parse_d1lc`:

```python
"""D1LC live-cache writer — byte-identical to plugins/filter-service/app/d1lc.py,
scripts/matlab/process_force.m::write_live_cache, and the client parser liveCache.ts.

32-byte LE header (magic 'D1LC', version, N, Fs, feed, diam, cs_sec, ce_sec) then six
float32[N] arrays t, Fx, Fy, Fz, rpm, revs_cum. Version 1 (no extras) is byte-identical to
before this file gained the `extras` parameter. Version 2 appends a trailer of named
float32[N] arrays -- see docs/superpowers/specs/2026-09-07-milling-path-models-and-polar-design.md #4.
Writing this format means the finished cut renders through the existing FrmCloud/ForceChart
with no new display code.
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
    extras: dict[str, np.ndarray] | None = None,
) -> None:
    n = int(t.size)
    version = 2 if extras else 1
    head = struct.pack(
        "<IIIfffff", MAGIC, version, n, float(fs), float(feed), float(diam), float(cs_sec), float(ce_sec)
    )
    with open(path, "wb") as f:
        f.write(head)
        for arr in (t, fx, fy, fz, rpm, revs):
            f.write(np.ascontiguousarray(arr, dtype="<f4").tobytes())
        if extras:
            f.write(struct.pack("<I", len(extras)))
            for name, arr in extras.items():
                name_bytes = name.encode("ascii")[:8].ljust(8, b"\x00")
                f.write(name_bytes)
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
    """Full parse: header + the six float32[N] arrays (t, Fx, Fy, Fz, rpm, revs), plus a
    version-2 `extras` dict of any named trailer arrays this reader recognises."""
    h = read_d1lc_header(buf)
    n = h["n"]
    names = ["t", "fx", "fy", "fz", "rpm", "revs"]
    arrs = np.frombuffer(buf, dtype="<f4", count=n * 6, offset=32)
    a = arrs.reshape(6, n)
    out = dict(h)
    out.update({name: a[i].copy() for i, name in enumerate(names)})
    out["extras"] = {}
    off = 32 + n * 6 * 4
    if h["version"] >= 2 and off + 4 <= len(buf):
        (extra_count,) = struct.unpack_from("<I", buf, off)
        off += 4
        known = {"Mz", "X", "Y", "Z"}
        for _ in range(extra_count):
            if off + 8 > len(buf):
                break
            name = buf[off:off + 8].rstrip(b"\x00").decode("ascii", errors="replace")
            off += 8
            arr = np.frombuffer(buf, dtype="<f4", count=n, offset=off).copy()
            off += n * 4
            if name in known:
                out["extras"][name] = arr
    return out
```

- [ ] **Step 9: Run to verify pass**

Run: `.venv\Scripts\python -m pytest tests/test_d1lc.py -v`
Expected: PASS (3 tests).

Then confirm nothing else in the backend broke:

Run: `.venv\Scripts\python -m pytest tests/ -k "d1lc or finalize or replay" -v`
Expected: PASS. (`finalize.py` calls `write_d1lc` positionally without `extras` — the new
parameter is keyword-only-by-default-value, so this call is unaffected.)

- [ ] **Step 10: Commit**

```bash
git add packages/force-plotting/src/liveCache.ts packages/force-plotting/src/liveCache.test.ts \
        packages/force-plotting/src/path.ts apps/force-app/backend/app/d1lc.py \
        apps/force-app/backend/tests/test_d1lc.py
git commit -m "feat(force-plotting,backend): D1LC v2 trailer -- Mz/X/Y/Z, additive and version-gated"
```

Note: `plugins/filter-service/app/d1lc.py` and `scripts/matlab/process_force.m::write_live_cache`
are deliberately **not modified** in this task. The filter-service's `parse()` reads exactly
`n * 6` floats at a fixed offset and never touches anything past that, so a v2 file with a trailer
parses there without error (the trailer is simply never read) — verified by inspection, not
behaviour change. MATLAB stays on v1 until it has extras to write (§4 of the spec).

---

## Task 6: Backend channel model — Mz, Index, the rotating-dyno preset

**Files:**
- Modify: `apps/force-app/backend/app/channels.py`
- Create: `apps/force-app/backend/tests/test_channels.py`

**Interfaces:**
- Produces: `ROLES` (now includes `Mz`, `Index`), `DYNO_STATIONARY`, `DYNO_ROTATING`,
  `ROTATING_ORDER`, `autoassign(devices, kind=DYNO_STATIONARY)`, `dyno_gains(channels, kind=
  DYNO_STATIONARY)`, `to_record_channels(channels, kind=DYNO_STATIONARY)` — the last now raises
  `ValueError` for `kind=DYNO_ROTATING`.

- [ ] **Step 1: Write the failing tests**

```python
# apps/force-app/backend/tests/test_channels.py
"""Channel-model tests: the rotating-dyno preset and its interaction with the fixed
9-column recorder layout. See
docs/superpowers/specs/2026-09-07-milling-path-models-and-polar-design.md #5."""
from __future__ import annotations

import pytest

from app.channels import (
    DYNO_ROTATING,
    DYNO_STATIONARY,
    ROTATING_ORDER,
    autoassign,
    dyno_gains,
    to_record_channels,
)


def _devices_with_n_ai(n: int) -> dict:
    return {
        "chassis": [],
        "standalone": [
            {"ports": [{"kind": "ai", "physical": f"Dev1/ai{i}"} for i in range(n)]}
        ],
    }


def test_autoassign_stationary_is_unchanged_by_default():
    channels = autoassign(_devices_with_n_ai(10))
    names = [c["name"] for c in channels]
    assert names == ["Fx1", "Fx2", "Fy1", "Fy2", "Fz1", "Fz2", "Fz3", "Fz4", "Tacho"]


def test_autoassign_rotating_fills_four_single_components_plus_tacho():
    channels = autoassign(_devices_with_n_ai(10), kind=DYNO_ROTATING)
    names = [c["name"] for c in channels]
    roles = [c["role"] for c in channels]
    assert names == ["Fx", "Fy", "Fz", "Mz", "Tacho"]
    assert roles == ["Fx", "Fy", "Fz", "Mz", "Tacho"]
    physicals = [c["physical"] for c in channels]
    assert physicals == ["Dev1/ai0", "Dev1/ai1", "Dev1/ai2", "Dev1/ai3", "Dev1/ai4"]


def test_to_record_channels_stationary_unchanged():
    channels = autoassign(_devices_with_n_ai(10))
    out = to_record_channels(channels)
    assert len(out) == 9


def test_to_record_channels_rotating_raises():
    channels = autoassign(_devices_with_n_ai(10), kind=DYNO_ROTATING)
    with pytest.raises(ValueError, match="v2"):
        to_record_channels(channels, kind=DYNO_ROTATING)


def test_dyno_gains_stationary_unchanged():
    channels = autoassign(_devices_with_n_ai(10))
    assert dyno_gains(channels) == []  # no gains supplied -> empty, same as today


def test_dyno_gains_rotating_uses_nm_per_v_for_mz():
    channels = autoassign(_devices_with_n_ai(10), kind=DYNO_ROTATING)
    by_name = {c["name"]: c for c in channels}
    for name in ("Fx", "Fy", "Fz"):
        by_name[name]["gain_n_per_v"] = 100.0
    by_name["Mz"]["gain_nm_per_v"] = 5.0
    gains = dyno_gains(channels, kind=DYNO_ROTATING)
    assert gains == [100.0, 100.0, 100.0, 5.0]


def test_rotating_order_is_fx_fy_fz_mz():
    assert ROTATING_ORDER == ["Fx", "Fy", "Fz", "Mz"]
```

- [ ] **Step 2: Run to verify failure**

Run (from `apps/force-app/backend`): `.venv\Scripts\python -m pytest tests/test_channels.py -v`
Expected: FAIL — `DYNO_ROTATING`, `ROTATING_ORDER` don't exist; `autoassign`/`dyno_gains`/
`to_record_channels` don't accept `kind`.

- [ ] **Step 3: Implement**

Replace the full contents of `channels.py`:

```python
"""The arbitrary channel model: named channels with a role, optionally bound to a physical NI-DAQ
input. Roles drive the force maths (all ``Fx`` channels sum into Fx, etc.); ``Tacho`` marks the
speed input; ``Index`` marks a zero-count/tooth-identity pulse (opt-in only -- see the module
docstring note below); ``Aux`` is recorded but not summed. ``source="virtual"`` channels have no
physical binding yet (bindable later).

Two dyno presets:
  - DYNO_STATIONARY ("stationary_8"): today's 4-component plate, Fx1/Fx2/Fy1/Fy2/Fz1..Fz4 summed
    in pairs/quads into Fx/Fy/Fz. Bridges to the recorder's fixed
    [Fx1,Fx2,Fy1,Fy2,Fz1,Fz2,Fz3,Fz4,Tacho] layout.
  - DYNO_ROTATING ("rotating_4"): a rotating cutting-force dynamometer (e.g. Kistler RCD 9170B /
    9123C) -- four SINGLE components Fx, Fy, Fz, Mz, no paired corners to sum. This preset can be
    authored and persisted, but `to_record_channels` refuses to start a recording with it: the
    fixed 9-column layout has no slot for a lone Fx or for Mz. That needs the v2 variable-column
    recorder (see docs/superpowers/specs/2026-07-27-force-capture-v2-schema-design.md), which is
    a separate, larger piece of work -- see
    docs/superpowers/specs/2026-09-07-milling-path-models-and-polar-design.md #5.

``Index`` is never auto-assigned: it needs >=4 kHz sampling against the standard force channels'
~1 kHz anti-aliasing filter (Kistler 9123C manual, chapter 5.8), so binding it is an explicit,
opt-in user action, not something autoassign should guess at.
"""

from __future__ import annotations

from .config import DEFAULT_NIDAQ_CHANNELS, DYNO_CHANNELS, TACHO_CHANNEL

ROLES = ["Fx", "Fy", "Fz", "Mz", "Tacho", "Index", "Aux"]
ROLE_COLOR = {
    "Fx": "#f87171",
    "Fy": "#4ade80",
    "Fz": "#60a5fa",
    "Mz": "#f472b6",
    "Tacho": "#c084fc",
    "Index": "#facc15",
    "Aux": "#fbbf24",
    "Virtual": "#38bdf8",
}

DYNO_STATIONARY = "stationary_8"
DYNO_ROTATING = "rotating_4"

# Force-first default: the first 8 analog inputs become these named channels, in this order.
FORCE_ORDER = list(DYNO_CHANNELS)  # Fx1 Fx2 Fy1 Fy2 Fz1 Fz2 Fz3 Fz4
_ROLE_OF = {n: n[:2] for n in FORCE_ORDER}  # "Fx1" -> "Fx"

# Rotating dyno: four single components, role == name.
ROTATING_ORDER = ["Fx", "Fy", "Fz", "Mz"]


def make_channel(
    name: str,
    role: str,
    physical: str | None = None,
    sensitivity: float | None = None,
    gain: float | None = None,
    source: str = "hardware",
) -> dict:
    return {
        "name": name,
        "role": role,
        "physical": physical,
        "sensitivity_pc_per_n": sensitivity,
        "gain_n_per_v": gain,
        # Mz's gain is N*m/V, a different unit from every other channel's N/V -- kept in its own
        # field rather than overloading gain_n_per_v, which would silently mix units.
        "gain_nm_per_v": None,
        "source": source,
        "color": ROLE_COLOR.get("Virtual" if source == "virtual" else role, "#94a3b8"),
    }


def _ai_ports(devices: dict) -> list[str]:
    """All analog-input physical channel strings, chassis order then slot order."""
    out: list[str] = []
    for ch in devices.get("chassis", []):
        for mod in ch.get("modules", []):
            for p in mod.get("ports", []):
                if p.get("kind") == "ai":
                    out.append(p["physical"])
    for mod in devices.get("standalone", []):
        for p in mod.get("ports", []):
            if p.get("kind") == "ai":
                out.append(p["physical"])
    return out


def autoassign(devices: dict, kind: str = DYNO_STATIONARY) -> list[dict]:
    """Force-first: fill the dyno's channels across the first AI ports, then Tacho on the next
    one. Remaining ports left unassigned.

    kind=DYNO_STATIONARY (default): Fx1..Fz4 across the first 8 AI (ai0 of the next module for
    Tacho when the force channels take whole 4-ch cards) -- unchanged from before this function
    took a `kind` argument.
    kind=DYNO_ROTATING: Fx, Fy, Fz, Mz across the first 4 AI, then Tacho on the 5th. No paired
    corners -- a rotating dyno has one sensor per component.
    """
    ai = _ai_ports(devices)
    if kind == DYNO_ROTATING:
        channels: list[dict] = []
        for i, name in enumerate(ROTATING_ORDER):
            phys = ai[i] if i < len(ai) else None
            channels.append(make_channel(name, name, physical=phys))
        tacho_phys = ai[len(ROTATING_ORDER)] if len(ai) > len(ROTATING_ORDER) else None
        channels.append(make_channel(TACHO_CHANNEL, "Tacho", physical=tacho_phys))
        return channels

    channels = []
    for i, name in enumerate(FORCE_ORDER):
        phys = ai[i] if i < len(ai) else None
        channels.append(make_channel(name, _ROLE_OF[name], physical=phys))
    tacho_phys = ai[8] if len(ai) > 8 else None  # ai0 of the next module
    channels.append(make_channel(TACHO_CHANNEL, "Tacho", physical=tacho_phys))
    return channels


def to_record_channels(channels: list[dict], kind: str = DYNO_STATIONARY) -> list[str]:
    """Ordered physical list for the recorder's fixed [Fx1..Fz4, Tacho] layout. Unbound slots keep
    the placeholder default so a partial config still starts.

    Raises ValueError for kind=DYNO_ROTATING: the fixed 9-column layout has no slot for a single
    Fx or for Mz. A rotating-dyno config can be saved and inspected; starting a recording with one
    needs the v2 variable-column recorder, which does not exist yet.
    """
    if kind == DYNO_ROTATING:
        raise ValueError(
            "rotating-dyno configs need the v2 variable-column recorder; "
            "config is saved but recording is not yet supported"
        )
    by_name = {c["name"]: c for c in channels}
    order = FORCE_ORDER + [TACHO_CHANNEL]
    out: list[str] = []
    for i, name in enumerate(order):
        c = by_name.get(name)
        phys = c.get("physical") if c else None
        out.append(phys or DEFAULT_NIDAQ_CHANNELS[i])
    return out


def dyno_gains(channels: list[dict], kind: str = DYNO_STATIONARY) -> list[float]:
    """Per-channel gains for the dyno's channels, if the config supplies them for ALL of them
    (else empty -> the recorder derives gains from the amp ranges as before).

    kind=DYNO_STATIONARY (default, unchanged): N/V gains for the 8 dyno channels via
    `gain_n_per_v`.
    kind=DYNO_ROTATING: N/V for Fx/Fy/Fz, N*m/V for Mz via the separate `gain_nm_per_v` field --
    the two units are never mixed into one list entry's meaning.
    """
    by_name = {c["name"]: c for c in channels}
    if kind == DYNO_ROTATING:
        gains: list[float | None] = []
        for name in ROTATING_ORDER:
            c = by_name.get(name, {})
            gains.append(c.get("gain_nm_per_v") if name == "Mz" else c.get("gain_n_per_v"))
        return [float(g) for g in gains] if all(g is not None for g in gains) else []

    gains = [by_name.get(n, {}).get("gain_n_per_v") for n in FORCE_ORDER]
    return [float(g) for g in gains] if all(g is not None for g in gains) else []
```

- [ ] **Step 4: Run to verify pass**

Run: `.venv\Scripts\python -m pytest tests/test_channels.py -v`
Expected: PASS (6 tests).

- [ ] **Step 5: Run the full backend suite to confirm nothing else broke**

Run: `.venv\Scripts\python -m pytest tests/ -v`
Expected: all pass, including every pre-existing test in `apps/force-app/backend/tests` (none of
`autoassign`, `to_record_channels`, `dyno_gains` changed their default-argument behaviour).

- [ ] **Step 6: Commit**

```bash
git add apps/force-app/backend/app/channels.py apps/force-app/backend/tests/test_channels.py
git commit -m "feat(backend): rotating-dyno channel preset -- Mz/Index roles, refuses record-start"
```

---

## Task 7: `PolarPlot.vue` — canvas-2D renderer

**Files:**
- Create: `packages/force-plotting/src/PolarPlot.vue`

**Interfaces:**
- Consumes: `Cache` from `./liveCache`; `PolarParams`, `PolarResult`, `buildPolar` from `./polar`;
  `COLORMAPS` from `./liveCloud`.
- Produces: default-exported Vue component with props `cache: Cache | null`, `params: PolarParams`,
  `colormap: string`, `pointSize: number`, `rMax?: number | null`, `paneLabel?: string`, `flutes?:
  number`; emits `loaded: { count: number; dropped: number; rMin: number; rMax: number }`.

- [ ] **Step 1: Implement `PolarPlot.vue`**

There is no meaningful "failing test first" for a canvas-drawing Vue component with no existing
test harness for pixel output in this package (`FrmCloud.vue`, its closest sibling, has none
either — it is verified through the desktop Playwright specs and manual screenshot review
instead). Write the component directly, then verify it via `npm run typecheck` and, at the
acceptance-gate step (Task 9), a manual screenshot through the `run-force-app` skill.

```vue
<script setup lang="ts">
// Canvas-2D polar (torque/force vs spindle angle) plot. Deliberately NOT WebGL: after
// striding, a polar view is thousands of points, not millions, and canvas makes the axis
// furniture (radial grid, spoke labels, colorbar) trivial. See
// docs/superpowers/specs/2026-09-07-milling-path-models-and-polar-design.md #6.
import { computed, nextTick, onMounted, ref, watch } from 'vue';
import type { Cache } from './liveCache';
import { buildPolar, type PolarParams, type PolarResult } from './polar';
import { COLORMAPS } from './liveCloud';

const props = withDefaults(defineProps<{
	cache: Cache | null;
	params: PolarParams;
	colormap: string;
	pointSize: number;
	rMax?: number | null;
	paneLabel?: string;
	/** Number of cutting edges -- draws N equally-spaced spokes so a periodic signal's
	 * lobes are easy to eyeball against tooth count. 0 hides the spoke overlay. */
	flutes?: number;
}>(), { rMax: null, paneLabel: '', flutes: 0 });

const emit = defineEmits<{
	(e: 'loaded', v: { count: number; dropped: number; rMin: number; rMax: number }): void;
}>();

const canvasEl = ref<HTMLCanvasElement | null>(null);
const result = ref<PolarResult | null>(null);
const errorMsg = ref<string | null>(null);

function rebuild() {
	errorMsg.value = null;
	if (!props.cache) { result.value = null; draw(); return; }
	const r = buildPolar(props.cache, props.params);
	result.value = r;
	if (!r) {
		errorMsg.value = props.params.radius === 'Mz' ? 'no torque channel in this capture' : 'no data';
	} else {
		emit('loaded', { count: r.count, dropped: r.dropped, rMin: r.rMin, rMax: r.rMax });
	}
	draw();
}

function draw() {
	const canvas = canvasEl.value;
	if (!canvas) return;
	const rect = canvas.getBoundingClientRect();
	const dpr = Math.min(window.devicePixelRatio || 1, 2);
	const w = Math.max(1, rect.width), h = Math.max(1, rect.height);
	canvas.width = Math.round(w * dpr); canvas.height = Math.round(h * dpr);
	const g = canvas.getContext('2d');
	if (!g) return;
	g.setTransform(dpr, 0, 0, dpr, 0, 0);
	g.clearRect(0, 0, w, h);

	const cx = w / 2, cy = h / 2;
	const radiusPx = Math.min(w, h) / 2 - 28;
	const r = result.value;
	const rMax = props.rMax ?? (r ? r.rMax * 1.05 || 1 : 1);

	// radial grid: 4 rings + spokes every 30deg
	g.strokeStyle = 'rgba(148,163,184,0.35)'; g.fillStyle = 'rgba(148,163,184,0.7)';
	g.font = '10px sans-serif'; g.textAlign = 'center'; g.textBaseline = 'middle';
	for (let ring = 1; ring <= 4; ring++) {
		const rr = (radiusPx * ring) / 4;
		g.beginPath(); g.arc(cx, cy, rr, 0, Math.PI * 2); g.stroke();
	}
	for (let deg = 0; deg < 360; deg += 30) {
		const a = (deg * Math.PI) / 180;
		g.beginPath(); g.moveTo(cx, cy); g.lineTo(cx + radiusPx * Math.cos(a), cy + radiusPx * Math.sin(a)); g.stroke();
	}

	// flute spokes, distinguishable from the 30deg grid
	if (props.flutes > 0) {
		g.strokeStyle = 'rgba(96,165,250,0.6)'; g.lineWidth = 1.5;
		for (let f = 0; f < props.flutes; f++) {
			const a = (f / props.flutes) * Math.PI * 2;
			g.beginPath(); g.moveTo(cx, cy); g.lineTo(cx + radiusPx * Math.cos(a), cy + radiusPx * Math.sin(a)); g.stroke();
		}
		g.lineWidth = 1;
	}

	if (r && r.count > 0) {
		const cm = COLORMAPS[props.colormap] || COLORMAPS.viridis;
		const span = (r.rMax - r.rMin) || 1;
		for (let k = 0; k < r.count; k++) {
			const rr = Math.min(radiusPx, (r.r[k] / rMax) * radiusPx);
			const x = cx + rr * Math.cos(r.phi[k]), y = cy + rr * Math.sin(r.phi[k]);
			const [cr, cg, cb] = cm((r.r[k] - r.rMin) / span);
			g.fillStyle = `rgb(${Math.round(cr * 255)},${Math.round(cg * 255)},${Math.round(cb * 255)})`;
			g.beginPath(); g.arc(x, y, props.pointSize, 0, Math.PI * 2); g.fill();
		}
	}

	// footer: angle-source honesty label -- tacho vs atan2(Fy,Fx) is the difference between a
	// trustworthy plot and a suggestive one, and the viewer must not have to guess which.
	g.fillStyle = 'rgba(226,232,240,0.85)'; g.textAlign = 'left'; g.font = '11px sans-serif';
	const srcLabel = props.params.angle.source === 'tacho' ? 'angle: tacho'
		: props.params.angle.source === 'force_vector' ? 'angle: atan2(Fy,Fx)' : 'angle: index pulse';
	g.fillText(srcLabel, 8, h - 10);
	if (props.paneLabel) { g.textAlign = 'right'; g.fillText(props.paneLabel, w - 8, h - 10); }
}

watch(() => [props.cache, props.params, props.rMax, props.colormap, props.flutes], rebuild, { deep: true });
onMounted(() => { nextTick(rebuild); window.addEventListener('resize', draw); });
</script>

<template>
	<div class="polar-plot">
		<canvas ref="canvasEl" class="polar-canvas"></canvas>
		<div v-if="errorMsg" class="polar-empty">{{ errorMsg }}</div>
	</div>
</template>

<style scoped>
.polar-plot { position: relative; width: 100%; height: 100%; }
.polar-canvas { width: 100%; height: 100%; display: block; }
.polar-empty { position: absolute; inset: 0; display: flex; align-items: center; justify-content: center; color: var(--text-dim); font-size: 13px; pointer-events: none; }
</style>
```

- [ ] **Step 2: Add it to `index.ts`**

```ts
export { default as PolarPlot } from './PolarPlot.vue';
```

- [ ] **Step 3: Typecheck**

Run: `npm run typecheck -w @d1/force-plotting`
Expected: no errors.

- [ ] **Step 4: Commit**

```bash
git add packages/force-plotting/src/PolarPlot.vue packages/force-plotting/src/index.ts
git commit -m "feat(force-plotting): PolarPlot.vue -- canvas-2D torque/force-vs-angle renderer"
```

---

## Task 8: Wire the polar panel into the Record page and its pop-out

**Files:**
- Modify: `apps/force-app/web/src/record/workspace.ts`
- Create: `apps/force-app/web/src/record/panels/PolarPanel.vue`
- Modify: `apps/force-app/web/src/record/RecordPage.vue`
- Modify: `apps/force-app/web/src/record/LivePanelWindow.vue`

**Interfaces:**
- Consumes: `PolarPlot`, `PolarRadius`, `AngleSource` (as re-exported strings), `PolarParams` from
  `@d1/force-plotting`.
- Produces: `plot.polarRadius: PolarRadius`, `plot.polarAngleSource: AngleSource`,
  `plot.polarBins: number` on the workspace's `plot` reactive object; a `polar` entry in
  `PANEL_TYPES`; a `polar` branch in `LivePanelWindow.vue`.

- [ ] **Step 1: Add polar fields to `workspace.ts`**

Read the file first (only the `plot` declaration changes). Replace:

```ts
const plot = reactive<{ forceMode: 'time' | 'fft'; frmAxis: Axis; colormap: string; pointSize: number; windowSec: number; liveFrmStride: number }>({
	forceMode: 'time', frmAxis: 'Fz', colormap: 'viridis', pointSize: 1.8, windowSec: 12, liveFrmStride: 1,
});
```

with:

```ts
const plot = reactive<{
	forceMode: 'time' | 'fft'; frmAxis: Axis; colormap: string; pointSize: number; windowSec: number; liveFrmStride: number;
	polarRadius: 'Mz' | 'Fz' | 'Fxy'; polarAngleSource: 'tacho' | 'force_vector'; polarBins: number;
}>({
	forceMode: 'time', frmAxis: 'Fz', colormap: 'viridis', pointSize: 1.8, windowSec: 12, liveFrmStride: 1,
	polarRadius: 'Fz', polarAngleSource: 'tacho', polarBins: 36,
});
```

(`polarAngleSource` deliberately excludes `'index_pulse'` from its type — that source is not
implemented; see Task 2's `AngleSourceUnavailableError`. Offering it in the UI would let a user
select an option guaranteed to throw.)

- [ ] **Step 2: Write `PolarPanel.vue`**

Mirrors `FrmPanel.vue`'s shape exactly (read that file's `<style>` block and reuse its class names
verbatim so the new panel matches the existing visual language with no new CSS to review):

```vue
<script setup lang="ts">
// Polar panel: torque/force vs spindle angle, live while recording or replaying a finished cut.
// Mirrors FrmPanel.vue's toolbar shape. See
// docs/superpowers/specs/2026-09-07-milling-path-models-and-polar-design.md #6.
import { computed } from 'vue';
import { useWorkspace } from '../workspace';
import { PolarPlot, type PolarParams } from '@d1/force-plotting';
import { appUrl } from '../../appUrl';

const w = useWorkspace();
const RADII = ['Fz', 'Fxy', 'Mz'] as const;
const SOURCES = [
	{ key: 'tacho', label: 'Tacho' },
	{ key: 'force_vector', label: 'atan2(Fy,Fx)' },
] as const;

const cache = computed(() => w.finishedCache.value);

const params = computed<PolarParams>(() => ({
	radius: w.plot.polarRadius,
	angle: {
		source: w.plot.polarAngleSource, ppr: w.cfg.ppr, offsetDeg: 0, direction: 1,
		engagementN: 5,
	},
	window: {
		cropStartSec: cache.value?.csSec ?? 0,
		cropEndSec: cache.value?.ceSec ?? 1e9,
		stride: 1,
	},
	bins: w.plot.polarBins,
}));

function openLive() {
	const q = new URLSearchParams({
		radius: w.plot.polarRadius, angle: w.plot.polarAngleSource,
		colormap: w.plot.colormap, pointSize: String(w.plot.pointSize),
	});
	window.open(appUrl(`/live/polar?${q}`), '_blank', 'noopener,width=1000,height=1000');
}
</script>

<template>
	<div class="frm-panel">
		<div class="frm-controls">
			<div class="segmode">
				<button v-for="r in RADII" :key="r" class="segbtn" :class="{ on: w.plot.polarRadius === r }" @click="w.plot.polarRadius = r">{{ r }}</button>
			</div>
			<select class="cmap" v-model="w.plot.polarAngleSource" title="Angle source">
				<option v-for="s in SOURCES" :key="s.key" :value="s.key">{{ s.label }}</option>
			</select>
			<select class="cmap" v-model="w.plot.colormap" title="Colormap">
				<option v-for="m in ['viridis', 'inferno', 'grayscale']" :key="m">{{ m }}</option>
			</select>
			<button class="popout" title="Pop out to a new window" @click="openLive">
				<span class="material-symbols-rounded">open_in_new</span>
			</button>
		</div>
		<div class="frm-body">
			<PolarPlot v-if="cache" :cache="cache" :params="params" :colormap="w.plot.colormap" :point-size="w.plot.pointSize" />
			<div v-else class="loading">Finish or replay a cut to see its polar plot.</div>
		</div>
	</div>
</template>

<style scoped>
.frm-panel { display: flex; flex-direction: column; height: 100%; min-height: 0; gap: 8px; }
.frm-controls { display: flex; justify-content: flex-end; align-items: center; gap: 8px; flex-wrap: wrap; }
.segmode { display: flex; gap: 4px; margin-right: auto; }
.segbtn { padding: 5px 10px; font-size: 12px; color: var(--text-dim); background: var(--surface); border: 1px solid var(--border); border-radius: 7px; cursor: pointer; }
.segbtn.on { background: var(--accent); color: var(--accent-ink); font-weight: 600; border-color: var(--accent); }
.cmap { padding: 5px 7px; font-size: 12px; color: var(--text); background: var(--surface); border: 1px solid var(--border); border-radius: 7px; }
.popout { display: inline-flex; align-items: center; justify-content: center; width: 26px; height: 26px; border-radius: 7px; background: var(--surface); border: 1px solid var(--border); color: var(--text-dim); cursor: pointer; }
.popout:hover { color: var(--accent); background: var(--surface-2); }
.popout .material-symbols-rounded { font-size: 15px; }
.frm-body { flex: 1; min-height: 0; }
.frm-body > * { height: 100%; }
.loading { display: flex; align-items: center; justify-content: center; height: 100%; color: var(--text-dim); text-align: center; padding: 12px; }
</style>
```

**Live-while-recording is out of scope for this task**: `PolarPanel` only renders once
`w.finishedCache` exists (a finished or replayed cut), the same gate `FrmPanel.vue` uses for its
`FrmCloud` branch. A live-accumulating polar view (the `LiveFrm.vue` equivalent) is not built here
— note it as a follow-up in the plan's final task rather than scope-creeping this one.

- [ ] **Step 3: Register the panel type in `RecordPage.vue`**

Read the file's `PANEL_TYPES` declaration first, then add one entry:

```ts
const PANEL_TYPES: Record<string, { title: string; icon: string; single?: boolean; w: number; h: number }> = {
	options: { title: 'Recording & Metadata', icon: 'tune', single: true, w: 2, h: 28 },
	overview: { title: 'Overview', icon: 'monitoring', w: 4, h: 4 },
	force: { title: 'Force Plot', icon: 'show_chart', w: 6, h: 11 },
	rpm: { title: 'RPM', icon: 'speed', w: 6, h: 7 },
	frm: { title: 'FRM Map', icon: 'fingerprint', w: 4, h: 19 },
	polar: { title: 'Polar Plot', icon: 'radar', w: 4, h: 16 },
};
```

Import `PolarPanel` alongside the other panel imports:

```ts
import PolarPanel from './panels/PolarPanel.vue';
```

Add the branch in the template, after the `FrmPanel` line:

```html
<FrmPanel v-else-if="item.type === 'frm'" />
<PolarPanel v-else-if="item.type === 'polar'" />
```

Do **not** add `polar` to `DEFAULT_LAYOUT` — per the Global Constraints, the default layout is
unchanged; the panel is opt-in via the existing "add panel" menu, which already enumerates every
entry in `PANEL_TYPES` automatically (`addable` computed property).

- [ ] **Step 4: Add the pop-out branch to `LivePanelWindow.vue`**

Read the file first. Add near the top, alongside `isFrm`:

```ts
const isPolar = computed(() => panel.value === 'polar');
```

Add polar-specific query-param state near `frmAxis`:

```ts
const polarRadius = ref<'Fz' | 'Fxy' | 'Mz'>((q.get('radius') as 'Fz' | 'Fxy' | 'Mz') || 'Fz');
const polarAngleSource = ref<'tacho' | 'force_vector'>((q.get('angle') as 'tacho' | 'force_vector') || 'tacho');
```

Extend `title`:

```ts
const title = computed(() => {
	if (isFrm.value) return 'Live FRM Fingerprint';
	if (isPolar.value) return 'Live Polar Plot';
	return 'Live ' + (MODE_LABEL[mode.value] || 'Force');
});
```

Because a pop-out window has no `w.finishedCache` to read (it is a bare route with its own
`RecordClient`, not the workspace), and Task 8 explicitly scoped `PolarPanel`'s live rendering out
for this pass, the pop-out route also does not render a live polar view yet — it shows the same
"finish a cut" placeholder as the embedded panel. Add a template branch alongside the `isFrm`
one that swaps in the radius/source controls and a placeholder body:

```html
<template v-if="isFrm">
	...  <!-- unchanged -->
</template>
<template v-else-if="isPolar">
	<div class="segmode">
		<button v-for="r in (['Fz','Fxy','Mz'] as const)" :key="r" class="segbtn" :class="{ on: polarRadius === r }" @click="polarRadius = r">{{ r }}</button>
	</div>
	<select v-model="polarAngleSource" class="cm">
		<option value="tacho">Tacho</option>
		<option value="force_vector">atan2(Fy,Fx)</option>
	</select>
</template>
<template v-else>
	...  <!-- unchanged -->
</template>
```

And in the body:

```html
<template v-else>
	<LiveFrm v-if="isFrm" :client="client" :diam="80" :colormap="colormap" :point-size="pointSize" :point-stride="initStride" :axis="frmAxis" />
	<div v-else-if="isPolar" class="syncing">Polar pop-out shows a finished/replayed cut — open it from the embedded panel once a cut is done.</div>
	<LiveForcePlot v-else-if="mode === 'time'" :client="client" :channels="channels" />
	...
</template>
```

- [ ] **Step 5: Typecheck the web app**

Run: `npm run typecheck -w force-app-web`
Expected: no errors.

- [ ] **Step 6: Run the force-plotting and web test suites once more**

Run: `npm run test --workspaces`
Expected: all green across every workspace.

- [ ] **Step 7: Commit**

```bash
git add apps/force-app/web/src/record/workspace.ts apps/force-app/web/src/record/panels/PolarPanel.vue \
        apps/force-app/web/src/record/RecordPage.vue apps/force-app/web/src/record/LivePanelWindow.vue
git commit -m "feat(force-app): polar-plot Record panel + /live/polar pop-out

Opt-in via Add Panel, like every other multi-instance panel -- the
default layout is unchanged. Renders once a cut is finished or
replayed; a live-accumulating view is a follow-up."
```

---

## Task 9: Documentation and the full acceptance gate

**Files:**
- Create: `docs/hardware/rotating-dynamometer.md`

- [ ] **Step 1: Write the hardware reference doc**

```markdown
# Rotating cutting-force dynamometer (RCD)

Reference constants pulled from the Kistler manuals read for
`docs/superpowers/specs/2026-09-07-milling-path-models-and-polar-design.md`, so they don't live
only in a PDF. Two devices are covered: the current RCD Type 9170B (wireless) and the older
9123C + 5223B charge-amplifier system (wired, analog).

## Components and ranges (9170B)

4-component: Fx, Fy, Fz, Mz. Coordinate frame **rotates with the tool**.

| | Nominal | Range 1 | Range 2 | Range 3 | Range 4 |
|---|---|---|---|---|---|
| Fx, Fy | -5..5 kN | -0.5..0.5 kN | -1..1 kN | -2.5..2.5 kN | -5..5 kN |
| Fz | -20..20 kN | -2.5..2.5 kN | -5..5 kN | -10..10 kN | -20..20 kN |
| Mz | -210..210 N*m | -10..10 N*m | -20..20 N*m | -50..50 N*m | -100..100 N*m |

Sampling rate 2.5 / 5 / 10 kHz per channel (not separately selectable); resolution 16-bit; max
speed 16,000 1/min. (9170B manual, chapter 10.)

## Feed force is not measured directly

The RCD gives Fx/Fy/Fz/Mz in the **rotating tool frame**. Feed force `Ff` and normal feed force
`FfN` are recovered by rotating Fx/Fy through the immersion angle phi:

```
Ff  =  Fx*sin(phi) + Fy*cos(phi)
FfN = -Fx*cos(phi) + Fy*sin(phi)
```

Only at phi=90 degrees do the rotating and fixed frames coincide (`Ff=Fx`, `FfN=Fy`). See
`packages/force-plotting/src/angle.ts`'s `toFixedFrame`. (9170B manual, chapter 8.1.1, Fig. 36/37.)

## Natural frequency and the tooth-passing rule

Tooth-passing frequency: `f = (n/60) * N`, where `n` is spindle speed in 1/min and `N` is the
number of cutting edges. Keep it below `f_n/5` for <5% amplitude error, or `f_n/3` for <10%.

Natural frequencies: approx. 2000 Hz (X/Y) and approx. 5300 Hz (Z) for a bare 9170B with the
HSK-A63 integrated adapter, no tool. Once installed in a real spindle with a tool attached, the
older 9123C measured 400-500 Hz in practice — the spindle/tool assembly's natural frequency
dominates, not the sensor's own. (9170B manual, chapters 6.3-6.4, 10.1; 9123C manual, chapter 5.4.)

## Drift mechanisms (all three affect Fz most)

- **Centrifugal**: Fz grows with the square of spindle speed (approx. `32,678*n^2 - 52.67*n` N in
  the manual's example, `n` in thousands of rpm) — radial forces Fx/Fy are largely unaffected.
  Minimise by bringing the spindle to speed *before* starting the measurement ("Operate").
- **Temperature**: non-linear drift, Z direction most sensitive. Minimise by thermally
  stabilising the system for at least 30 minutes before measuring, and letting the spindle run at
  the target speed beforehand.
- **Internal coolant pressure**: Fz drifts roughly linearly with coolant pressure, down to about
  -1600 N at 70 bar (the maximum permitted pressure). Minimise by starting coolant flow before
  "Operate" and holding pressure constant during the cut.

(9170B manual, chapter 7.)

## Zero-count / index-pulse channel (9123C + 5223B only)

Channel 6 on the 5223B2 signal conditioner: an infrared light barrier senses a groove on a
rotatable ring, alignable to a specific tool cutting edge — giving tooth *identity*, not just
angle. Needs a minimum 4000 Hz sampling rate, while the force channels 1-5 have a 1000 Hz
anti-aliasing filter — a materially different acquisition path from the force channels.
Not implemented in the force app; see `AngleSourceUnavailableError` in
`packages/force-plotting/src/angle.ts`. (9123C manual, chapters 5.6, 5.8.)

## Analog interface (9123C + 5223B)

+/-10 V on channels 1-5, +5 V on channel 6, D-Sub 15-pole connector, **differential** wiring (the
A/D card must run in DIFFERENTIAL, not SINGLE ENDED, mode to avoid ground-loop problems). RS-232C
for range selection and reset. (9123C manual, chapter 5.8.)
```

- [ ] **Step 2: Commit the doc**

```bash
git add docs/hardware/rotating-dynamometer.md
git commit -m "docs(hardware): rotating dynamometer reference -- ranges, drift, tooth-passing rule"
```

- [ ] **Step 3: Run the full acceptance gate**

From the repo root:

```bash
npm run test --workspaces
npm run typecheck --workspaces
```

Expected: all green. Then, from `apps/force-app/backend`:

```bash
.venv\Scripts\python -m pytest tests/ -v
```

Expected: all green, including the new `test_d1lc.py` and `test_channels.py`.

- [ ] **Step 4: Visual confirmation the FRM map is unchanged**

Use the `run-force-app` skill to launch the desktop app, replay a synthetic cut, and screenshot the
finished FrmCloud view. Compare it by eye against a screenshot taken before Task 4's refactor (or,
if none was captured beforehand, screenshot the current `main` branch's FRM view first, then this
branch's, side by side) — the spiral shape, colour scale, and point density must be indistinguishable.

- [ ] **Step 5: Report results**

State plainly, with the actual command output: which suites ran and passed, which (if any) could
not be run in this environment (e.g. the desktop Playwright specs, if Electron isn't available
here) and why, and whether the visual FRM comparison matched. Do not claim a gate passed without
having run it.
