import { describe, expect, it } from 'vitest';
import {
	AXIS_MAPS, DEFAULT_AXIS_MAP, computeCuttingMetrics, midWindowDiameter, opKindFromSubtype, parseAxisMap,
	type CuttingInputs,
} from './cuttingMetrics';

// Constant forces: Fx = 200 N, Fy = -100 N, Fz = 600 N (min = max = mean). 1000 rpm throughout.
const axis = (v: number) => ({ n: 100, mean: v, rms: Math.abs(v), std: 0, min: v, max: v, p2p: 0, effBits: null, railLoPct: 0, railHiPct: 0, clipped: false });
const RES = Math.sqrt(200 ** 2 + 100 ** 2 + 600 ** 2);   // 640.3124 N
const baseStats: CuttingInputs['stats'] = {
	windowSec: [0, 0], cacheCropStartSec: 0,
	axes: { Fx: axis(200), Fy: axis(-100), Fz: axis(600) },
	rpm: { mean: 1000, std: 0, min: 1000, max: 1000 },
	resultant: { mean: RES, peak: RES },
};
const inp = (o: Partial<CuttingInputs> = {}): CuttingInputs => ({
	stats: baseStats, axisMap: DEFAULT_AXIS_MAP, opKind: 'turning', diameterMm: 100, feedMmPerRev: 0.1, apMm: 2, ...o,
});

describe('computeCuttingMetrics', () => {
	it('matches the hand calculation for a constant cut', () => {
		const m = computeCuttingMetrics(inp());
		expect(m.resultant.mean.value).toBeCloseTo(640.3124, 4);
		expect(m.Fc.mean.value).toBe(600);
		expect(m.Ff.mean.value).toBe(200);
		expect(m.Fp.mean.value).toBe(100);   // |-100|
		expect(m.Fp.peak.value).toBe(100);
		expect(m.vcMPerMin.value).toBeCloseTo(314.159265, 5);   // pi * 100 mm * 1000 rpm / 1000
		expect(m.pcW.value).toBeCloseTo(3141.59265, 4);          // 600 N * 314.159 m/min / 60
		expect(m.kcMPa.value).toBe(3000);                        // 600 / (2 mm * 0.1 mm/rev)
	});
	it('follows the axis mapping', () => {
		const m = computeCuttingMetrics(inp({ axisMap: { Fc: 'Fx', Ff: 'Fz', Fp: 'Fy' } }));
		expect(m.Fc.mean.value).toBe(200);
		expect(m.kcMPa.value).toBe(1000);
	});
	it('uses the diameter at the window midpoint of the spiral', () => {
		// 60 s window, 1000 rpm, f = 0.01: mid is 30 s => 500 revs => D = 100 - 2 * 0.01 * 500 = 90
		expect(midWindowDiameter(100, 0.01, 1000, 30)).toBeCloseTo(90, 9);
		const m = computeCuttingMetrics(inp({ feedMmPerRev: 0.01, stats: { ...baseStats, windowSec: [0, 60] } }));
		expect(m.diameterMidMm.value).toBeCloseTo(90, 9);
		expect(m.vcMPerMin.value).toBeCloseTo(Math.PI * 90, 9);
	});
	it('reports a window past the disc centre as unavailable', () => {
		const m = computeCuttingMetrics(inp({ feedMmPerRev: 0.1, stats: { ...baseStats, windowSec: [0, 60] } }));
		expect(m.vcMPerMin.value).toBeNull();
		expect(m.pcW.value).toBeNull();
		expect(m.kcMPa.value).toBe(3000);   // kc needs no speed
	});
	it('says why each metric is unavailable when an input is missing', () => {
		const noFeed = computeCuttingMetrics(inp({ feedMmPerRev: null }));
		expect(noFeed.kcMPa).toEqual({ value: null, reason: 'feed not recorded' });
		expect(noFeed.pcW.value).toBeCloseTo(3141.59265, 4);   // power does not need the feed
		expect(computeCuttingMetrics(inp({ apMm: undefined })).kcMPa.reason).toBe('depth of cut not recorded');
		expect(computeCuttingMetrics(inp({ apMm: 0 })).kcMPa.reason).toBe('depth of cut not recorded');
		const noD = computeCuttingMetrics(inp({ diameterMm: 0 }));
		expect(noD.vcMPerMin.reason).toBe('diameter missing');
		expect(noD.pcW.reason).toBe('diameter missing');
		expect(noD.kcMPa.value).toBe(3000);
	});
	it('zero RPM makes speed and power unavailable but not kc or the forces', () => {
		const m = computeCuttingMetrics(inp({ stats: { ...baseStats, rpm: { mean: 0, std: 0, min: 0, max: 0 } } }));
		expect(m.vcMPerMin.reason).toBe('RPM is zero in this window');
		expect(m.pcW.reason).toBe('RPM is zero in this window');
		expect(m.kcMPa.value).toBe(3000);
		expect(m.Fc.mean.value).toBe(600);
	});
	it('milling and unknown ops keep only the resultant', () => {
		for (const kind of ['milling', 'unknown'] as const) {
			const m = computeCuttingMetrics(inp({ opKind: kind }));
			expect(m.resultant.mean.value).toBeCloseTo(640.3124, 4);
			expect(m.Fc.mean.value).toBeNull();
			expect(m.pcW.value).toBeNull();
			expect(m.kcMPa.value).toBeNull();
			expect(m.kcMPa.reason).toMatch(kind === 'milling' ? /milling/ : /unknown/);
		}
	});
	it('uses |min|/|max| for the peak of a signed axis', () => {
		const stats = { ...baseStats, axes: { ...baseStats.axes, Fz: { ...axis(600), min: -900, max: 700 } } };
		expect(computeCuttingMetrics(inp({ stats })).Fc.peak.value).toBe(900);
	});
	it('handles an empty window', () => {
		const e = { ...axis(0), n: 0 };
		const m = computeCuttingMetrics(inp({ stats: { ...baseStats, axes: { Fx: e, Fy: e, Fz: e } } }));
		expect(m.resultant.mean.value).toBeNull();
		expect(m.Fc.mean.value).toBeNull();
	});
});

describe('helpers', () => {
	it('classifies subtypes', () => {
		expect(opKindFromSubtype('MT-Facing')).toBe('turning');
		expect(opKindFromSubtype(' mm-slot')).toBe('milling');
		expect(opKindFromSubtype('')).toBe('unknown');
		expect(opKindFromSubtype(null)).toBe('unknown');
	});
	it('offers six axis mappings and falls back to the default', () => {
		expect(AXIS_MAPS).toHaveLength(6);
		expect(parseAxisMap('Fx/Fz/Fy')).toEqual({ Fc: 'Fx', Ff: 'Fz', Fp: 'Fy' });
		expect(parseAxisMap('nonsense')).toEqual(DEFAULT_AXIS_MAP);
		expect(parseAxisMap(null)).toEqual(DEFAULT_AXIS_MAP);
	});
});
