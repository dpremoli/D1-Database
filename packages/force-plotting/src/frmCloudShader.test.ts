// Correctness gate for the Phase-5 GPU rewrite: computeSpiralVertexJS (the shader's exact JS
// mirror) must reproduce buildPath's buildTurningSpiral output byte-for-byte-ish (float
// tolerance only) at every crop window this test tries, INCLUDING a narrowed one — that's the
// case a naive per-vertex discard could get wrong if the crop-start-anchored phase (revsCs/tCs)
// weren't recomputed per window. See frmCloudShader.ts's top comment for the monotonicity/
// contiguous-prefix assumptions this relies on (checked against real caches before writing this).
import { describe, expect, it } from 'vitest';
import { buildPath, type TurningSpiralParams } from './path';
import { idxOfTime, type Cache } from './liveCache';
import { computeSpiralVertexJS, type SpiralUniformParams } from './frmCloudShader';

function makeCache(): Cache {
	const N = 2000;
	const t = Float32Array.from({ length: N }, (_, i) => i * 0.01);
	// A realistic non-uniform-but-monotonic revs curve (spindle ramps up then holds), never
	// decreasing — matches what the real-cache probe found (see frmCloudShader.ts).
	const revs = Float32Array.from({ length: N }, (_, i) => {
		const rampSamples = 200;
		return i < rampSamples ? 0.02 * (i * i) / rampSamples : 0.02 * rampSamples + 0.6 * (i - rampSamples);
	});
	const mk = (f: (i: number) => number) => Float32Array.from({ length: N }, (_, i) => f(i));
	return {
		N, Fs: 100, feed: 0.05, diam: 80, csSec: 0, ceSec: (N - 1) * 0.01,
		t, revs,
		Fx: mk((i) => Math.sin(i * 0.05) * 30), Fy: mk((i) => Math.cos(i * 0.05) * 30),
		Fz: mk((i) => Math.sin(i * 0.08) * 50 + 10), rpm: mk(() => 1200),
	};
}

const cache = makeCache();

function checkWindow(
	pathParams: TurningSpiralParams, cropStartSec: number, cropEndSec: number, label: string,
) {
	const path = buildPath(cache, pathParams, { cropStartSec, cropEndSec, stride: 1 });
	expect(path, `${label}: expected a non-null path`).not.toBeNull();
	if (!path) return;
	const cs = idxOfTime(cache.t, cropStartSec);
	const uParams: SpiralUniformParams = {
		feed: pathParams.feed, diam: pathParams.diam, innerDiam: pathParams.innerDiam,
		speedMode: pathParams.speedMode, rpm: pathParams.rpm, vc: pathParams.vc,
		timeScale: pathParams.timeScale, ppr: pathParams.ppr,
		tCs: cache.t[cs], revsCs: cache.revs[cs],
	};
	// Every point buildPath actually emitted must be visible in the shader mirror, at the same
	// (x,y), within float tolerance.
	for (let k = 0; k < path.count; k++) {
		const i = path.idx[k];
		const v = computeSpiralVertexJS(cache.t[i], cache.revs[i], uParams, cropStartSec, cropEndSec);
		expect(v.visible, `${label} @k=${k} (i=${i}) should be visible`).toBe(true);
		expect(v.x).toBeCloseTo(path.pos[k * 3], 4);
		expect(v.y).toBeCloseTo(path.pos[k * 3 + 1], 4);
	}
	// The sample immediately after where buildPath stopped (whether by cropEnd or the
	// inner-diameter break) must be invisible in the shader mirror — confirms the discard
	// boundary lines up, not just the retained points.
	const lastEmittedIdx = path.idx[path.count - 1];
	if (lastEmittedIdx + 1 < cache.N) {
		const i = lastEmittedIdx + 1;
		const v = computeSpiralVertexJS(cache.t[i], cache.revs[i], uParams, cropStartSec, cropEndSec);
		if (cache.t[i] > cropEndSec) expect(v.visible, `${label}: past cropEnd should be invisible`).toBe(false);
		// (if it stopped on the inner-diameter break instead, this next sample's rho may still
		// legitimately be >= innerR by a hair depending on cache shape — only assert the
		// unambiguous cropEnd case here; the inner-diameter boundary is covered by the
		// donut-cut case below via an explicit rho check instead.)
	}
}

describe('frmCloudShader: computeSpiralVertexJS matches buildTurningSpiral', () => {
	const base: TurningSpiralParams = {
		kind: 'turning_spiral', feed: 0.05, diam: 80, innerDiam: 0,
		speedMode: 'measured', rpm: 1200, vc: 0, timeScale: 1, ppr: 1,
	};

	it('full window, measured mode', () => checkWindow(base, 0, 1e9, 'full-measured'));
	it('narrowed window (crop start dragged inward)', () => checkWindow(base, 5, 12, 'narrowed'));
	it('narrowed-to-30% window near the end of the cut', () => checkWindow(base, 15, 19.99, 'narrow-30pct'));
	it('rpm mode, narrowed window', () =>
		checkWindow({ ...base, speedMode: 'rpm', rpm: 900 }, 3, 10, 'rpm-narrowed'));
	it('vc mode, narrowed window', () =>
		checkWindow({ ...base, speedMode: 'vc', vc: 120 }, 3, 10, 'vc-narrowed'));
	it('donut cut (inner diameter stops the spiral early)', () => {
		const donut = { ...base, diam: 80, innerDiam: 40 };
		checkWindow(donut, 0, 1e9, 'donut-full');
		// explicit inner-diameter boundary check: the first sample past where buildPath stopped
		// must have rho < innerR in the shader mirror too (not just "invisible for some reason").
		const path = buildPath(cache, donut, { cropStartSec: 0, cropEndSec: 1e9, stride: 1 });
		const lastIdx = path!.idx[path!.count - 1];
		if (lastIdx + 1 < cache.N) {
			const uParams: SpiralUniformParams = {
				feed: donut.feed, diam: donut.diam, innerDiam: donut.innerDiam, speedMode: donut.speedMode,
				rpm: donut.rpm, vc: donut.vc, timeScale: donut.timeScale, ppr: donut.ppr,
				tCs: cache.t[0], revsCs: cache.revs[0],
			};
			const v = computeSpiralVertexJS(cache.t[lastIdx + 1], cache.revs[lastIdx + 1], uParams, 0, 1e9);
			expect(v.rho).toBeLessThan(20);   // innerR = innerDiam/2 = 20
		}
	});
	it('narrowed window with a non-zero crop start still anchors r=0 at the new start (rho=rho0)', () => {
		const path = buildPath(cache, base, { cropStartSec: 5, cropEndSec: 1e9, stride: 1 });
		expect(path).not.toBeNull();
		// first emitted point is exactly at the crop-start sample -> r=0 -> rho=rho0=40
		expect(Math.hypot(path!.pos[0], path!.pos[1])).toBeCloseTo(40, 3);
	});
});
