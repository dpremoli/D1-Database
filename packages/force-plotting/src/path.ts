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
	feed: number;          // mm/rev
	diam: number;           // mm
	innerDiam: number;      // mm — spiral stops here (0 = solid disc)
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
	yOffset: number;    // mm — constant Y for this pass
	zOffset: number;    // mm — constant Z (axial depth reference), informational
}

export interface MachineXyzParams {
	kind: 'machine_xyz';
	xKey: 'X' | 'Y' | 'Z';
	yKey: 'X' | 'Y' | 'Z';
	zKey: 'X' | 'Y' | 'Z';
	scale: number;       // mm per stored unit
	origin: 'first_sample' | 'absolute';
}

export type PathParams = TurningSpiralParams | LinearFeedParams | MachineXyzParams;

export interface PathBounds {
	minX: number; maxX: number;
	minY: number; maxY: number;
	minZ: number; maxZ: number;
}

export interface PathResult {
	pos: Float32Array;   // stride 3 — [x0,y0,z0, x1,y1,z1, ...]
	idx: Int32Array;     // cache index of each emitted point
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

/**
 * Build the tool path for one crop window. Returns null for a degenerate cache
 * (N === 0, empty t, or a crop that selects nothing) — callers MUST handle null.
 */
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
	const src: Record<'X' | 'Y' | 'Z', Float32Array | undefined> = {
		X: (c as any).X, Y: (c as any).Y, Z: (c as any).Z,
	};
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
