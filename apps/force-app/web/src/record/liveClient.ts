// Live recording client: opens the recorder WebSocket, decodes D1LF binary frames, and keeps
// rolling buffers the live widgets draw from. Scalars are reactive (readouts); the bulk trace/FRM
// buffers are plain arrays (redrawn each animation frame) to avoid per-sample reactivity overhead.
import { reactive, ref } from 'vue';
import { getConfig } from '../config';
import { authHeaders } from '../directusClient';
import type { RecordConfig } from './types';

const MAGIC = 0x46_4c_31_44; // 'D1LF' bytes D,1,L,F read little-endian as a u32
// The 8 dyno sub-channels the frame streams (min/max envelope), in raw-file column order.
export const SUB_NAMES = ['Fx1', 'Fx2', 'Fy1', 'Fy2', 'Fz1', 'Fz2', 'Fz3', 'Fz4', 'Tacho'] as const;
export type SubName = (typeof SUB_NAMES)[number];

// Raw-file geometry, for size/bandwidth estimates. The writer emits float32 rows (d1rw.py dtype
// "<f4"; recovery.py reads row_bytes = n_cols * 4) of Time + 8 dyno channels + Tacho. Keep these
// in step with backend/app/storage.py's RAW_BYTES_PER_SAMPLE — guessing float64 here silently
// doubled every size readout and disk-space warning.
export const RAW_BYTES_PER_SAMPLE = 4;
export const RAW_COLUMNS = 10;
type Env = [number, number][];
function emptyTrace() {
	const sub: Record<string, Env> = {};
	for (const n of SUB_NAMES) sub[n] = [];
	return { t: [] as number[], fx: [] as Env, fy: [] as Env, fz: [] as Env, sub };
}

export interface LiveStatus {
	connected: boolean;
	state: 'idle' | 'recording' | 'finalizing' | 'done' | 'error';
	seq: number;
	tSec: number;
	rpm: number;
	peaks: { Fx: number; Fy: number; Fz: number };
	nTotal: number;
	error: string | null;
	captureId: string | null;
	summary: any | null;
	cutStartSec: number | null;   // detected cut start (2f) — null until the cut begins
	diskAction: { action: 'backup_started' | 'backup_unavailable' | 'forced_stop'; freeGb: number } | null;
}

export class RecordClient {
	status = reactive<LiveStatus>({
		connected: false, state: 'idle', seq: 0, tSec: 0, rpm: 0,
		peaks: { Fx: 0, Fy: 0, Fz: 0 }, nTotal: 0, error: null, captureId: null, summary: null, cutStartSec: null,
		diskAction: null,
	});
	// bump each frame so widgets can watch cheaply
	frameSeq = ref(0);
	// latest live spectra (published a few times a second by the backend); fftSeq bumps on update.
	// `spectra` holds an amplitude spectrum per channel (Fx/Fy/Fz + the 8 dyno subs); `amp`/`axis`
	// stay for the single-axis fallback. `fftHistory` is a rolling stack of recent spectra frames
	// the spectrogram/waterfall views draw from (accumulated client-side; only current frames cross).
	fft: { axis: string; f: number[]; amp: number[]; fs: number; spectra: Record<string, number[]> } | null = null;
	fftFreq: number[] = [];
	fftHistory: { t: number; spectra: Record<string, number[]> }[] = [];
	fftHistCap = 220;
	fftSeq = ref(0);

	// rolling trace envelope (min/max per axis + per dyno sub-channel), capped to windowSec.
	trace = emptyTrace();
	windowSec = 12;

	// FRM points, preallocated; filled incrementally. count = live points; cCap for colour scaling
	private cap = 2_000_000;
	// cLo/cHi: optional percentile-based colour bounds, set once by playback (which has the whole
	// cut up front and can match the finished-cut view's colour scale exactly) and left undefined
	// for a true live recording (which cannot know its own final range ahead of time and falls
	// back to cAbsMax's running-max, symmetric-about-zero scheme — see LiveFrm.vue's frame()).
	frm = { xy: new Float32Array(this.cap * 2), c: new Float32Array(this.cap), count: 0, cAbsMax: 1, cLo: undefined as number | undefined, cHi: undefined as number | undefined };

	private ws: WebSocket | null = null;
	private base = getConfig().recorderUrl;
	get baseUrl() { return this.base; }
	private relay: BroadcastChannel | null = null;
	// Whether a pop-out window has ever announced itself on the channel. Until one does, relaying
	// every decoded frame is pure overhead on the acquisition PC (a structured clone per frame, at
	// full frame rate, that nothing receives) — and the common case is that no pop-out is open.
	private hasRelayPeer = false;

	// Build the absolute ws(s):// stream URL. `base` may be an absolute http(s) URL (dev, e.g.
	// http://localhost:8200) or a same-origin relative path (deploy, /recorder proxied by Caddy).
	// WebSocket() rejects relative URLs, so resolve a relative base against the page origin.
	private streamUrl(): string {
		const path = this.base + '/record/stream';
		if (/^wss?:/.test(path)) return path;
		if (/^https?:/.test(path)) return path.replace(/^http/, 'ws');
		const scheme = location.protocol === 'https:' ? 'wss' : 'ws';
		return `${scheme}://${location.host}${path.startsWith('/') ? '' : '/'}${path}`;
	}

	connect() {
		const ws = new WebSocket(this.streamUrl());
		ws.binaryType = 'arraybuffer';
		ws.onopen = () => { this.status.connected = true; };
		ws.onclose = () => { this.status.connected = false; };
		ws.onerror = () => { this.status.error = 'stream connection error'; };
		ws.onmessage = (ev) => {
			if (typeof ev.data === 'string') this.onControl(JSON.parse(ev.data));
			else this.onFrame(ev.data as ArrayBuffer);
			if (this.hasRelayPeer) {
				this.relay?.postMessage(ev.data instanceof ArrayBuffer ? { bin: new Uint8Array(ev.data) } : { txt: ev.data });
			}
		};
		this.ws = ws;
		// Close any channel from a previous connect() before replacing it — reconnecting otherwise
		// leaks the old BroadcastChannel, which stays subscribed and keeps its handler alive.
		this.relay?.close();
		this.relay = new BroadcastChannel('force-app-live');
		this.relay.onmessage = (ev) => {
			if (ev.data?.type === 'sync-request') {
				// A pop-out exists: send it the backlog, and start relaying live frames from here on.
				this.hasRelayPeer = true;
				this.sendSnapshot();
			}
		};
	}

	snapshotReady = ref(false);

	connectViaRelay() {
		this.relay?.close();  // same leak guard as connect()
		this.relay = new BroadcastChannel('force-app-live');
		this.relay.onmessage = (ev) => {
			const d = ev.data;
			if (d?.bin) { const u8 = new Uint8Array(d.bin); this.onFrame(u8.buffer as ArrayBuffer); }
			else if (d?.txt) this.onControl(JSON.parse(d.txt));
			else if (d?.type === 'snapshot') {
				this.applySnapshot(d);
				this.snapshotReady.value = true;
			}
		};
		this.status.connected = true;
		this.relay.postMessage({ type: 'sync-request' });
		// The parent might not exist/respond (e.g. this window was opened standalone, or the parent
		// tab closed) — don't leave the pop-out stuck on "Syncing…" forever if no snapshot ever comes.
		setTimeout(() => { this.snapshotReady.value = true; }, 2000);
	}

	// `this.status` is a Vue reactive() proxy — its nested objects (peaks/summary/diskAction) are
	// themselves lazily-wrapped reactive proxies on access, so a shallow `{ ...this.status }` copies
	// those nested PROXIES by reference, not plain objects. Proxies aren't structured-clonable, so
	// postMessage()ing that shape throws DataCloneError — which was silently swallowed by the catch
	// below (whose OWN fallback made the exact same mistake, so it threw too, uncaught, and the
	// child never got anything at all, just its 2s timeout). A full JSON round-trip strips every
	// level of proxy-ness at once; safe here since LiveStatus is plain JSON-shaped data (no Dates,
	// Maps, or typed arrays inside it — those live in frm/trace/fft, which are already plain class
	// fields, not reactive-wrapped, so their own .slice()s were never the problem).
	private plainStatus(): LiveStatus {
		return JSON.parse(JSON.stringify(this.status));
	}

	private sendSnapshot() {
		try {
			const fm = this.frm;
			const n = fm.count;
			const snap = {
				type: 'snapshot',
				status: this.plainStatus(),
				frm: { xy: fm.xy.slice(0, n * 2), c: fm.c.slice(0, n), count: n, cAbsMax: fm.cAbsMax, cLo: fm.cLo, cHi: fm.cHi },
				trace: { t: this.trace.t.slice(), fx: this.trace.fx.slice(), fy: this.trace.fy.slice(), fz: this.trace.fz.slice(),
					sub: Object.fromEntries(Object.entries(this.trace.sub).map(([k, v]) => [k, v.slice()])) },
				fft: this.fft ? { ...this.fft } : null,
				fftFreq: this.fftFreq.slice(),
				fftHistory: this.fftHistory.slice(),
			};
			this.relay?.postMessage(snap);
		} catch (e) {
			console.warn('[force-app] snapshot sync to pop-out window failed:', e);
			this.relay?.postMessage({ type: 'snapshot', status: this.plainStatus(), frm: { xy: new Float32Array(0), c: new Float32Array(0), count: 0, cAbsMax: 1 }, trace: null, fft: null, fftFreq: [], fftHistory: [] });
		}
	}

	private applySnapshot(snap: any) {
		if (snap.status) { Object.assign(this.status, snap.status); }
		if (snap.frm) {
			const n = snap.frm.count || 0;
			if (n > 0) {
				const xy = snap.frm.xy instanceof Float32Array ? snap.frm.xy : Float32Array.from(snap.frm.xy);
				const c = snap.frm.c instanceof Float32Array ? snap.frm.c : Float32Array.from(snap.frm.c);
				if (xy.length >= n * 2 && c.length >= n) {
					this.frm.xy.set(xy, 0);
					this.frm.c.set(c, 0);
					this.frm.count = n;
					this.frm.cAbsMax = snap.frm.cAbsMax;
					this.frm.cLo = snap.frm.cLo; this.frm.cHi = snap.frm.cHi;
				} else {
					console.warn('[force-app] snapshot frm data too small: need xy[', n * 2, '], c[', n, ']');
				}
			}
		}
		if (snap.trace) {
			this.trace.t = snap.trace.t; this.trace.fx = snap.trace.fx;
			this.trace.fy = snap.trace.fy; this.trace.fz = snap.trace.fz;
			this.trace.sub = snap.trace.sub;
		}
		if (snap.fft) this.fft = snap.fft;
		if (snap.fftFreq) this.fftFreq = snap.fftFreq;
		if (snap.fftHistory?.length) { this.fftHistory = snap.fftHistory; this.fftSeq.value++; }
		this.frameSeq.value++;
	}

	disconnect() { this.ws?.close(); this.ws = null; this.relay?.close(); this.relay = null; this.hasRelayPeer = false; }

	private onControl(msg: any) {
		if (msg.type === 'done') {
			this.status.state = msg.state;
			this.status.error = msg.error ?? null;
			this.status.captureId = msg.id ?? this.status.captureId;
			this.status.summary = msg.summary ?? null;
		} else if (msg.type === 'fft') {
			const spectra: Record<string, number[]> = msg.spectra ?? (msg.axis ? { [msg.axis]: msg.amp ?? [] } : {});
			this.fft = { axis: msg.axis, f: msg.f, amp: msg.amp ?? spectra[msg.axis] ?? [], fs: msg.fs ?? 0, spectra };
			this.fftFreq = msg.f ?? this.fftFreq;
			this.fftHistory.push({ t: this.status.tSec, spectra });
			if (this.fftHistory.length > this.fftHistCap) this.fftHistory.shift();
			this.fftSeq.value++;
		} else if (msg.type === 'cutstart') {
			this.status.cutStartSec = msg.t;
		} else if (msg.type === 'disk_action') {
			this.status.diskAction = { action: msg.action, freeGb: msg.free_gb };
		}
	}

	private onFrame(buf: ArrayBuffer) {
		const dv = new DataView(buf);
		if (dv.getUint32(0, true) !== MAGIC) return;
		const seq = dv.getUint32(8, true);
		const tSec = dv.getFloat32(12, true);
		const rpm = dv.getFloat32(16, true);
		const pfx = dv.getFloat32(20, true), pfy = dv.getFloat32(24, true), pfz = dv.getFloat32(28, true);
		const nTotal = dv.getUint32(32, true);
		const nTrace = dv.getUint32(36, true);
		const nSub = dv.getUint32(40, true);
		const nPts = dv.getUint32(44, true);

		this.status.seq = seq; this.status.tSec = tSec; this.status.rpm = rpm;
		this.status.peaks = { Fx: pfx, Fy: pfy, Fz: pfz }; this.status.nTotal = nTotal;
		if (this.status.state === 'idle') this.status.state = 'recording';

		let off = 48;
		const trace = new Float32Array(buf, off, nTrace * 7);
		off += nTrace * 7 * 4;
		const sub = nSub ? new Float32Array(buf, off, nTrace * nSub * 2) : null;
		off += nSub ? nTrace * nSub * 2 * 4 : 0;
		const pts = new Float32Array(buf, off, nPts * 3);

		const nSubUse = Math.min(nSub, SUB_NAMES.length);
		for (let i = 0; i < nTrace; i++) {
			const b = i * 7;
			this.trace.t.push(trace[b]);
			this.trace.fx.push([trace[b + 1], trace[b + 2]]);
			this.trace.fy.push([trace[b + 3], trace[b + 4]]);
			this.trace.fz.push([trace[b + 5], trace[b + 6]]);
			if (sub) {
				const sb = i * nSub * 2;
				for (let j = 0; j < nSubUse; j++) this.trace.sub[SUB_NAMES[j]].push([sub[sb + j * 2], sub[sb + j * 2 + 1]]);
			}
		}
		// drop points older than the window
		const tMin = tSec - this.windowSec;
		let drop = 0;
		while (drop < this.trace.t.length && this.trace.t[drop] < tMin) drop++;
		if (drop > 0) {
			this.trace.t.splice(0, drop); this.trace.fx.splice(0, drop);
			this.trace.fy.splice(0, drop); this.trace.fz.splice(0, drop);
			for (const n of SUB_NAMES) this.trace.sub[n].splice(0, drop);
		}

		const start = this.frm.count;
		const room = this.cap - start;
		const take = Math.min(nPts, room);
		for (let i = 0; i < take; i++) {
			const s = i * 3;
			this.frm.xy[(start + i) * 2] = pts[s];
			this.frm.xy[(start + i) * 2 + 1] = pts[s + 1];
			const c = pts[s + 2];
			this.frm.c[start + i] = c;
			const a = Math.abs(c);
			if (a > this.frm.cAbsMax) this.frm.cAbsMax = a;
		}
		this.frm.count = start + take;
		this.frameSeq.value++;
	}

	// ---- control REST ----
	async start(cfg: RecordConfig) {
		this.reset();
		const res = await fetch(this.base + '/record/start', {
			method: 'POST',
			headers: { 'Content-Type': 'application/json', ...authHeaders() },
			body: JSON.stringify(cfg),
		});
		if (!res.ok) throw new Error(`start failed: ${res.status} ${(await res.text()).slice(0, 200)}`);
		const j = await res.json();
		this.status.state = 'recording';
		this.status.captureId = j.id;
	}

	// NOTE: there is deliberately no startReplay() here any more. Replaying an archived cut is
	// PLAYBACK — a local playhead over the cut (record/playback/engine.ts) that writes nothing —
	// not a recording session, so nothing in the app posts /record/start_replay. That endpoint does
	// still exist and stays covered by backend/tests/test_replay.py: it drives real data through
	// the whole acquisition pipeline, which is useful as a pipeline test. This client method was
	// its only caller and had none of its own left, so it went rather than lingering as a second,
	// untested way to start a replay that behaves nothing like the transport controls.

	async stop() {
		const res = await fetch(this.base + '/record/stop', { method: 'POST', headers: { ...authHeaders() } });
		if (res.ok) {
			const j = await res.json();
			this.status.state = j.state;
			this.status.captureId = j.id ?? this.status.captureId;
			this.status.summary = j.summary ?? this.status.summary;
		}
	}

	reset() {
		this.trace = emptyTrace();
		this.frm = { xy: new Float32Array(this.cap * 2), c: new Float32Array(this.cap), count: 0, cAbsMax: 1, cLo: undefined, cHi: undefined };
		this.fft = null; this.fftHistory = []; this.fftSeq.value++;
		this.status.state = 'idle'; this.status.error = null; this.status.summary = null;
		this.status.captureId = null; this.status.nTotal = 0; this.status.tSec = 0;
		this.status.peaks = { Fx: 0, Fy: 0, Fz: 0 }; this.status.cutStartSec = null;
		this.status.diskAction = null;
		this.frameSeq.value++;
	}

	cacheUrl(id: string) { return `${this.base}/captures/${id}/live_cache.bin`; }
	matUrl(id: string) { return `${this.base}/captures/${id}/capture.mat`; }
}
