// Parsed live-cache store, kept in a SEPARATE module so the LRU map is a true
// singleton — evaluated once and shared across every FrmCloud mount. (Declaring it
// at the top of a <script setup> would instead recreate it on each mount, since
// setup() runs per-instance, defeating the "keep the data for a bit after switching
// operations" requirement.)

export interface Cache {
	N: number; Fs: number; feed: number; diam: number; csSec: number; ceSec: number;
	t: Float32Array; Fx: Float32Array; Fy: Float32Array; Fz: Float32Array;
	rpm: Float32Array; revs: Float32Array;
}

const MAGIC = 0x44314c43; // 'D1LC'

// Parse live_cache.bin (little-endian): 32-byte header then six float32[N] arrays.
// Layout MUST match scripts/matlab/process_force.m's write_live_cache.
export function parseCache(ab: ArrayBuffer): Cache {
	const dv = new DataView(ab);
	if (dv.getUint32(0, true) !== MAGIC) throw new Error('bad live-cache magic');
	const N = dv.getUint32(8, true);
	const Fs = dv.getFloat32(12, true);
	const feed = dv.getFloat32(16, true);
	const diam = dv.getFloat32(20, true);
	const csSec = dv.getFloat32(24, true);
	const ceSec = dv.getFloat32(28, true);
	let off = 32;
	const take = () => { const a = new Float32Array(ab, off, N); off += N * 4; return a; };
	const t = take(), Fx = take(), Fy = take(), Fz = take(), rpm = take(), revs = take();
	return { N, Fs, feed, diam, csSec, ceSec, t, Fx, Fy, Fz, rpm, revs };
}

// Decimate a cache by keeping every `stride`-th sample (indices 0, stride, 2·stride…),
// matching the filter-service's slice exactly. Used in compare mode so the raw pane plots
// the SAME sample set as the service-decimated filtered pane — identical spiral positions,
// only the force (colour) differs.
export function decimateCache(c: Cache, stride: number): Cache {
	if (stride <= 1) return c;
	const pick = (a: Float32Array) => {
		const n = Math.ceil(a.length / stride);
		const o = new Float32Array(n);
		for (let i = 0, k = 0; i < a.length; i += stride, k++) o[k] = a[i];
		return o;
	};
	return { ...c, N: Math.ceil(c.N / stride), t: pick(c.t), Fx: pick(c.Fx), Fy: pick(c.Fy), Fz: pick(c.Fz), rpm: pick(c.rpm), revs: pick(c.revs) };
}

// Module-scoped LRU: survives component unmount, so revisiting a recently-viewed
// operation is instant and issues no network request.
const MEM = new Map<string, Cache>();
const MEM_CAP = 6;

export function cacheGet(id: string): Cache | undefined {
	const v = MEM.get(id);
	if (v) { MEM.delete(id); MEM.set(id, v); }   // bump to most-recent
	return v;
}
export function cachePut(id: string, v: Cache) {
	MEM.set(id, v);
	while (MEM.size > MEM_CAP) MEM.delete(MEM.keys().next().value as string);
}
