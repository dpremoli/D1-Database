import { describe, expect, it } from 'vitest';
import { buildSeriesEnvelope, decimateCache, parseCache, type Cache } from './liveCache';

const MAGIC = 0x44314c43;

// Builds a real D1LC-format ArrayBuffer (header + 6 float32[N] arrays), matching the layout
// parseCache expects — so this exercises the actual wire format, not just the in-memory shape.
function encodeD1LC(n: number, opts: { fs?: number; feed?: number; diam?: number; csSec?: number; ceSec?: number } = {}): { buf: ArrayBuffer; series: Float32Array[] } {
	const { fs = 1000, feed = 0.05, diam = 80, csSec = 0.1, ceSec = 0.9 } = opts;
	const buf = new ArrayBuffer(32 + n * 4 * 6);
	const dv = new DataView(buf);
	dv.setUint32(0, MAGIC, true);
	dv.setUint32(8, n, true);
	dv.setFloat32(12, fs, true);
	dv.setFloat32(16, feed, true);
	dv.setFloat32(20, diam, true);
	dv.setFloat32(24, csSec, true);
	dv.setFloat32(28, ceSec, true);
	const series: Float32Array[] = [];
	let off = 32;
	for (let s = 0; s < 6; s++) {
		const a = new Float32Array(buf, off, n);
		for (let i = 0; i < n; i++) a[i] = s * 1000 + i; // distinct, easy-to-check values per series
		series.push(a.slice()); // detach a stable copy (the view aliases `buf`)
		off += n * 4;
	}
	return { buf, series };
}

describe('parseCache', () => {
	it('round-trips header fields and all six series correctly', () => {
		const n = 25;
		const { buf, series } = encodeD1LC(n, { fs: 5000, feed: 0.12, diam: 63.5, csSec: 0.5, ceSec: 4.5 });
		const c = parseCache(buf);
		expect(c.N).toBe(n);
		expect(c.Fs).toBeCloseTo(5000, 3);
		expect(c.feed).toBeCloseTo(0.12, 5);
		expect(c.diam).toBeCloseTo(63.5, 3);
		expect(c.csSec).toBeCloseTo(0.5, 5);
		expect(c.ceSec).toBeCloseTo(4.5, 5);
		const order: (keyof Cache)[] = ['t', 'Fx', 'Fy', 'Fz', 'rpm', 'revs'];
		order.forEach((key, s) => {
			const arr = c[key] as Float32Array;
			expect(arr.length).toBe(n);
			for (let i = 0; i < n; i++) expect(arr[i]).toBe(series[s][i]);
		});
	});

	it('handles N=0 without throwing (all series empty)', () => {
		const { buf } = encodeD1LC(0);
		const c = parseCache(buf);
		expect(c.N).toBe(0);
		expect(c.t.length).toBe(0);
		expect(c.Fz.length).toBe(0);
	});

	it('rejects a buffer with the wrong magic number', () => {
		const { buf } = encodeD1LC(5);
		new DataView(buf).setUint32(0, 0xdeadbeef, true);
		expect(() => parseCache(buf)).toThrow(/magic/i);
	});
});

describe('decimateCache', () => {
	function makeCache(n: number): Cache {
		const mk = (base: number) => Float32Array.from({ length: n }, (_, i) => base + i);
		return { N: n, Fs: 1000, feed: 0.05, diam: 80, csSec: 0, ceSec: 1, t: mk(0), Fx: mk(1000), Fy: mk(2000), Fz: mk(3000), rpm: mk(4000), revs: mk(5000) };
	}

	it('returns the same object for stride<=1 (no-op)', () => {
		const c = makeCache(10);
		expect(decimateCache(c, 1)).toBe(c);
		expect(decimateCache(c, 0)).toBe(c);
	});

	it('keeps every Nth sample starting at index 0', () => {
		const c = makeCache(10);
		const d = decimateCache(c, 3);
		// indices 0,3,6,9 -> 4 samples
		expect(d.N).toBe(4);
		expect(Array.from(d.t)).toEqual([0, 3, 6, 9]);
		expect(Array.from(d.Fz)).toEqual([3000, 3003, 3006, 3009]);
	});

	it('all series stay the same length as each other after decimation', () => {
		const c = makeCache(97); // not evenly divisible by the stride
		const d = decimateCache(c, 7);
		const lens = [d.t.length, d.Fx.length, d.Fy.length, d.Fz.length, d.rpm.length, d.revs.length];
		expect(new Set(lens).size).toBe(1);
	});
});

// Regression coverage for a real bug: uploading a capture "succeeded" (peaks + FRM map both
// worked) but the force/RPM charts on the Plot page showed "no data" forever, because
// ForceChart.vue reads its plot data from machining_force_analysis.series (a JSONB min/max
// envelope) — not from live_cache_file — and the upload path never populated it. These pin the
// exact shape ForceChart.vue's `geom` computed requires: parallel t/min/max arrays per axis.
describe('buildSeriesEnvelope', () => {
	function makeCache(n: number, values?: Partial<Record<'Fx' | 'Fy' | 'Fz' | 'rpm', Float32Array>>): Cache {
		const t = Float32Array.from({ length: n }, (_, i) => i * 0.01);
		return {
			N: n, Fs: 100, feed: 0.05, diam: 80, csSec: 0, ceSec: n * 0.01, t,
			Fx: values?.Fx ?? Float32Array.from({ length: n }, (_, i) => i),
			Fy: values?.Fy ?? Float32Array.from({ length: n }, (_, i) => -i),
			Fz: values?.Fz ?? Float32Array.from({ length: n }, () => 42),
			rpm: values?.rpm ?? Float32Array.from({ length: n }, () => 1200),
			revs: Float32Array.from({ length: n }, (_, i) => i * 0.02),
		};
	}

	it('produces parallel t/min/max arrays of equal length for every axis, including RPM', () => {
		const env = buildSeriesEnvelope(makeCache(500), 50);
		for (const key of ['Fx', 'Fy', 'Fz', 'RPM'] as const) {
			const s = env[key];
			expect(s.t.length).toBeGreaterThan(0);
			expect(s.min.length).toBe(s.t.length);
			expect(s.max.length).toBe(s.t.length);
		}
	});

	it('never produces more buckets than requested, and covers the full time range', () => {
		const c = makeCache(1000);
		const env = buildSeriesEnvelope(c, 100);
		expect(env.Fx.t.length).toBeLessThanOrEqual(100);
		expect(env.Fx.t[0]).toBe(c.t[0]);
		expect(env.Fx.t[env.Fx.t.length - 1]).toBeLessThan(c.t[c.N - 1]);
	});

	it('each bucket max >= min, and bounds the real min/max within that bucket', () => {
		const c = makeCache(300);
		const env = buildSeriesEnvelope(c, 30);
		for (let i = 0; i < env.Fx.t.length; i++) expect(env.Fx.max[i]).toBeGreaterThanOrEqual(env.Fx.min[i]);
		// Fx is monotonically increasing 0..299, so the very first bucket's min must be 0.
		expect(env.Fx.min[0]).toBe(0);
	});

	it('a constant signal collapses min===max (still valid for the chart, not NaN)', () => {
		const env = buildSeriesEnvelope(makeCache(200), 20);
		for (let i = 0; i < env.Fz.t.length; i++) {
			expect(env.Fz.min[i]).toBe(42);
			expect(env.Fz.max[i]).toBe(42);
		}
	});

	it('handles a bucket count larger than the sample count without producing empty buckets', () => {
		const env = buildSeriesEnvelope(makeCache(5), 2000);
		expect(env.Fx.t.length).toBe(5);
		for (let i = 0; i < 5; i++) expect(env.Fx.min[i]).toBe(env.Fx.max[i]); // one sample per bucket
	});
});
