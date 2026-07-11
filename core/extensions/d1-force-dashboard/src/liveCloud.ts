// Pure FRM point-cloud recompute for Live mode. Rebuilds the spiral fingerprint
// (positions + per-point colour) from a parsed live cache for any crop / Feed /
// Diameter / speed model — an O(N) pass, kept out of the component so it stays
// testable and reusable by both the FRM cloud renderer and any future consumer.
//
// Geometry (mirrors scripts/matlab/process_force.m): with r = revolutions elapsed
// since the crop-start,  theta = 2*PI*r,  rho = Diam/2 - Feed*r,  x/y = pol2cart.
// Three speed models drive r:
//   measured — cached revs_cum (integrated from the real tacho at full res)
//   rpm      — constant spindle speed:      r = (RPM/60)*(t - t_cs)
//   vc       — constant surface speed Vc:   rho(t) = sqrt(rho0^2 - 2K*(t-t_cs)),
//              K = Feed*Vc*1000/(pi*120) [mm^2/s]; r = (rho0 - rho)/Feed
import type { Cache } from './liveCache';

export type SpeedMode = 'measured' | 'rpm' | 'vc';
export type Axis = 'Fx' | 'Fy' | 'Fz';

export interface CloudParams {
	axis: Axis;
	feed: number;          // mm/rev
	diam: number;          // mm
	speedMode: SpeedMode;
	rpm: number;           // constant-RPM value
	vc: number;            // constant-Vc value (m/min)
	timeScale: number;     // Rate override: elapsed-time scale for rpm/vc models (1 = cache Fs)
	ppr: number;           // pulses per rev — divides the cached (raw, PPR=1) revs_cum in 'measured' mode
	cropStartSec: number;
	cropEndSec: number;
	stride: number;        // client-side thinning (render every Nth point)
	gridding: boolean;     // bin into a grid (mean colour per cell) vs raw scatter
	gridN: number;         // grid resolution per axis when gridding
	colormap: (x: number) => [number, number, number];
	// Manual colour-scale limits (N). When either is null/undefined the limit is
	// auto-computed from the data (prctile 1 / 99, mirroring the app's
	// prctile(DATA,1) / prctile(DATA,99) — the same limits process_force.m uses
	// for the canonical FRM PNGs).
	cmin?: number | null;
	cmax?: number | null;
}

export interface Cloud {
	pos: Float32Array; col: Float32Array; count: number;
	minX: number; maxX: number; minY: number; maxY: number;
	cmin: number; cmax: number;   // colour-scale limits actually applied (for the colorbar)
}

// first index with t[i] >= sec (binary search)
function idxOfTime(t: Float32Array, sec: number): number {
	let lo = 0, hi = t.length - 1, ans = t.length - 1;
	while (lo <= hi) { const m = (lo + hi) >> 1; if (t[m] >= sec) { ans = m; hi = m - 1; } else lo = m + 1; }
	return ans;
}

function percentile(sorted: Float32Array, p: number): number {
	const i = Math.min(sorted.length - 1, Math.max(0, Math.round((p / 100) * (sorted.length - 1))));
	return sorted[i];
}

export function buildCloud(c: Cache, p: CloudParams): Cloud | null {
	const t = c.t, revs = c.revs;
	const cs = idxOfTime(t, p.cropStartSec);
	const ceTime = p.cropEndSec;
	const F = p.feed, D = p.diam, rho0 = D / 2;
	const revsCs = revs[cs], tCs = t[cs];
	const revPerSec = p.rpm / 60;
	const ts = p.timeScale > 0 ? p.timeScale : 1;  // Rate override time scaling (rpm/vc only)
	const ppr = p.ppr > 0 ? p.ppr : 1;             // pulses-per-rev divisor (measured mode)
	const K = F * p.vc * 1000 / (Math.PI * 120);   // constant-Vc coefficient
	const stride = Math.max(1, Math.round(p.stride) || 1);
	const Faxis = c[p.axis];

	// Preallocate to the worst-case window size (every strided sample kept) and fill
	// by index — avoids per-point boxed-array push()/GC, which dominates at millions
	// of points. `m` is the real count (the loop can break early on rho<0 / t>end).
	const cap = Math.max(1, Math.ceil((c.N - cs) / stride) + 1);
	const xs = new Float32Array(cap), ys = new Float32Array(cap), fv = new Float32Array(cap);
	let m = 0;
	let minX = Infinity, maxX = -Infinity, minY = Infinity, maxY = -Infinity;
	for (let i = cs; i < c.N; i += stride) {
		if (t[i] > ceTime) break;
		let r: number, rho: number;
		if (p.speedMode === 'vc') {
			const under = rho0 * rho0 - 2 * K * (t[i] - tCs) * ts;
			if (under < 0) break;
			rho = Math.sqrt(under);
			r = (rho0 - rho) / F;
		} else {
			r = p.speedMode === 'rpm' ? revPerSec * (t[i] - tCs) * ts : (revs[i] - revsCs) / ppr;
			rho = rho0 - F * r;
			if (rho < 0) break;
		}
		const theta = 2 * Math.PI * r;
		const x = rho * Math.cos(theta), y = rho * Math.sin(theta);
		xs[m] = x; ys[m] = y; fv[m] = Faxis[i]; m++;
		if (x < minX) minX = x; if (x > maxX) maxX = x;
		if (y < minY) minY = y; if (y > maxY) maxY = y;
	}
	if (!m) return null;

	// colour scale: manual limits when supplied, else percentile-clamped like the
	// app — prctile(DATA,1) / prctile(DATA,99), matching process_force.m's
	// prctile(cc,[1 99]) so a couple of outlier spikes don't wash out the colormap.
	// (TypedArray.sort is numeric by default, so this sorts by value.)
	const sorted = fv.slice(0, m).sort();
	let lo = Number.isFinite(p.cmin as number) ? (p.cmin as number) : percentile(sorted, 1);
	let hi = Number.isFinite(p.cmax as number) ? (p.cmax as number) : percentile(sorted, 99);
	if (!(hi > lo)) { lo = sorted[0]; hi = sorted[sorted.length - 1]; if (!(hi > lo)) hi = lo + 1; }
	const span = hi - lo || 1;

	if (p.gridding) return gridCloud(xs, ys, fv, m, minX, maxX, minY, maxY, lo, span, p);

	const pos = new Float32Array(m * 2), col = new Float32Array(m * 3);
	for (let k = 0; k < m; k++) {
		pos[k * 2] = xs[k]; pos[k * 2 + 1] = ys[k];
		const [rr, gg, bb] = p.colormap((fv[k] - lo) / span);
		col[k * 3] = rr; col[k * 3 + 1] = gg; col[k * 3 + 2] = bb;
	}
	return { pos, col, count: m, minX, maxX, minY, maxY, cmin: lo, cmax: hi };
}

// Bin the scatter into a gridN×gridN grid; emit one point per non-empty cell at its
// centre, coloured by the mean force there. Tames overplotting into a clean map.
function gridCloud(
	xs: Float32Array, ys: Float32Array, fv: Float32Array, m: number,
	minX: number, maxX: number, minY: number, maxY: number,
	lo: number, span: number, p: CloudParams,
): Cloud {
	const G = Math.max(8, Math.round(p.gridN) || 400);
	const wx = (maxX - minX) || 1, wy = (maxY - minY) || 1;
	const sum = new Float64Array(G * G), cnt = new Uint32Array(G * G);
	for (let k = 0; k < m; k++) {
		let gx = Math.floor(((xs[k] - minX) / wx) * (G - 1e-9));
		let gy = Math.floor(((ys[k] - minY) / wy) * (G - 1e-9));
		if (gx < 0) gx = 0; else if (gx >= G) gx = G - 1;
		if (gy < 0) gy = 0; else if (gy >= G) gy = G - 1;
		const idx = gy * G + gx;
		sum[idx] += fv[k]; cnt[idx]++;
	}
	const cx = wx / G, cy = wy / G;
	const xsg: number[] = [], ysg: number[] = [], cg: number[] = [];
	for (let gy = 0; gy < G; gy++) for (let gx = 0; gx < G; gx++) {
		const idx = gy * G + gx; const n = cnt[idx]; if (!n) continue;
		xsg.push(minX + (gx + 0.5) * cx); ysg.push(minY + (gy + 0.5) * cy);
		cg.push(sum[idx] / n);
	}
	const n = cg.length;
	const pos = new Float32Array(n * 2), col = new Float32Array(n * 3);
	for (let k = 0; k < n; k++) {
		pos[k * 2] = xsg[k]; pos[k * 2 + 1] = ysg[k];
		const [rr, gg, bb] = p.colormap((cg[k] - lo) / span);
		col[k * 3] = rr; col[k * 3 + 1] = gg; col[k * 3 + 2] = bb;
	}
	return { pos, col, count: n, minX, maxX, minY, maxY, cmin: lo, cmax: lo + span };
}

// ---- colormaps (0..1 -> rgb 0..1) ----
const clamp01 = (v: number) => (v < 0 ? 0 : v > 1 ? 1 : v);

// True viridis via linear interpolation over the reference control points
// (matplotlib == MATLAB viridis, sampled at 0.1 spacing). A polynomial fit — the
// old approach — overshoots and drifts off the green→yellow ramp; piecewise-linear
// over these anchors tracks the real map closely and matches process_force.m's
// colormap(ax, viridis). For pixel-exact output, the host MATLAB render is the
// source of truth; this is the interactive Live approximation.
const VIRIDIS_ANCHORS: [number, number, number][] = [
	[0.267004, 0.004874, 0.329415], // 0.0
	[0.282623, 0.140926, 0.457517], // 0.1
	[0.253935, 0.265254, 0.529983], // 0.2
	[0.206756, 0.371758, 0.553117], // 0.3
	[0.163625, 0.471133, 0.558148], // 0.4
	[0.127568, 0.566949, 0.550556], // 0.5
	[0.134692, 0.658636, 0.517649], // 0.6
	[0.266941, 0.748751, 0.440573], // 0.7
	[0.477504, 0.821444, 0.318195], // 0.8
	[0.741388, 0.873449, 0.149561], // 0.9
	[0.993248, 0.906157, 0.143936], // 1.0
];

function lutLerp(anchors: [number, number, number][], x: number): [number, number, number] {
	x = clamp01(x);
	const last = anchors.length - 1;
	const s = x * last;
	const i = Math.min(last - 1, Math.floor(s));
	const f = s - i;
	const a = anchors[i], b = anchors[i + 1];
	return [a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f, a[2] + (b[2] - a[2]) * f];
}

function viridis(x: number): [number, number, number] { return lutLerp(VIRIDIS_ANCHORS, x); }
function inferno(x: number): [number, number, number] {
	x = clamp01(x);
	const r = -0.0002 + x * (0.1065 + x * (11.6035 + x * (-42.1403 + x * (60.1300 + x * (-35.0665 + x * 7.3641)))));
	const g = 0.0009 + x * (-0.3852 + x * (2.1873 + x * (-2.4184 + x * (2.7095 + x * (-1.8895 + x * 0.4443)))));
	const b = 0.0139 + x * (2.9950 + x * (-16.0958 + x * (40.6117 + x * (-46.3423 + x * (24.0722 + x * -4.6595)))));
	return [clamp01(r), clamp01(g), clamp01(b)];
}
function grayscale(x: number): [number, number, number] { const v = clamp01(x); return [v, v, v]; }

export const COLORMAPS: Record<string, (x: number) => [number, number, number]> = {
	viridis, inferno, grayscale,
};
