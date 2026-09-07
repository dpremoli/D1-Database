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
	} as CloudParams;
}

// Each case name documents which axis of the matrix it exercises.
const CASES: [string, Partial<CloudParams>][] = [
	['measured-raw', {}],
	['rpm-model', { speedMode: 'rpm', rpm: 900 } as Partial<CloudParams>],
	['vc-model', { speedMode: 'vc', vc: 120 } as Partial<CloudParams>],
	['gridded', { gridding: true, gridN: 12 }],
	['stride-5', { stride: 5 }],
	['inner-diam-20', { innerDiam: 20 } as Partial<CloudParams>],
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
