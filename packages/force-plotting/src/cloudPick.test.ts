import { describe, expect, it } from 'vitest';
import {
	createClickTracker, displayedKeep, findNearestPathIndex, formatPointInfo, octreePathParams, pickNearest, pointInfo, settleRing,
	recentreWindow,
} from './cloudPick';
import type { Cache } from './liveCache';
import { buildPath, type PathParams } from './path';

describe('pickNearest', () => {
	const pts = [{ px: 0, py: 0 }, { px: 10, py: 10 }, { px: 12, py: 10 }, { px: 100, py: 100 }];
	const project = (k: number) => pts[k];
	it('picks the nearest point', () => {
		expect(pickNearest(4, project, 11.5, 10, 20)).toBe(2);
		expect(pickNearest(4, project, 1, 1, 20)).toBe(0);
	});
	it('returns null when nothing is within the radius', () => {
		expect(pickNearest(4, project, 50, 50, 10)).toBeNull();
		expect(pickNearest(4, project, 3, 0, 3)).toBe(0);   // exactly on the radius counts
		expect(pickNearest(4, project, 3.1, 0, 3)).toBeNull();
	});
	it('skips points rejected by keep()', () => {
		expect(pickNearest(4, project, 12, 10, 20, (k) => k !== 2)).toBe(1);
	});
	it('skips points that project to null', () => {
		const p = (k: number) => (k === 2 ? null : pts[k]);
		expect(pickNearest(4, p, 12, 10, 20)).toBe(1);
	});
	it('handles n = 0', () => {
		expect(pickNearest(0, project, 0, 0, 100)).toBeNull();
	});
});

describe('recentreWindow', () => {
	it('returns null when the marker is inside the window', () => {
		expect(recentreWindow(10, 20, 15, 0, 100)).toBeNull();
		expect(recentreWindow(10, 20, 10, 0, 100)).toBeNull();
		expect(recentreWindow(10, 20, 20, 0, 100)).toBeNull();
	});
	it('returns null when not zoomed', () => {
		expect(recentreWindow(null, null, 50, 0, 100)).toBeNull();
		expect(recentreWindow(10, null, 50, 0, 100)).toBeNull();
		expect(recentreWindow(null, 20, 50, 0, 100)).toBeNull();
	});
	it('centres on t keeping the width', () => {
		expect(recentreWindow(10, 20, 50, 0, 100)).toEqual({ start: 45, end: 55 });
	});
	it('shifts instead of shrinking at the left edge', () => {
		expect(recentreWindow(40, 60, 2, 0, 100)).toEqual({ start: 0, end: 20 });
	});
	it('shifts instead of shrinking at the right edge', () => {
		expect(recentreWindow(10, 30, 99, 0, 100)).toEqual({ start: 80, end: 100 });
	});
	it('returns the full range when the width covers it', () => {
		expect(recentreWindow(-5, 105, 200, 0, 100)).toEqual({ start: 0, end: 100 });
		expect(recentreWindow(0, 100, 150, 0, 100)).toEqual({ start: 0, end: 100 });
	});
});

describe('findNearestPathIndex', () => {
	const idx = Int32Array.from([10, 20, 30, 40]);
	it('clamps below and above the path', () => {
		expect(findNearestPathIndex(idx, 4, 0)).toBe(0);
		expect(findNearestPathIndex(idx, 4, 500)).toBe(3);
	});
	it('picks the nearer neighbour between entries', () => {
		expect(findNearestPathIndex(idx, 4, 24)).toBe(1);
		expect(findNearestPathIndex(idx, 4, 26)).toBe(2);
		expect(findNearestPathIndex(idx, 4, 20)).toBe(1);
	});
	it('returns -1 when empty', () => {
		expect(findNearestPathIndex(new Int32Array(0), 0, 5)).toBe(-1);
		expect(findNearestPathIndex(idx, 0, 5)).toBe(-1);
	});
});

function makeCache(withRpm = true): Cache {
	const N = 60;
	const mk = (f: (i: number) => number) => Float32Array.from({ length: N }, (_, i) => f(i));
	return {
		N, Fs: 1000, feed: 0.05, diam: 80, csSec: 0.05, ceSec: 0.5,
		t: mk((i) => i * 0.01), revs: mk((i) => i * 0.03),
		Fx: mk((i) => i + 0.5), Fy: mk((i) => -i), Fz: mk((i) => i * 2),
		rpm: withRpm ? mk(() => 1200) : new Float32Array(0),
	};
}

describe('pointInfo / formatPointInfo', () => {
	it('reads the sample from the cache', () => {
		const c = makeCache();
		const p = pointInfo(c, 7, 1.5, -2.5, 38);
		expect(p.i).toBe(7);
		expect(p.t).toBeCloseTo(0.07, 6);
		expect(p).toMatchObject({ x: 1.5, y: -2.5, rho: 38, Fx: 7.5, Fy: -7, Fz: 14, rpm: 1200 });
	});
	it('omits rho and rpm when unavailable', () => {
		const p = pointInfo(makeCache(false), 3, 0, 0);
		expect('rho' in p).toBe(false);
		expect('rpm' in p).toBe(false);
	});
	it('formats tab-separated key/value lines with units', () => {
		const text = formatPointInfo({ i: 7, t: 0.5, x: 1, y: 2, rho: 3, Fx: 4, Fy: 5, Fz: 6, rpm: 1200 });
		expect(text.split('\n')).toEqual([
			'i\t7', 't (s)\t0.5', 'x (mm)\t1', 'y (mm)\t2', 'rho (mm)\t3',
			'Fx (N)\t4', 'Fy (N)\t5', 'Fz (N)\t6', 'rpm\t1200',
		]);
	});
	it('omits undefined optional fields', () => {
		const text = formatPointInfo({ i: 1, t: 2, x: 3, y: 4, Fx: 5, Fy: 6, Fz: 7 });
		expect(text).not.toContain('rho');
		expect(text).not.toContain('rpm');
		expect(text.split('\n')).toHaveLength(7);
	});
});

describe('octreePathParams', () => {
	it('matches buildPath in a hand-built measured-mode configuration', () => {
		const c = makeCache();
		const { path, window } = octreePathParams(c, 10, 4);
		expect(path).toMatchObject({ kind: 'turning_spiral', speedMode: 'measured', feed: 0.05, diam: 80, innerDiam: 10, ppr: 4, rpm: 1200 });
		expect(window).toEqual({ cropStartSec: 0.05, cropEndSec: 0.5, stride: 1 });

		const hand: PathParams = {
			kind: 'turning_spiral', feed: 0.05, diam: 80, innerDiam: 10,
			speedMode: 'measured', rpm: 0, vc: 0, timeScale: 1, ppr: 4,
		};
		const a = buildPath(c, path, window)!;
		const b = buildPath(c, hand, { cropStartSec: 0.05, cropEndSec: 0.5, stride: 1 })!;
		expect(a.count).toBeGreaterThan(0);
		expect(a.count).toBe(b.count);
		expect(Array.from(a.pos)).toEqual(Array.from(b.pos));
		expect(Array.from(a.idx)).toEqual(Array.from(b.idx));
		// csSec / ceSec share c.t's time base: the path spans exactly the header's window.
		expect(a.idx[0]).toBe(5);
		expect(a.idx[a.count - 1]).toBe(50);
	});
	it('falls back to rpm 0 when the cache carries no rpm', () => {
		const { path } = octreePathParams(makeCache(false), 0, 1);
		expect(path.kind === 'turning_spiral' && path.rpm).toBe(0);
	});
});

describe('displayedKeep', () => {
	const vals = Float32Array.from([1, 5, 9]);
	const idx = Int32Array.from([0, 1, 2]);
	it('is undefined when nothing is hidden', () => {
		expect(displayedKeep(vals, idx, { dispMin: 2, dispMax: 8, greyOutOfRange: true })).toBeUndefined();
		expect(displayedKeep(undefined, idx, { dispMin: 2, dispMax: 8 })).toBeUndefined();
	});
	it('keeps only values inside the displayed range', () => {
		const keep = displayedKeep(vals, idx, { dispMin: 2, dispMax: 8 })!;
		expect([0, 1, 2].map(keep)).toEqual([false, true, false]);
	});
});

describe('createClickTracker', () => {
	const ev = (x: number, y: number, button = 2, pointerType = 'mouse') => ({ clientX: x, clientY: y, button, pointerType }) as PointerEvent;
	it('tells a click from a drag on the right-button release', () => {
		const t = createClickTracker();
		t.down(ev(10, 10)); expect(t.up(ev(12, 11))).toBe(true);
		t.down(ev(10, 10)); expect(t.up(ev(30, 10))).toBe(false);
	});
	it('forgets the press after the release', () => {
		const t = createClickTracker();
		t.down(ev(10, 10)); t.up(ev(10, 10));
		expect(t.up(ev(10, 10))).toBe(false);
	});
	it('ignores other buttons and touch', () => {
		const t = createClickTracker();
		t.down(ev(10, 10, 0)); expect(t.up(ev(10, 10, 0))).toBe(false);
		t.down(ev(10, 10, 2, 'touch')); expect(t.up(ev(10, 10, 2, 'touch'))).toBe(false);
	});
	it('does not open for a release with no recorded press', () => {
		expect(createClickTracker().up(ev(10, 10))).toBe(false);
	});
});

describe('settleRing', () => {
	it('keeps the old object for sub-quarter-pixel moves', () => {
		const cur = { x: 10, y: 10 };
		expect(settleRing(cur, 10.1, 10.2)).toBe(cur);
		expect(settleRing(cur, 11, 10)).toEqual({ x: 11, y: 10 });
		expect(settleRing(null, 1, 2)).toEqual({ x: 1, y: 2 });
	});
});
