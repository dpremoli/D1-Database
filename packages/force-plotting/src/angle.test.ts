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
		for (let i = 0; i < 10; i++) {
			const sum = wrap2pi(fwd[i] + rev[i]);
			const okZero = Math.abs(sum) < 1e-3;
			const okTwoPi = Math.abs(sum - 2 * Math.PI) < 1e-3;
			expect(okZero || okTwoPi).toBe(true);
		}
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
