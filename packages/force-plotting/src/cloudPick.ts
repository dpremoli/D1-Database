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
import { nearestIndex } from './hoverIndex';

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

/**
 * Position k in the ascending idx[0..count) whose cache index is nearest i (ties to the lower
 * k), or -1 when empty. Rings use this because a strided path doesn't hold every cache index.
 */
export function findNearestPathIndex(idx: Int32Array, count: number, i: number): number {
	return count > 0 ? nearestIndex(idx, i, 0, count - 1) : -1;
}

// ---- small pieces both map views share (FrmCloud, FrmOctree) ----

/** Pick radius in CSS px for a given point size: a few px of slack around even the smallest dot. */
export function pickRadius(pointSize: number | undefined, fallback = 1.5): number {
	return Math.max(8, (pointSize || fallback) * 2);
}

/**
 * Tells a right-click from a right-drag (the map views pan on right-drag, and the browser fires
 * `contextmenu` on release either way): record the press, then ask on `contextmenu`.
 */
export function createClickTracker(slopPx = 4) {
	let x = NaN, y = NaN;
	return {
		down(ev: PointerEvent) { if (ev.pointerType === 'mouse' && ev.button === 2) { x = ev.clientX; y = ev.clientY; } },
		/** true unless the right button moved more than slopPx since its press (resets the press). */
		isClick(ev: MouseEvent): boolean {
			const moved = Math.hypot(ev.clientX - x, ev.clientY - y) > slopPx;
			x = y = NaN;
			return !moved;
		},
	};
}

/**
 * The displayed-range hide as a pick filter, or undefined when nothing is hidden: a point whose
 * value is outside [dispMin, dispMax] isn't drawn unless greyOutOfRange (colorizeValues and the
 * map shaders' uDisp/uGreyOOR test), so it must not be pickable either.
 */
export function displayedKeep(
	vals: ArrayLike<number> | undefined, idx: Int32Array,
	s: { dispMin: number; dispMax: number; greyOutOfRange?: boolean },
): ((k: number) => boolean) | undefined {
	if (s.greyOutOfRange || !vals) return undefined;
	return (k) => { const v = vals[idx[k]]; return v >= s.dispMin && v <= s.dispMax; };
}

/** A ring overlay's next position: `cur` itself when it moved < 0.25 px, so idle redraws don't touch reactivity. */
export function settleRing(
	cur: { x: number; y: number } | null, px: number, py: number,
): { x: number; y: number } {
	return cur && Math.abs(cur.x - px) < 0.25 && Math.abs(cur.y - py) < 0.25 ? cur : { x: px, y: py };
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
