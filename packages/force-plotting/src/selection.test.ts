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
		// Compare through Float32Array on both sides -- 0.1..0.5 aren't exactly representable
		// in float32, so a plain float64 literal array would fail toEqual on rounding alone.
		expect(Array.from(ws.tsaResid)).toEqual(Array.from(new Float32Array([0.1, 0.2, 0.3, 0.4, 0.5])));
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
