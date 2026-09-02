import { describe, expect, it } from 'vitest';
import type { DiagAttrs } from './diagAttrs';
import { clusterStats, computeStats, matches, workingSetFromD1an } from './selection';
import type { Selection } from './selection';

function makeAttrs(): DiagAttrs {
	// 5 points spiralling outward in r. Two clusters (0, 1) plus one noise point (-1).
	return {
		n: 5,
		columns: {
			t: new Float32Array([0, 1, 2, 3, 4]),
			rev: new Float32Array([0, 1, 2, 3, 4]),
			x: new Float32Array([10, 12, 14, 16, 18]),
			y: new Float32Array([0, 0, 0, 0, 0]),
			tsa_resid: new Float32Array([0.1, 0.2, 0.3, 0.4, 0.5]),
			resid_z: new Float32Array([-5, -1, 0, 1, 5]),
			gi_star: new Float32Array([-2, 0, 0, 1, 4]),
			gi_sig: new Float32Array([1, 0, 0, 0, 1]),
			cluster_id: new Float32Array([0, 0, -1, 1, 1]),
			glosh: new Float32Array([0.9, 0.1, 0.5, 0.2, 0.8]),
			env_band: new Float32Array([0, 0, 0, 0, 0]),
		},
	};
}

describe('workingSetFromD1an', () => {
	it('maps all snake_case D1AN columns to the WorkingSet shape', () => {
		const ws = workingSetFromD1an(makeAttrs());
		expect(ws.n).toBe(5);
		expect(Array.from(ws.residZ)).toEqual([-5, -1, 0, 1, 5]);
		expect(Array.from(ws.giSig)).toEqual([1, 0, 0, 0, 1]);
		expect(Array.from(ws.clusterId)).toEqual([0, 0, -1, 1, 1]);
		expect(Array.from(ws.tsaResid)).toEqual(Array.from(new Float32Array([0.1, 0.2, 0.3, 0.4, 0.5])));
	});

	it('throws when a required column is missing', () => {
		const attrs = makeAttrs();
		delete attrs.columns.gi_star;
		expect(() => workingSetFromD1an(attrs)).toThrow(/gi_star/);
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

	it('attribute selection works on any channel', () => {
		const onZ: Selection = { kind: 'attribute', column: 'residZ', min: -1, max: 1 };
		expect([0, 1, 2, 3, 4].map((i) => matches(ws, onZ, i))).toEqual([false, true, true, true, false]);
		const onGi: Selection = { kind: 'attribute', column: 'giStar', min: 0.5, max: 10 };
		expect([0, 1, 2, 3, 4].map((i) => matches(ws, onGi, i))).toEqual([false, false, false, true, true]);
	});

	it('cluster selection matches one cluster id', () => {
		const sel: Selection = { kind: 'cluster', id: 1 };
		expect([0, 1, 2, 3, 4].map((i) => matches(ws, sel, i))).toEqual([false, false, false, true, true]);
	});

	it('lasso selection matches points inside the polygon', () => {
		const sel: Selection = { kind: 'lasso', polygon: [[11, -1], [13, -1], [13, 1], [11, 1]] };
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
		expect(s.meanResidZ).toBeCloseTo(0, 6);
	});

	it('returns a zeroed result for an empty selection rather than NaN', () => {
		const s = computeStats(ws, { kind: 'time', t0: 100, t1: 200 });
		expect(s).toEqual({ n: 0, tMin: 0, tMax: 0, rMin: 0, rMax: 0, meanResidZ: 0 });
	});
});

describe('clusterStats', () => {
	const ws = workingSetFromD1an(makeAttrs());

	it('summarises each cluster with the noise row last and fractions summing to 1', () => {
		const rows = clusterStats(ws);
		expect(rows.map((r) => r.id)).toEqual([0, 1, -1]); // 0 and 1 both n=2, noise (-1) forced last
		expect(rows.reduce((s, r) => s + r.fraction, 0)).toBeCloseTo(1, 6);
		const c1 = rows.find((r) => r.id === 1)!;
		expect(c1.n).toBe(2);
		expect(c1.maxGiStar).toBe(4);
		expect(c1.meanAbsResidZ).toBeCloseTo(3, 6); // (|1| + |5|) / 2
	});

	it('handles an all-noise WorkingSet', () => {
		const attrs = makeAttrs();
		attrs.columns.cluster_id = new Float32Array([-1, -1, -1, -1, -1]);
		const rows = clusterStats(workingSetFromD1an(attrs));
		expect(rows).toHaveLength(1);
		expect(rows[0].id).toBe(-1);
		expect(rows[0].n).toBe(5);
	});
});
