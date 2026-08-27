import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest';
import { createPlaybackEngine } from './engine';
import { RecordClient } from '../liveClient';
import type { Cache } from '@d1/force-plotting';

// A synthetic cut: 10 s at 100 Hz, constant 600 rpm (=10 rev/s), cut starts at t=0.
function makeCache(n = 1000, fs = 100): Cache {
	const t = new Float32Array(n), Fx = new Float32Array(n), Fy = new Float32Array(n);
	const Fz = new Float32Array(n), rpm = new Float32Array(n), revs = new Float32Array(n);
	for (let i = 0; i < n; i++) {
		t[i] = i / fs;
		Fx[i] = i; Fy[i] = -i; Fz[i] = Math.sin(i / 10) * 100;
		rpm[i] = 600; revs[i] = (600 / 60) * (i / fs);
	}
	return { N: n, Fs: fs, feed: 0.1, diam: 80, csSec: 0, ceSec: (n - 1) / fs, t, Fx, Fy, Fz, rpm, revs };
}

// Fs=1000 makes binSize = round(1000/200) = 5, so envelope bins span several samples — the case
// the Fs=100 fixture above cannot exercise (there binSize == 1 and every bin is one sample).
function makeDenseCache(n = 10000, fs = 1000): Cache {
	const t = new Float32Array(n), Fx = new Float32Array(n), Fy = new Float32Array(n);
	const Fz = new Float32Array(n), rpm = new Float32Array(n), revs = new Float32Array(n);
	for (let i = 0; i < n; i++) {
		t[i] = i / fs;
		// Peak deliberately in the MIDDLE, not at the end: a monotonic ramp would let a
		// last-sample-only peak scan look correct by accident.
		Fx[i] = i === 1234 ? 9999 : Math.sin(i / 7) * 10;
		Fy[i] = -Fx[i];
		Fz[i] = i === 2345 ? -8888 : Math.cos(i / 11) * 10;
		rpm[i] = 600; revs[i] = (600 / 60) * (i / fs);
	}
	return { N: n, Fs: fs, feed: 0.1, diam: 80, csSec: 0, ceSec: (n - 1) / fs, t, Fx, Fy, Fz, rpm, revs };
}

// Deterministic clock + manual frame pump, so no rAF and no wall-clock flake.
function harness() {
	let clock = 0;
	const frames: (() => void)[] = [];
	const client = new RecordClient();
	const engine = createPlaybackEngine(client, {
		baseUrl: 'http://x',
		now: () => clock,
		schedule: (cb) => { frames.push(cb); return frames.length; },
		cancel: () => {},
	});
	const tick = (ms: number) => { clock += ms; const f = frames.shift(); f?.(); };
	return { client, engine, tick, get clock() { return clock; } };
}

beforeEach(() => { vi.stubGlobal('fetch', vi.fn(async () => ({ ok: true, status: 200, json: async () => ({ fs: 100, f: [], spectra: {} }) }) as any)); });
afterEach(() => { vi.unstubAllGlobals(); });

describe('playback engine', () => {
	it('loads a cache and reports its duration without playing', () => {
		const h = harness();
		h.engine.load(makeCache(), { ppr: 1, stride: 1 });
		expect(h.engine.state.loaded).toBe(true);
		expect(h.engine.state.duration).toBeCloseTo(9.99, 2);
		expect(h.engine.state.playing).toBe(false);
		expect(h.engine.state.tSec).toBe(0);
	});

	it('advances the playhead by elapsed x speed', () => {
		const h = harness();
		h.engine.load(makeCache(), { ppr: 1, stride: 1 });
		h.engine.play();
		h.tick(1000);
		expect(h.engine.state.tSec).toBeCloseTo(1.0, 2);
		h.engine.setSpeed(2);
		h.tick(1000);
		expect(h.engine.state.tSec).toBeCloseTo(3.0, 2);
	});

	it('pause freezes the playhead across elapsed time', () => {
		const h = harness();
		h.engine.load(makeCache(), { ppr: 1, stride: 1 });
		h.engine.play(); h.tick(1000);
		h.engine.pause();
		const at = h.engine.state.tSec;
		h.tick(5000);
		expect(h.engine.state.tSec).toBe(at);
	});

	it('SEEK INVARIANT: buffers after seek(t) equal buffers after playing to t', () => {
		const played = harness();
		played.engine.load(makeCache(), { ppr: 1, stride: 1 });
		played.engine.play();
		for (let i = 0; i < 5; i++) played.tick(1000);   // play through to t=5
		played.engine.pause();

		const sought = harness();
		sought.engine.load(makeCache(), { ppr: 1, stride: 1 });
		sought.engine.seek(played.engine.state.tSec);

		expect(sought.client.frm.count).toBe(played.client.frm.count);
		expect(sought.client.frm.xy.slice(0, played.client.frm.count * 2))
			.toEqual(played.client.frm.xy.slice(0, played.client.frm.count * 2));
		expect(sought.client.trace.t).toEqual(played.client.trace.t);
		expect(sought.client.trace.fz).toEqual(played.client.trace.fz);
	});

	it('seeking backwards truncates rather than appending', () => {
		const h = harness();
		h.engine.load(makeCache(), { ppr: 1, stride: 1 });
		h.engine.seek(8);
		const far = h.client.frm.count;
		h.engine.seek(2);
		expect(h.client.frm.count).toBeLessThan(far);
		expect(h.engine.state.tSec).toBe(2);
	});

	it('clamps seeks to [0, duration]', () => {
		const h = harness();
		h.engine.load(makeCache(), { ppr: 1, stride: 1 });
		h.engine.seek(-5);
		expect(h.engine.state.tSec).toBe(0);
		h.engine.seek(9999);
		expect(h.engine.state.tSec).toBeCloseTo(h.engine.state.duration, 5);
	});

	it('stops at the end and reports not playing', () => {
		const h = harness();
		h.engine.load(makeCache(), { ppr: 1, stride: 1 });
		h.engine.play();
		for (let i = 0; i < 15; i++) h.tick(1000);
		expect(h.engine.state.playing).toBe(false);
		expect(h.engine.state.tSec).toBeCloseTo(h.engine.state.duration, 5);
	});

	it('trims the trace to windowSec, like the live path', () => {
		const h = harness();
		h.client.windowSec = 2;
		h.engine.load(makeCache(), { ppr: 1, stride: 1 });
		h.engine.seek(9);
		const t = h.client.trace.t;
		expect(t[0]).toBeGreaterThanOrEqual(9 - 2 - 0.5);
	});

	it('reports running peaks and rpm from the cache, not re-derived', () => {
		const h = harness();
		h.engine.load(makeCache(), { ppr: 1, stride: 1 });
		h.engine.seek(5);
		expect(h.client.status.rpm).toBeCloseTo(600, 5);
		expect(h.client.status.peaks.Fx).toBeGreaterThan(0);
		expect(h.client.status.tSec).toBeCloseTo(5, 5);
	});

	it('rejects a degenerate cache instead of dividing by zero', () => {
		const h = harness();
		const bad = { ...makeCache(1), N: 1 } as Cache;
		h.engine.load(bad, { ppr: 1, stride: 1 });
		expect(h.engine.state.loaded).toBe(false);
		expect(h.engine.state.error).toBeTruthy();
	});

	it('makes no network call other than the spectrum request', () => {
		const h = harness();
		h.engine.load(makeCache(), { ppr: 1, stride: 1 });
		h.engine.seek(5);
		for (const call of (globalThis.fetch as any).mock.calls) {
			expect(String(call[0])).toContain('/dsp/spectrum');
		}
	});
	it('accumulates peaks over the whole range, not just the last sample', () => {
		// Regression: the peak scan looped `for (i = target-1; i < target; i++)` — exactly one
		// sample — so every peak except the newest was ignored.
		const h = harness();
		h.engine.load(makeDenseCache(), { ppr: 1, stride: 1 });
		h.engine.seek(5);   // well past both spikes (i=1234 and i=2345, i.e. t=1.234 / 2.345)
		expect(h.client.status.peaks.Fx).toBeCloseTo(9999, 0);
		expect(h.client.status.peaks.Fz).toBeCloseTo(8888, 0);
	});

	it('reports the same peaks whether played through or sought to', () => {
		const played = harness();
		played.engine.load(makeDenseCache(), { ppr: 1, stride: 1 });
		played.engine.play();
		for (let i = 0; i < 15; i++) played.tick(333);
		played.engine.pause();

		const sought = harness();
		sought.engine.load(makeDenseCache(), { ppr: 1, stride: 1 });
		sought.engine.seek(played.engine.state.tSec);

		expect(sought.client.status.peaks.Fx).toBeCloseTo(played.client.status.peaks.Fx, 3);
		expect(sought.client.status.peaks.Fz).toBeCloseTo(played.client.status.peaks.Fz, 3);
	});

	it('SEEK INVARIANT holds when bins span several samples (binSize > 1)', () => {
		// The Fs=100 fixture gives binSize == 1, which cannot catch bins being split at frame
		// boundaries. At Fs=1000 binSize is 5, and ticks of 333 ms land mid-bin.
		const played = harness();
		played.engine.load(makeDenseCache(), { ppr: 1, stride: 1 });
		played.engine.play();
		for (let i = 0; i < 15; i++) played.tick(333);
		played.engine.pause();

		const sought = harness();
		sought.engine.load(makeDenseCache(), { ppr: 1, stride: 1 });
		sought.engine.seek(played.engine.state.tSec);

		expect(sought.client.trace.t).toEqual(played.client.trace.t);
		expect(sought.client.trace.fz).toEqual(played.client.trace.fz);
		expect(sought.client.frm.count).toBe(played.client.frm.count);
	});

	it('drops spectrogram history that is ahead of the playhead after seeking back', () => {
		// fftHistory feeds the spectrogram/waterfall. Without this, scrubbing back keeps showing
		// spectra from later in the cut.
		const h = harness();
		h.engine.load(makeCache(), { ppr: 1, stride: 1 });
		h.client.fftHistory.push({ t: 1, spectra: {} }, { t: 8, spectra: {} }, { t: 9, spectra: {} });
		h.engine.seek(2);
		expect(h.client.fftHistory.every((e) => e.t <= 2)).toBe(true);
	});

	it('clears a stale spectrum error once a later request succeeds', async () => {
		const f = vi.fn()
			.mockResolvedValueOnce({ ok: false, status: 503, text: async () => 'down' } as any)
			.mockResolvedValue({ ok: true, status: 200, json: async () => ({ fs: 100, f: [1, 2], spectra: { Fz: [1, 2] } }) } as any);
		vi.stubGlobal('fetch', f);
		const h = harness();
		// The dense fixture, not the sparse one: at Fs=100 the trailing window is only 100 samples,
		// under the 256-sample floor, so no spectrum request is ever issued and this would pass
		// vacuously.
		h.engine.load(makeDenseCache(), { ppr: 1, stride: 1 });
		h.engine.seek(5);
		await new Promise((r) => setTimeout(r, 0));
		expect(h.engine.state.error).toBeTruthy();
		h.engine.seek(6);
		await new Promise((r) => setTimeout(r, 0));
		expect(h.engine.state.error).toBeNull();
	});
});
