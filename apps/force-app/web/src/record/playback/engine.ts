// Video-style playback of an archived cut. The playhead lives here, in the browser, and fills the
// SAME RecordClient buffers the live WebSocket fills — so every panel renders a replay exactly as
// it renders a live recording, with no panel changes at all.
//
// Nothing is written to disk and no RecordingSession is opened: playback is a viewer, not a
// recording. That is also what makes scrubbing possible — RawWriter is append-only and
// FrmIntegrator carries theta/rho across chunks, so seeking backwards through a real session
// would either corrupt the capture or need integrator state unwound that was never built to unwind.
//
// DETERMINISM: a sample's envelope bin and its FRM point are pure functions of its INDEX, never of
// when it was drawn. That is the whole trick — it makes "seek to t" and "play through to t"
// produce byte-identical buffers, which is the invariant engine.test.ts pins down.
import { reactive } from 'vue';
import type { Cache } from '@d1/force-plotting';
import { SUB_NAMES, type RecordClient } from '../liveClient';
import { createSpectrumClient, type SpectrumClient } from './spectrum';

export interface PlaybackOpts {
	baseUrl: string;
	now?: () => number;
	schedule?: (cb: () => void) => number;
	cancel?: (h: number) => void;
}
export interface PlaybackState {
	loaded: boolean; playing: boolean; tSec: number; duration: number; speed: number; error: string | null;
}
export interface PlaybackEngine {
	load(cache: Cache, o: { ppr: number; stride: number }): void;
	play(): void; pause(): void; toggle(): void;
	seek(tSec: number, o?: { commit?: boolean }): void;
	setSpeed(x: number): void;
	dispose(): void;
	state: PlaybackState;
}

// Envelope bins per second of CUT time. Fixed in cut time (not wall time) so the plot has the same
// density at 0.25x as at 20x, and so bin boundaries fall on fixed sample indices.
const BINS_PER_SEC = 200;
// Trailing window handed to /dsp/spectrum, capped like session.py's _fft_cap.
const FFT_WINDOW_SEC = 1.0;
const FFT_MAX = 200_000;

export function createPlaybackEngine(client: RecordClient, opts: PlaybackOpts): PlaybackEngine {
	const now = opts.now ?? (() => performance.now());
	const schedule = opts.schedule ?? ((cb: () => void) => requestAnimationFrame(cb));
	const cancel = opts.cancel ?? ((h: number) => cancelAnimationFrame(h));

	const state = reactive<PlaybackState>({
		loaded: false, playing: false, tSec: 0, duration: 0, speed: 1, error: null,
	});

	let cache: Cache | null = null;
	let ppr = 1, stride = 1;
	let csIdx = 0, revsCs = 0;         // FRM spiral origin (cache's own detected cut start)
	let binSize = 1;                   // samples per envelope bin
	let cursor = 0;                    // exclusive sample index already rendered
	let frame: number | null = null;
	let lastTick = 0;
	const spectra: SpectrumClient = createSpectrumClient(opts.baseUrl);
	spectra.onReply = (r) => {
		if (!r.f.length) return;
		client.fft = { axis: 'Fz', f: r.f, amp: r.spectra.Fz ?? [], fs: r.fs, spectra: r.spectra };
		client.fftFreq = r.f;
		client.fftHistory.push({ t: state.tSec, spectra: r.spectra });
		if (client.fftHistory.length > client.fftHistCap) client.fftHistory.shift();
		client.fftSeq.value++;
	};
	spectra.onError = (e) => { state.error = e.message; };

	function idxOfTime(sec: number): number {
		if (!cache) return 0;
		const t = cache.t;
		let lo = 0, hi = cache.N - 1;
		if (sec <= t[0]) return 0;
		if (sec >= t[hi]) return cache.N;
		while (lo < hi) { const m = (lo + hi) >> 1; if (t[m] < sec) lo = m + 1; else hi = m; }
		return lo;
	}

	function load(c: Cache, o: { ppr: number; stride: number }) {
		reset();
		if (!c || c.N < 2 || !(c.Fs > 0)) {
			state.loaded = false;
			state.error = 'this cut has too few samples to play';
			return;
		}
		cache = c;
		ppr = o.ppr > 0 ? o.ppr : 1;
		stride = Math.max(1, Math.round(o.stride) || 1);
		csIdx = idxOfTime(c.csSec);
		revsCs = c.revs[csIdx] ?? 0;
		binSize = Math.max(1, Math.round(c.Fs / BINS_PER_SEC));
		state.loaded = true;
		state.error = null;
		state.duration = c.t[c.N - 1];
		state.tSec = 0;
		renderTo(0, false);
	}

	function reset() {
		pause();
		client.reset();
		cursor = 0;
		state.tSec = 0; state.duration = 0; state.loaded = false; state.error = null;
		cache = null;
	}

	// Append samples [i0, i1) to the trace envelope and the FRM cloud. Bin boundaries are fixed
	// multiples of binSize, so this is index-deterministic no matter how the range is chopped up.
	function appendRange(i0: number, i1: number) {
		if (!cache || i1 <= i0) return;
		const c = cache;
		const rho0 = c.diam / 2;
		for (let b0 = Math.floor(i0 / binSize) * binSize; b0 < i1; b0 += binSize) {
			const s = Math.max(b0, i0), e = Math.min(b0 + binSize, i1);
			if (e <= s) continue;
			let fxlo = Infinity, fxhi = -Infinity, fylo = Infinity, fyhi = -Infinity, fzlo = Infinity, fzhi = -Infinity;
			for (let i = s; i < e; i++) {
				const x = c.Fx[i], y = c.Fy[i], z = c.Fz[i];
				if (x < fxlo) fxlo = x; if (x > fxhi) fxhi = x;
				if (y < fylo) fylo = y; if (y > fyhi) fyhi = y;
				if (z < fzlo) fzlo = z; if (z > fzhi) fzhi = z;
			}
			client.trace.t.push(c.t[(s + e - 1) >> 1]);
			client.trace.fx.push([fxlo, fxhi]);
			client.trace.fy.push([fylo, fyhi]);
			client.trace.fz.push([fzlo, fzhi]);
			// The cache carries summed axes only. Sub-channels are the same synthetic split
			// ReplaySource applies server-side (Fx/2, Fy/2, Fz/4); Tacho has no counterpart at all
			// and stays flat — TransportBar labels this so it is never mistaken for real data.
			const sub = client.trace.sub;
			sub.Fx1.push([fxlo / 2, fxhi / 2]); sub.Fx2.push([fxlo / 2, fxhi / 2]);
			sub.Fy1.push([fylo / 2, fyhi / 2]); sub.Fy2.push([fylo / 2, fyhi / 2]);
			for (const k of ['Fz1', 'Fz2', 'Fz3', 'Fz4']) sub[k].push([fzlo / 4, fzhi / 4]);
			sub.Tacho.push([0, 0]);
		}
		// FRM: geometry is a pure function of the sample index given the fixed spiral origin, so
		// this matches liveCloud's `measured` branch exactly and needs no carried state.
		const F = c.feed;
		let n = client.frm.count;
		const first = Math.max(i0, csIdx);
		const off = first - ((first - csIdx) % stride);
		for (let i = Math.max(off, csIdx); i < i1; i += stride) {
			if (i < i0) continue;
			const r = (c.revs[i] - revsCs) / ppr;
			const rho = rho0 - F * r;
			if (rho < 0) break;
			const th = 2 * Math.PI * r;
			client.frm.xy[n * 2] = rho * Math.cos(th);
			client.frm.xy[n * 2 + 1] = rho * Math.sin(th);
			const col = c.Fz[i];
			client.frm.c[n] = col;
			const a = Math.abs(col);
			if (a > client.frm.cAbsMax) client.frm.cAbsMax = a;
			n++;
		}
		client.frm.count = n;
	}

	function trimWindow(tSec: number) {
		const tMin = tSec - client.windowSec;
		let drop = 0;
		const t = client.trace.t;
		while (drop < t.length && t[drop] < tMin) drop++;
		if (drop <= 0) return;
		client.trace.t.splice(0, drop);
		client.trace.fx.splice(0, drop);
		client.trace.fy.splice(0, drop);
		client.trace.fz.splice(0, drop);
		for (const n of SUB_NAMES) client.trace.sub[n].splice(0, drop);
	}

	// Bring the buffers to exactly represent playhead `tSec`. Forward is an append; backward
	// rebuilds from scratch, which is cheap because it is a straight pass over typed arrays.
	function renderTo(tSec: number, requestSpectrum = true, forceSpectrum = false) {
		if (!cache) return;
		const target = idxOfTime(tSec);
		if (target < cursor) {
			client.trace = emptyTrace();
			client.frm.count = 0; client.frm.cAbsMax = 1;
			client.status.peaks = { Fx: 0, Fy: 0, Fz: 0 };
			cursor = 0;
		}
		appendRange(cursor, target);
		cursor = target;
		trimWindow(tSec);

		const c = cache;
		const last = Math.max(0, Math.min(c.N - 1, target - 1));
		let px = client.status.peaks.Fx, py = client.status.peaks.Fy, pz = client.status.peaks.Fz;
		for (let i = Math.max(0, target - 1); i < target; i++) {
			px = Math.max(px, Math.abs(c.Fx[i])); py = Math.max(py, Math.abs(c.Fy[i])); pz = Math.max(pz, Math.abs(c.Fz[i]));
		}
		client.status.peaks = { Fx: px, Fy: py, Fz: pz };
		client.status.tSec = tSec;
		client.status.rpm = c.rpm[last];        // straight from the cache; never re-derived
		client.status.nTotal = target;
		client.frameSeq.value++;

		if (requestSpectrum) {
			const win = Math.min(Math.round(c.Fs * FFT_WINDOW_SEC), FFT_MAX);
			const s0 = Math.max(0, target - win);
			if (target - s0 >= 256) {
				const n = target - s0;
				const buf = new Float32Array(n * 3);
				buf.set(c.Fx.subarray(s0, target), 0);
				buf.set(c.Fy.subarray(s0, target), n);
				buf.set(c.Fz.subarray(s0, target), n * 2);
				spectra.request({ fs: c.Fs, names: ['Fx', 'Fy', 'Fz'], samples: buf, force: forceSpectrum });
			}
		}
	}

	function emptyTrace() {
		const sub: Record<string, [number, number][]> = {};
		for (const n of SUB_NAMES) sub[n] = [];
		return { t: [] as number[], fx: [] as [number, number][], fy: [] as [number, number][], fz: [] as [number, number][], sub };
	}

	function tick() {
		frame = null;
		if (!state.playing || !cache) return;
		const t = now();
		const dt = (t - lastTick) / 1000;
		lastTick = t;
		const next = state.tSec + dt * state.speed;
		if (next >= state.duration) {
			state.tSec = state.duration;
			renderTo(state.duration, true, true);
			pause();
			return;
		}
		state.tSec = next;
		renderTo(next);
		frame = schedule(tick);
	}

	function play() {
		if (!state.loaded || state.playing) return;
		if (state.tSec >= state.duration) { state.tSec = 0; renderTo(0, false); }
		state.playing = true;
		// Panels gate live accumulation on state === 'recording' (see RpmPanel); playback is live
		// data as far as they are concerned. Pausing drops back to 'idle', which is also why the
		// Save dialog never fires — RecordPage only opens it on recording -> finalizing/done/error.
		client.status.state = 'recording';
		lastTick = now();
		frame = schedule(tick);
	}

	function pause() {
		state.playing = false;
		client.status.state = 'idle';
		if (frame !== null) { cancel(frame); frame = null; }
	}

	return {
		state,
		load,
		play,
		pause,
		toggle() { state.playing ? pause() : play(); },
		seek(tSec, o) {
			if (!state.loaded) return;
			const t = Math.max(0, Math.min(state.duration, tSec));
			state.tSec = t;
			renderTo(t, true, o?.commit !== false);
			lastTick = now();
		},
		setSpeed(x) { state.speed = x > 0 ? x : 1; },
		dispose() { pause(); spectra.dispose(); cache = null; },
	};
}
