import { describe, expect, it } from 'vitest';
import { shaderZ, timeInPath } from './octreePick';

describe('shaderZ', () => {
	it('is 0 when flat', () => { expect(shaderZ(5, 0, 10, 0)).toBe(0); });
	it('maps the range onto +-zScale/2', () => {
		expect(shaderZ(0, 0, 10, 20)).toBe(-10);
		expect(shaderZ(10, 0, 10, 20)).toBe(10);
		expect(shaderZ(5, 0, 10, 20)).toBe(0);
	});
	it('clamps outside the range', () => {
		expect(shaderZ(-50, 0, 10, 20)).toBe(-10);
		expect(shaderZ(50, 0, 10, 20)).toBe(10);
	});
	it('survives a degenerate range', () => { expect(Number.isFinite(shaderZ(1, 1, 1, 20))).toBe(true); });
});

describe('timeInPath', () => {
	const t = Float32Array.from([0, 1, 2, 3, 4, 5]);
	const idx = Int32Array.from([1, 2, 3, 4]);
	it('is inclusive of the first and last sample', () => {
		expect(timeInPath(t, idx, 4, 1)).toBe(true);
		expect(timeInPath(t, idx, 4, 4)).toBe(true);
	});
	it('rejects times outside, and an empty path', () => {
		expect(timeInPath(t, idx, 4, 0.5)).toBe(false);
		expect(timeInPath(t, idx, 4, 4.5)).toBe(false);
		expect(timeInPath(t, idx, 0, 2)).toBe(false);
	});
});
