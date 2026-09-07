// Radius/angle pairs for the polar-plot panel. See
// docs/superpowers/specs/2026-09-07-milling-path-models-and-polar-design.md §6.
import type { Cache } from './liveCache';
import { spindleAngle, type AngleParams } from './angle';
import type { PathWindow } from './path';

export type PolarRadius = 'Mz' | 'Fz' | 'Fxy';

export interface PolarParams {
	radius: PolarRadius;
	angle: AngleParams;
	window: PathWindow;
	// 0 = raw scatter (advisory for callers; buildPolar always returns raw per-point r/phi --
	// binning for display is the renderer's job).
	bins: number;
}

export interface PolarResult {
	r: Float32Array;
	phi: Float32Array;
	count: number;
	rMin: number; rMax: number;
	unit: 'N·m' | 'N';
	dropped: number;
}

function idxOfTime(t: Float32Array, sec: number): number {
	if (t.length === 0) return -1;
	let lo = 0, hi = t.length - 1, ans = t.length - 1;
	while (lo <= hi) { const m = (lo + hi) >> 1; if (t[m] >= sec) { ans = m; hi = m - 1; } else lo = m + 1; }
	return ans;
}

export function buildPolar(c: Cache, p: PolarParams): PolarResult | null {
	const t = c.t;
	if (!t || t.length === 0 || c.N === 0) return null;
	if (p.radius === 'Mz' && !(c as any).Mz) return null;

	const cs = idxOfTime(t, p.window.cropStartSec);
	if (cs < 0) return null;
	const stride = Math.max(1, Math.round(p.window.stride) || 1);

	const idxAll: number[] = [];
	for (let i = cs; i < c.N; i += stride) {
		if (t[i] > p.window.cropEndSec) break;
		idxAll.push(i);
	}
	if (!idxAll.length) return null;
	const idx = Int32Array.from(idxAll);

	const phiAll = new Float32Array(idx.length);
	spindleAngle(c, p.angle, idx, phiAll);

	const src: Float32Array = p.radius === 'Mz' ? (c as any).Mz : p.radius === 'Fz' ? c.Fz : c.Fx;
	const srcY = p.radius === 'Fxy' ? c.Fy : null;

	const r = new Float32Array(idx.length);
	const phi = new Float32Array(idx.length);
	let m = 0, dropped = 0;
	let rMin = Infinity, rMax = -Infinity;
	for (let k = 0; k < idx.length; k++) {
		if (Number.isNaN(phiAll[k])) { dropped++; continue; }
		const i = idx[k];
		const v = srcY ? Math.hypot(src[i], srcY[i]) : src[i];
		r[m] = v; phi[m] = phiAll[k];
		if (v < rMin) rMin = v; if (v > rMax) rMax = v;
		m++;
	}
	const unit: 'N·m' | 'N' = p.radius === 'Mz' ? 'N·m' : 'N';
	if (!m) return { r: new Float32Array(0), phi: new Float32Array(0), count: 0, rMin: 0, rMax: 0, unit, dropped };
	return { r: r.subarray(0, m), phi: phi.subarray(0, m), count: m, rMin, rMax, unit, dropped };
}
