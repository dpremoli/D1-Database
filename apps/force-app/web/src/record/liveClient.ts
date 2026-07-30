// Live recording client: opens the recorder WebSocket, decodes D1LF binary frames, and keeps
// rolling buffers the live widgets draw from. Scalars are reactive (readouts); the bulk trace/FRM
// buffers are plain arrays (redrawn each animation frame) to avoid per-sample reactivity overhead.
import { reactive, ref } from 'vue';
import { getConfig } from '../config';
import { authHeaders } from '../directusClient';
import type { RecordConfig } from './types';

const MAGIC = 0x46_4c_31_44; // 'D1LF' bytes D,1,L,F read little-endian as a u32

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
}

export class RecordClient {
	status = reactive<LiveStatus>({
		connected: false, state: 'idle', seq: 0, tSec: 0, rpm: 0,
		peaks: { Fx: 0, Fy: 0, Fz: 0 }, nTotal: 0, error: null, captureId: null, summary: null,
	});
	// bump each frame so widgets can watch cheaply
	frameSeq = ref(0);

	// rolling trace envelope (min/max per axis), capped to windowSec of wall-time
	trace = { t: [] as number[], fx: [] as [number, number][], fy: [] as [number, number][], fz: [] as [number, number][] };
	windowSec = 12;

	// FRM points, preallocated; filled incrementally. count = live points; cCap for colour scaling
	private cap = 2_000_000;
	frm = { xy: new Float32Array(this.cap * 2), c: new Float32Array(this.cap), count: 0, cAbsMax: 1 };

	private ws: WebSocket | null = null;
	private base = getConfig().recorderUrl;

	connect() {
		const url = this.base.replace(/^http/, 'ws') + '/record/stream';
		const ws = new WebSocket(url);
		ws.binaryType = 'arraybuffer';
		ws.onopen = () => { this.status.connected = true; };
		ws.onclose = () => { this.status.connected = false; };
		ws.onerror = () => { this.status.error = 'stream connection error'; };
		ws.onmessage = (ev) => {
			if (typeof ev.data === 'string') this.onControl(JSON.parse(ev.data));
			else this.onFrame(ev.data as ArrayBuffer);
		};
		this.ws = ws;
	}

	disconnect() { this.ws?.close(); this.ws = null; }

	private onControl(msg: any) {
		if (msg.type === 'done') {
			this.status.state = msg.state;
			this.status.error = msg.error ?? null;
			this.status.captureId = msg.id ?? this.status.captureId;
			this.status.summary = msg.summary ?? null;
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
		const nPts = dv.getUint32(40, true);

		this.status.seq = seq; this.status.tSec = tSec; this.status.rpm = rpm;
		this.status.peaks = { Fx: pfx, Fy: pfy, Fz: pfz }; this.status.nTotal = nTotal;
		if (this.status.state === 'idle') this.status.state = 'recording';

		let off = 44;
		const trace = new Float32Array(buf, off, nTrace * 7);
		off += nTrace * 7 * 4;
		const pts = new Float32Array(buf, off, nPts * 3);

		for (let i = 0; i < nTrace; i++) {
			const b = i * 7;
			this.trace.t.push(trace[b]);
			this.trace.fx.push([trace[b + 1], trace[b + 2]]);
			this.trace.fy.push([trace[b + 3], trace[b + 4]]);
			this.trace.fz.push([trace[b + 5], trace[b + 6]]);
		}
		// drop points older than the window
		const tMin = tSec - this.windowSec;
		let drop = 0;
		while (drop < this.trace.t.length && this.trace.t[drop] < tMin) drop++;
		if (drop > 0) {
			this.trace.t.splice(0, drop); this.trace.fx.splice(0, drop);
			this.trace.fy.splice(0, drop); this.trace.fz.splice(0, drop);
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
		this.trace = { t: [], fx: [], fy: [], fz: [] };
		this.frm = { xy: new Float32Array(this.cap * 2), c: new Float32Array(this.cap), count: 0, cAbsMax: 1 };
		this.status.state = 'idle'; this.status.error = null; this.status.summary = null;
		this.status.captureId = null; this.status.nTotal = 0; this.status.tSec = 0;
		this.status.peaks = { Fx: 0, Fy: 0, Fz: 0 };
		this.frameSeq.value++;
	}

	cacheUrl(id: string) { return `${this.base}/captures/${id}/live_cache.bin`; }
}
