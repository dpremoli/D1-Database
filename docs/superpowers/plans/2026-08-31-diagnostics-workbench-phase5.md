# Diagnostics Workbench Phase 5 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add pass-to-pass differencing — angular-domain alignment of two cuts, so whatever cancels out between them (the tool/machine signature) is separated from whatever survives (material variation), the highest-information single feature for that distinction.

**Architecture:** A single client-side TypeScript module, not a `scripts/diag/` Python addition — a two-array resample-and-subtract is cheap enough to run in the browser once two WorkingSets are already loaded, unlike the heavy Gi*/HDBSCAN work that genuinely needs server-side precomputation. No new Vue panel/UI, following the precedent Phase 3/4 already set: ship the tested capability, defer new UI until there's a real diag octree to verify it against.

**Tech Stack:** TypeScript, Vitest — no new dependencies.

**Spec:** `docs/superpowers/specs/2026-08-30-diagnostics-workbench-design.md`, continuing `docs/superpowers/plans/2026-08-30-diagnostics-workbench.md`'s "Phase 5 — Pass-to-pass differencing".

## Global Constraints

- This lands in `packages/force-plotting/src/`, not `scripts/diag/` — it is client-side logic, not part of the server-side analysis pipeline.
- Both input signals are assumed already on the same per-revolution sample spacing (`samplesPerRev`) — that is not itself a parameter to validate or reconcile; what varies between two passes is their starting origin and total span, not their internal sample rate.
- `.vue` components in this package are not unit-tested (no `@vue/test-utils`); this task adds no `.vue` file, so that constraint doesn't bind here, but the eventual UI consumer will inherit it.
- No live diag octree exists yet (the pre-existing, unrelated MATLAB/archive regression from the Phase 1 session is still unresolved). Verified with synthetic data.
- Never claim a step passes without running it and reading the output.

---

## File Structure

**New:**

| File | Responsibility |
|---|---|
| `packages/force-plotting/src/compare.ts` | `alignAndDiff` — resample two per-revolution signals onto their shared overlap and subtract |
| `packages/force-plotting/src/compare.test.ts` | Unit tests |

**Modified:**

| File | Change |
|---|---|
| `packages/force-plotting/src/index.ts` | Export `alignAndDiff` and its `AlignedDiff` type |

**Explicitly out of scope:** any Vue component consuming this (a "Compare" mode in `DiagnosticsWorkbench.vue` or a standalone panel) — no real two-cut data exists yet to verify a UI against, same reasoning as every prior phase's UI deferral.

---

### Task 1: `alignAndDiff`

**Files:**
- Create: `packages/force-plotting/src/compare.ts`
- Test: `packages/force-plotting/src/compare.test.ts`

**Interfaces:**
- Consumes: nothing
- Produces:
  - `interface AlignedDiff { rev: Float32Array; aAligned: Float32Array; bAligned: Float32Array; diff: Float32Array; }`
  - `alignAndDiff(revA: Float32Array, sigA: Float32Array, revB: Float32Array, sigB: Float32Array, samplesPerRev: number): AlignedDiff`

- [ ] **Step 1: Write the failing test**

```typescript
// packages/force-plotting/src/compare.test.ts
import { describe, expect, it } from 'vitest';
import { alignAndDiff } from './compare';

const SPR = 256;

// A repeatable "tool signature" waveform -- what a real cut's TSA signature would look like:
// a fundamental plus a harmonic, nothing random. Two passes sharing this exactly is the
// synthetic stand-in for "the tool/machine behaved the same both times".
function makeSignature(revs: Float32Array): Float32Array {
	const out = new Float32Array(revs.length);
	for (let i = 0; i < revs.length; i++) {
		out[i] = Math.sin(2 * Math.PI * revs[i]) + 0.5 * Math.sin(2 * Math.PI * 3 * revs[i]);
	}
	return out;
}

function revGrid(nRev: number, spr: number, offset = 0): Float32Array {
	const n = nRev * spr;
	const out = new Float32Array(n);
	for (let i = 0; i < n; i++) out[i] = offset + i / spr;
	return out;
}

describe('alignAndDiff', () => {
	it('recovers an anomaly present in only one pass, cancelling the shared tool signature', () => {
		// THE ground-truth test: two passes sharing the exact same repeatable waveform, one
		// with an extra anomaly the other never had. The diff must isolate that anomaly and
		// go quiet everywhere the two passes actually agreed.
		const revA = revGrid(20, SPR);
		const sigA = makeSignature(revA);
		const revB = revGrid(20, SPR);
		const sigB = makeSignature(revB);
		const hitIdx = Math.round(10 * SPR);
		sigB[hitIdx] += 5.0;

		const { rev, diff } = alignAndDiff(revA, sigA, revB, sigB, SPR);
		let peakIdx = 0;
		for (let i = 1; i < diff.length; i++) {
			if (Math.abs(diff[i]) > Math.abs(diff[peakIdx])) peakIdx = i;
		}
		expect(Math.abs(rev[peakIdx] - 10.0)).toBeLessThan(0.05);
		expect(Math.abs(diff[peakIdx])).toBeGreaterThan(4.0);
		// away from the anomaly, both passes agree -- the diff should be ~0
		const farIdx = Math.round(2 * SPR);
		expect(Math.abs(diff[farIdx])).toBeLessThan(0.01);
	});

	it('resamples only the overlapping revolution range when passes cover different spans', () => {
		const revA = revGrid(20, SPR, 0); // covers 0..20
		const revB = revGrid(20, SPR, 5); // covers 5..25
		const sigA = makeSignature(revA);
		const sigB = makeSignature(revB);
		const { rev } = alignAndDiff(revA, sigA, revB, sigB, SPR);
		expect(rev[0]).toBeCloseTo(5.0, 2);
		expect(rev[rev.length - 1]).toBeLessThanOrEqual(20.0 + 1e-6);
	});

	it('throws when the two revolution ranges do not overlap at all', () => {
		const revA = revGrid(5, SPR, 0); // 0..5
		const revB = revGrid(5, SPR, 10); // 10..15
		const sigA = makeSignature(revA);
		const sigB = makeSignature(revB);
		expect(() => alignAndDiff(revA, sigA, revB, sigB, SPR)).toThrow(/overlap/);
	});

	it('throws when a rev/sig pair has mismatched lengths', () => {
		const revA = revGrid(5, SPR);
		const sigA = new Float32Array(revA.length - 1);
		const revB = revGrid(5, SPR);
		const sigB = makeSignature(revB);
		expect(() => alignAndDiff(revA, sigA, revB, sigB, SPR)).toThrow(/length/);
	});
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd packages/force-plotting && npx vitest run src/compare.test.ts`
Expected: FAIL — cannot resolve `./compare`

- [ ] **Step 3: Write the implementation**

```typescript
// packages/force-plotting/src/compare.ts
// Pass-to-pass differencing: align two cuts' per-revolution signals onto their shared
// overlapping revolution range and subtract. What's consistent between two passes on the
// same tool/insert is most likely the tool/machine signature; what survives the subtraction
// is more likely material variation -- the highest-information single feature for telling
// those two apart, and cheap enough (one interpolation, one subtraction) to run client-side
// once both passes' WorkingSets are already loaded, unlike the server-side Gi*/HDBSCAN work.

export interface AlignedDiff {
	rev: Float32Array;
	aAligned: Float32Array;
	bAligned: Float32Array;
	diff: Float32Array;
}

// Linear interpolation mirroring numpy's np.interp (the same primitive
// scripts/diag/angular.py's angular_resample already uses server-side): `xp` must be sorted
// ascending; `x` is assumed sorted ascending too (true by construction here, since it's a
// evenly-spaced generated grid), which lets the lookup walk forward with a single pointer
// instead of binary-searching per query point.
function interp(x: Float32Array, xp: Float32Array, fp: Float32Array): Float32Array {
	const out = new Float32Array(x.length);
	let j = 0;
	for (let i = 0; i < x.length; i++) {
		const xi = x[i];
		if (xi <= xp[0]) {
			out[i] = fp[0];
			continue;
		}
		if (xi >= xp[xp.length - 1]) {
			out[i] = fp[fp.length - 1];
			continue;
		}
		while (j < xp.length - 2 && xp[j + 1] < xi) j++;
		const x0 = xp[j];
		const x1 = xp[j + 1];
		const y0 = fp[j];
		const y1 = fp[j + 1];
		const t = (xi - x0) / (x1 - x0);
		out[i] = y0 + t * (y1 - y0);
	}
	return out;
}

export function alignAndDiff(
	revA: Float32Array,
	sigA: Float32Array,
	revB: Float32Array,
	sigB: Float32Array,
	samplesPerRev: number,
): AlignedDiff {
	if (revA.length !== sigA.length) {
		throw new Error(`revA/sigA length mismatch: ${revA.length} vs ${sigA.length}`);
	}
	if (revB.length !== sigB.length) {
		throw new Error(`revB/sigB length mismatch: ${revB.length} vs ${sigB.length}`);
	}
	const lo = Math.max(revA[0], revB[0]);
	const hi = Math.min(revA[revA.length - 1], revB[revB.length - 1]);
	if (hi <= lo) {
		throw new Error(
			`no overlapping revolution range between the two cuts (A: [${revA[0]}, ${revA[revA.length - 1]}], B: [${revB[0]}, ${revB[revB.length - 1]}])`,
		);
	}
	const n = Math.floor((hi - lo) * samplesPerRev);
	if (n < 1) {
		throw new Error('overlapping revolution range too small to resample');
	}
	const rev = new Float32Array(n);
	for (let i = 0; i < n; i++) rev[i] = lo + i / samplesPerRev;

	const aAligned = interp(rev, revA, sigA);
	const bAligned = interp(rev, revB, sigB);
	const diff = new Float32Array(n);
	for (let i = 0; i < n; i++) diff[i] = aAligned[i] - bAligned[i];

	return { rev, aAligned, bAligned, diff };
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd packages/force-plotting && npx vitest run src/compare.test.ts`
Expected: 4 passed

- [ ] **Step 5: Typecheck and commit**

```bash
cd packages/force-plotting && npx vue-tsc --noEmit
git add packages/force-plotting/src/compare.ts packages/force-plotting/src/compare.test.ts
git commit -m "feat(force-plotting): add pass-to-pass differencing (alignAndDiff)"
```

---

### Task 2: Export

**Files:**
- Modify: `packages/force-plotting/src/index.ts`

**Interfaces:**
- Consumes: `alignAndDiff`, `AlignedDiff` (Task 1)
- Produces: package public API addition

- [ ] **Step 1: Add the export**

```typescript
export { alignAndDiff } from './compare';
export type { AlignedDiff } from './compare';
```

- [ ] **Step 2: Typecheck and run the full package suite**

Run: `cd packages/force-plotting && npx vue-tsc --noEmit`
Expected: no errors

Run: `cd packages/force-plotting && npx vitest run`
Expected: all pass, including the 4 new `compare.test.ts` cases alongside the existing suite

- [ ] **Step 3: Commit**

```bash
git add packages/force-plotting/src/index.ts
git commit -m "feat(force-plotting): export alignAndDiff from the package API"
```

---

## Self-Review Notes

**Spec coverage:** The master plan's Phase 5 description ("angular-domain alignment of two cuts and their difference... the highest-information single feature for separating material variation from machine behaviour") is implemented directly in `alignAndDiff`. The "extends the existing multi-pass query pattern in `WearTrend.vue`" clause is explicitly **not** built here — that's UI consuming this capability, and per Global Constraints, UI work is deferred until real two-cut data exists to verify it against, consistent with Phase 3's Panel D and Phase 4's Panel C deferrals.

**Known gap carried forward, not silently dropped:** the UI surface (a "Compare" mode, or `WearTrend.vue` extension) has no task here. Tracked as follow-up work once a real diag octree exists, not forgotten.

**Type consistency check:** `AlignedDiff`'s four fields (`rev`, `aAligned`, `bAligned`, `diff`) are all `Float32Array`, matching the type every other WorkingSet-adjacent array in this package already uses (`selection.ts`'s `WorkingSet`, `diagAttrs.ts`'s `DiagAttrs.columns`) — a future UI consumer can pass a `WorkingSet`'s `rev`/`residZ` arrays straight in without a conversion step.
