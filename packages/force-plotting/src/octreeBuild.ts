// The octree build manifest (`d1_build.json`, published by scripts/force_orchestrator.py next to
// metadata.json): the geometry and cut window the host actually integrated the spiral with. The map
// rebuilds the octree's path from the live cache, so it needs those values, not whatever the row says
// now (inner diameter, ppr and the official crop can all change after a build). Octrees built before
// the manifest existed have none: callers fall back to the cache window and row values.
import type { Cache } from './liveCache';

export interface OctreeBuild {
	feed: number; diam: number; innerDiam: number; ppr: number;   // mm/rev, mm, mm, pulses per rev
	cutStartSec: number; cutEndSec: number;   // the file's Time axis, the same as the live cache's `t`
}

const num = (v: unknown): v is number => typeof v === 'number' && Number.isFinite(v);

/**
 * The manifest as an OctreeBuild, or null for anything that isn't a well-formed schema 1 manifest
 * (wrong schema, a missing or non-finite number, ppr <= 0, an end before the start). Null means
 * "ignore it": a half-trusted manifest would misplace every pick, while the old fallback only misses.
 */
export function parseOctreeBuild(raw: unknown): OctreeBuild | null {
	if (!raw || typeof raw !== 'object') return null;
	const m = raw as Record<string, unknown>;
	if (m.schema !== 1) return null;
	if (!num(m.feed) || !num(m.diam) || !num(m.inner_diam) || !num(m.ppr)
		|| !num(m.cut_start_sec) || !num(m.cut_end_sec)) return null;
	if (m.ppr <= 0 || m.cut_end_sec < m.cut_start_sec) return null;
	return {
		feed: m.feed, diam: m.diam, innerDiam: m.inner_diam, ppr: m.ppr,
		cutStartSec: m.cut_start_sec, cutEndSec: m.cut_end_sec,
	};
}

/** Half a sample: how far before t[0] a build's cut start may be and still land on the cache's first sample. */
export function cacheEpsilon(c: Cache): number {
	return c.N > 1 ? Math.max(1e-6, (c.t[1] - c.t[0]) / 2) : 1e-6;
}

/**
 * Does the live cache reach back to the build's cut start? A crop that starts before the cache does
 * (the cache holds a later window) leaves the spiral's r = 0 anchor without a sample, so nothing can
 * be placed. No build, or an empty cache, is not a conflict.
 */
export function cacheCoversBuild(c: Cache, build: OctreeBuild | null | undefined): boolean {
	return !build || !c.N || build.cutStartSec >= c.t[0] - cacheEpsilon(c);
}

/**
 * The span of time the map can place a sample for: the build's window clipped to the cache's own
 * t range (the cache's range alone without a build). null when the two don't overlap or the cache
 * doesn't cover the build's start.
 */
export function mappableWindow(c: Cache, build?: OctreeBuild | null): { start: number; end: number } | null {
	if (!c.N) return null;
	const lo = c.t[0], hi = c.t[c.N - 1];
	if (!build) return { start: lo, end: hi };
	if (!cacheCoversBuild(c, build)) return null;
	const start = Math.max(lo, build.cutStartSec), end = Math.min(hi, build.cutEndSec);
	return end >= start ? { start, end } : null;
}
