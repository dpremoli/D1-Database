// Picking and linking helpers shared by the FRM map (FrmCloud, FrmOctree) and the Signals
// charts (ForceChart), so a map point and a moment on a chart can point at each other.
//
// Time is the shared key. The charts plot envelope buckets (a bucket index into
// EnvSeries.t), while the map works in live-cache sample indices (PathResult.idx). The two
// meet through `t`: idxOfTime(cache.t, seconds) turns a chart time into a cache index, and
// cache.t[i] turns a picked point back into a chart time. Decimated caches (compare,
// filtered) keep the true `t`, so the key survives decimation.
//
// Octree points carry no time (only x, y and Fx/Fy/Fz), so an octree pick works by position:
// the octree is built host-side with FIXED geometry (measured tacho speed, auto cut start,
// feed and diameter from the .mat) in the same mm frame as Lite's measured mode, centred on
// the part axis with theta = 0 at the cut start (scripts/matlab/process_force.m:168-176,227
// against the measured branch of path.ts). Rebuilding that path from the live cache with
// octreePathParams() gives every sample an (x, y), which can be projected through the octree
// camera and picked like any other cloud.
import type { Cache } from './liveCache';
import type { PathParams, PathWindow } from './path';

export interface PointInfo {
	i: number;       // cache sample index
	t: number;       // seconds, on the same axis as the charts
	x: number; y: number;   // mm
	rho?: number;    // mm from the part axis (turning spiral only)
	Fx: number; Fy: number; Fz: number;   // N
	rpm?: number;
}

export interface PointMenuEvent {
	clientX: number; clientY: number;
	point: PointInfo | null;   // null: nothing under the cursor, or the pick can't resolve a sample
	reason?: 'gridded' | 'no-cache' | 'outside-crop';   // why the time items are unavailable
}

/**
 * The index k (0..n-1) whose projected screen position is nearest (px, py) and within
 * radiusPx, or null. `project` returns null for a point that isn't drawn; `keep` filters
 * points out (e.g. hidden by the displayed range). Linear scan: it runs over up to ~3M
 * points per right-click, so the loop does nothing beyond the two callbacks.
 */
export function pickNearest(
	n: number, project: (k: number) => { px: number; py: number } | null,
	px: number, py: number, radiusPx: number, keep?: (k: number) => boolean,
): number | null {
	let best = -1, bestD = radiusPx * radiusPx;
	for (let k = 0; k < n; k++) {
		if (keep && !keep(k)) continue;
		const p = project(k);
		if (!p) continue;
		const dx = p.px - px, dy = p.py - py;
		const d = dx * dx + dy * dy;
		if (d <= bestD) { bestD = d; best = k; }
	}
	return best < 0 ? null : best;
}

/** Everything the menu shows or copies for cache sample i, at map position (x, y). */
export function pointInfo(c: Cache, i: number, x: number, y: number, rho?: number): PointInfo {
	const info: PointInfo = { i, t: c.t[i], x, y, Fx: c.Fx[i], Fy: c.Fy[i], Fz: c.Fz[i] };
	if (rho !== undefined) info.rho = rho;
	if (c.rpm && c.rpm.length > i) info.rpm = c.rpm[i];
	return info;
}

/** Tab-separated "key\tvalue" lines (units in the key), for the clipboard. */
export function formatPointInfo(p: PointInfo): string {
	const rows: [string, number][] = [['i', p.i], ['t (s)', p.t], ['x (mm)', p.x], ['y (mm)', p.y]];
	if (p.rho !== undefined) rows.push(['rho (mm)', p.rho]);
	rows.push(['Fx (N)', p.Fx], ['Fy (N)', p.Fy], ['Fz (N)', p.Fz]);
	if (p.rpm !== undefined) rows.push(['rpm', p.rpm]);
	return rows.map(([k, v]) => `${k}\t${v}`).join('\n');
}

/**
 * A chart zoom window of the same width centred on t, clamped into [min, max] (shifted, never
 * shrunk), so a marker that sits off-screen comes into view. null means "leave the zoom
 * alone": not zoomed (start/end null) or t is already inside [start, end].
 */
export function recentreWindow(
	start: number | null, end: number | null, t: number, min: number, max: number,
): { start: number; end: number } | null {
	if (start == null || end == null) return null;
	if (t >= start && t <= end) return null;
	const w = end - start;
	if (w >= max - min) return { start: min, end: max };
	let s = t - w / 2;
	if (s < min) s = min;
	if (s + w > max) s = max - w;
	return { start: s, end: s + w };
}

/** Position k in the ascending idx[0..count) holding exactly cache index i, or -1. */
export function findPathIndex(idx: Int32Array, count: number, i: number): number {
	let lo = 0, hi = count - 1;
	while (lo <= hi) {
		const m = (lo + hi) >> 1, v = idx[m];
		if (v === i) return m;
		if (v < i) lo = m + 1; else hi = m - 1;
	}
	return -1;
}

/**
 * Position k in the ascending idx[0..count) whose cache index is nearest i (ties to the lower
 * k), or -1 when empty. Rings use this because a strided path doesn't hold every cache index.
 */
export function findNearestPathIndex(idx: Int32Array, count: number, i: number): number {
	if (count <= 0) return -1;
	let lo = 0, hi = count - 1;
	while (lo < hi) { const m = (lo + hi) >> 1; if (idx[m] < i) lo = m + 1; else hi = m; }
	// lo is now the first k with idx[k] >= i, or the last k when i is past the end.
	if (lo > 0 && i - idx[lo - 1] <= idx[lo] - i) return lo - 1;
	return lo;
}

/**
 * The path and window that reproduce the octree's own geometry from a live cache: measured
 * tacho speed, the auto cut start, and the feed and diameter the cache header carries (the
 * same values the octree was built with). `rpm` is unused by measured mode; it is set to the
 * last sample's for completeness.
 *
 * Time base: csSec/ceSec are written by process_force.m's write_live_cache as
 * (cutstart-1)/Fs and (cutend-1)/Fs, the times of the cache's first and last window samples,
 * i.e. the same axis as `t` (= tt(idx)). buildPath feeds cropStartSec straight to
 * idxOfTime(c.t, ...), so no conversion is needed.
 */
export function octreePathParams(c: Cache, innerDiam: number, ppr: number): { path: PathParams; window: PathWindow } {
	const rpm = c.rpm && c.rpm.length ? c.rpm[c.rpm.length - 1] : 0;
	return {
		path: {
			kind: 'turning_spiral', feed: c.feed, diam: c.diam, innerDiam,
			speedMode: 'measured', rpm, vc: 0, timeScale: 1, ppr,
		},
		window: { cropStartSec: c.csSec, cropEndSec: c.ceSec, stride: 1 },
	};
}
