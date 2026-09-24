// Coverage for colorScale.ts's pure maths: the linear/symlog normalize<->denormalize round trip,
// the invariants applyParams enforces (symmetrical, always-show-zero), sampleScale's step
// quantisation, and NaN safety -- a NaN reaching a shader as a vertex colour is this codebase's
// most recurring real bug (see liveCloud.test.ts's header), so every boundary here is checked
// against it explicitly rather than assumed.
import { describe, expect, it } from 'vitest';
import {
	applyParams, buildScaleLUT, defaultScale, denormalize, normalize, sampleScale, sampleScaleAt,
	type ColorScale,
} from './colorScale';

function scale(overrides: Partial<ColorScale> = {}): ColorScale {
	return { ...defaultScale(-10, 10), ...overrides };
}

describe('defaultScale', () => {
	it('spans the given range with sane defaults', () => {
		const s = defaultScale(0, 100);
		expect(s).toMatchObject({
			satMin: 0, satMax: 100, dispMin: 0, dispMax: 100,
			colormap: 'viridis', steps: 256, logScale: false, symmetrical: false, alwaysShowZero: false,
			greyOutOfRange: true, barVisible: true,
		});
	});
	it('repairs a degenerate (hi <= lo) range rather than dividing by zero downstream', () => {
		const s = defaultScale(5, 5);
		expect(s.satMax).toBeGreaterThan(s.satMin);
		const s2 = defaultScale(5, 2);
		expect(s2.satMax).toBeGreaterThan(s2.satMin);
	});
});

describe('applyParams', () => {
	it('is a no-op when no shaping params are set and the range is already valid', () => {
		const s = scale({ satMin: -3, satMax: 7 });
		expect(applyParams(s, -100, 100)).toEqual(s);
	});
	it('symmetrical forces satMin = -satMax using the larger magnitude', () => {
		const s = applyParams(scale({ symmetrical: true, satMin: -2, satMax: 9 }), 0, 0);
		expect(s.satMax).toBe(9);
		expect(s.satMin).toBe(-9);
	});
	it('alwaysShowZero widens a range that does not already contain zero', () => {
		const above = applyParams(scale({ alwaysShowZero: true, satMin: 2, satMax: 9 }), 0, 0);
		expect(above.satMin).toBe(0); expect(above.satMax).toBe(9);
		const below = applyParams(scale({ alwaysShowZero: true, satMin: -9, satMax: -2 }), 0, 0);
		expect(below.satMin).toBe(-9); expect(below.satMax).toBe(0);
	});
	it('alwaysShowZero is a no-op when zero is already inside the range', () => {
		const s = applyParams(scale({ alwaysShowZero: true, satMin: -5, satMax: 5 }), 0, 0);
		expect(s.satMin).toBe(-5); expect(s.satMax).toBe(5);
	});
	it('symmetrical and alwaysShowZero together are consistent (symmetrical already contains zero)', () => {
		const s = applyParams(scale({ symmetrical: true, alwaysShowZero: true, satMin: 3, satMax: 8 }), 0, 0);
		expect(s.satMin).toBe(-8); expect(s.satMax).toBe(8);
	});
	it('repairs a degenerate saturation range from the supplied data bounds', () => {
		const s = applyParams(scale({ satMin: 4, satMax: 4 }), -50, 50);
		expect(s.satMin).toBe(-50); expect(s.satMax).toBe(50);
	});
	it('falls back to 0..1 when both the scale and the data bounds are degenerate', () => {
		const s = applyParams(scale({ satMin: 4, satMax: 4 }), 4, 4);
		expect(s.satMax).toBeGreaterThan(s.satMin);
	});
	it('repairs a degenerate displayed range by resetting it to the saturation range', () => {
		const s = applyParams(scale({ satMin: -10, satMax: 10, dispMin: 3, dispMax: 3 }), 0, 0);
		expect(s.dispMin).toBe(-10); expect(s.dispMax).toBe(10);
	});
	it('never auto-widens a displayed range the user set deliberately', () => {
		const s = applyParams(scale({ satMin: -10, satMax: 10, dispMin: -2, dispMax: 4 }), 0, 0);
		expect(s.dispMin).toBe(-2); expect(s.dispMax).toBe(4);
	});
});

describe('normalize (linear)', () => {
	const s = scale({ satMin: -10, satMax: 10, logScale: false });
	it('maps the endpoints to 0 and 1', () => {
		expect(normalize(-10, s)).toBe(0);
		expect(normalize(10, s)).toBe(1);
	});
	it('maps the midpoint to 0.5', () => {
		expect(normalize(0, s)).toBeCloseTo(0.5, 10);
	});
	it('clamps values outside the saturation range', () => {
		expect(normalize(-999, s)).toBe(0);
		expect(normalize(999, s)).toBe(1);
	});
	it('is NaN-safe: a non-finite value normalizes to 0, never NaN', () => {
		expect(normalize(NaN, s)).toBe(0);
		expect(normalize(Infinity, s)).toBe(0);
	});
	it('does not divide by zero on a degenerate saturation range', () => {
		const deg = scale({ satMin: 5, satMax: 5 });
		expect(Number.isNaN(normalize(5, deg))).toBe(false);
	});
});

describe('normalize (symlog)', () => {
	const s = scale({ satMin: -100, satMax: 100, logScale: true });
	it('still maps the endpoints to 0 and 1', () => {
		expect(normalize(-100, s)).toBeCloseTo(0, 6);
		expect(normalize(100, s)).toBeCloseTo(1, 6);
	});
	it('maps zero to the midpoint on a range symmetric about zero', () => {
		expect(normalize(0, s)).toBeCloseTo(0.5, 6);
	});
	it('is monotonically increasing (a defining property of a valid colour ramp position)', () => {
		const samples = [-100, -50, -10, -1, 0, 1, 10, 50, 100];
		const positions = samples.map((v) => normalize(v, s));
		for (let i = 1; i < positions.length; i++) expect(positions[i]).toBeGreaterThan(positions[i - 1]);
	});
	it('expands near-zero detail relative to the linear mapping (the whole point of log scale)', () => {
		const lin = scale({ satMin: -100, satMax: 100, logScale: false });
		// A small value near zero moves FURTHER from the midpoint under symlog than under a linear
		// mapping (v=5 out of +-100 barely nudges a linear position, but symlog gives it real visual
		// separation) -- that expanded near-zero contrast is exactly what log scale is for.
		const linGap = Math.abs(normalize(5, lin) - 0.5);
		const logGap = Math.abs(normalize(5, s) - 0.5);
		expect(logGap).toBeGreaterThan(linGap);
	});
});

describe('normalize <-> denormalize round trip', () => {
	it('is an exact inverse under a linear scale', () => {
		const s = scale({ satMin: -30, satMax: 70, logScale: false });
		for (const t of [0, 0.1, 0.25, 0.5, 0.75, 0.9, 1]) {
			expect(normalize(denormalize(t, s), s)).toBeCloseTo(t, 9);
		}
	});
	it('is an exact inverse under a symlog scale, including a range that does not span zero', () => {
		const s = scale({ satMin: -40, satMax: 200, logScale: true });
		for (const t of [0, 0.1, 0.25, 0.5, 0.75, 0.9, 1]) {
			expect(normalize(denormalize(t, s), s)).toBeCloseTo(t, 6);
		}
		const positive = scale({ satMin: 5, satMax: 500, logScale: true });
		for (const t of [0, 0.3, 0.6, 1]) {
			expect(normalize(denormalize(t, positive), positive)).toBeCloseTo(t, 6);
		}
	});
	it('denormalize recovers the saturation endpoints at t=0 and t=1', () => {
		const s = scale({ satMin: -17, satMax: 43, logScale: true });
		expect(denormalize(0, s)).toBeCloseTo(-17, 6);
		expect(denormalize(1, s)).toBeCloseTo(43, 6);
	});
});

describe('sampleScale', () => {
	it('returns a finite [r,g,b] in 0..1 across the full domain, never NaN', () => {
		const s = scale();
		for (let i = 0; i <= 20; i++) {
			const [r, g, b] = sampleScale(i / 20, s);
			for (const c of [r, g, b]) {
				expect(Number.isFinite(c)).toBe(true);
				expect(c).toBeGreaterThanOrEqual(0);
				expect(c).toBeLessThanOrEqual(1);
			}
		}
	});
	it('quantises to `steps` distinct colours -- coarse steps visibly band the ramp', () => {
		const s = scale({ steps: 4 });
		const seen = new Set<string>();
		for (let i = 0; i <= 100; i++) seen.add(sampleScale(i / 100, s).map((c) => c.toFixed(4)).join(','));
		expect(seen.size).toBeLessThanOrEqual(4);
	});
	it('a full-resolution scale (steps=256) is effectively continuous over a coarse sample', () => {
		const s = scale({ steps: 256 });
		const seen = new Set<string>();
		for (let i = 0; i <= 20; i++) seen.add(sampleScale(i / 20, s).map((c) => c.toFixed(4)).join(','));
		expect(seen.size).toBeGreaterThan(4);
	});
	it('falls back to viridis for an unknown colormap name rather than throwing', () => {
		const s = scale({ colormap: 'not-a-real-map' });
		expect(() => sampleScale(0.5, s)).not.toThrow();
	});
});

describe('sampleScaleAt', () => {
	it('agrees with calling normalize then sampleScale directly', () => {
		const s = scale({ satMin: -5, satMax: 5 });
		expect(sampleScaleAt(2, s)).toEqual(sampleScale(normalize(2, s), s));
	});
});

describe('buildScaleLUT', () => {
	it('produces an RGBA8 buffer of the requested width with alpha always opaque', () => {
		const s = scale();
		const lut = buildScaleLUT(s, 32);
		expect(lut.length).toBe(32 * 4);
		for (let i = 0; i < 32; i++) expect(lut[i * 4 + 3]).toBe(255);
	});
	it('defaults to a 256-wide texture', () => {
		expect(buildScaleLUT(scale()).length).toBe(256 * 4);
	});
	it('the first and last entries match the colour at the saturation endpoints', () => {
		const s = scale({ satMin: -10, satMax: 10 });
		const lut = buildScaleLUT(s, 16);
		const [r0, g0, b0] = sampleScaleAt(-10, s);
		const [r1, g1, b1] = sampleScaleAt(10, s);
		expect(lut[0]).toBeCloseTo(Math.round(r0 * 255), 0);
		expect(lut[1]).toBeCloseTo(Math.round(g0 * 255), 0);
		expect(lut[2]).toBeCloseTo(Math.round(b0 * 255), 0);
		const last = 15;
		expect(lut[last * 4]).toBeCloseTo(Math.round(r1 * 255), 0);
		expect(lut[last * 4 + 1]).toBeCloseTo(Math.round(g1 * 255), 0);
		expect(lut[last * 4 + 2]).toBeCloseTo(Math.round(b1 * 255), 0);
	});
	it('never produces NaN/undefined bytes, even on a degenerate saturation range', () => {
		const s = scale({ satMin: 5, satMax: 5 });
		const lut = buildScaleLUT(s, 8);
		for (let i = 0; i < lut.length; i++) {
			expect(Number.isFinite(lut[i])).toBe(true);
		}
	});
	it('log scale produces visibly fewer distinct colours than steps at a coarse count (banding)', () => {
		const s = scale({ satMin: -100, satMax: 100, logScale: true, steps: 8 });
		const lut = buildScaleLUT(s, 256);
		const seen = new Set<string>();
		for (let i = 0; i < 256; i++) seen.add(`${lut[i * 4]},${lut[i * 4 + 1]},${lut[i * 4 + 2]}`);
		expect(seen.size).toBeLessThanOrEqual(8);
	});
});
