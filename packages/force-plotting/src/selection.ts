// Shared selection state for the Diagnostics Workbench: a WorkingSet is the decimated,
// off-GPU point set the D1AN file provides; a Selection is a predicate over it, evaluated the
// same way regardless of which panel produced it (time brush in Panel A, attribute threshold
// or spatial lasso in Panel B) -- that symmetry is what makes cross-panel highlighting work
// without each panel needing to know about the others.
import type { DiagAttrs } from './diagAttrs';

export interface WorkingSet {
	n: number;
	t: Float32Array;
	rev: Float32Array;
	x: Float32Array;
	y: Float32Array;
	tsaResid: Float32Array;
	residZ: Float32Array;
}

const REQUIRED_COLUMNS = ['t', 'rev', 'x', 'y', 'tsa_resid', 'resid_z'] as const;

export function workingSetFromD1an(attrs: DiagAttrs): WorkingSet {
	for (const col of REQUIRED_COLUMNS) {
		if (!(col in attrs.columns)) {
			throw new Error(`D1AN file is missing required column '${col}'`);
		}
	}
	return {
		n: attrs.n,
		t: attrs.columns.t,
		rev: attrs.columns.rev,
		x: attrs.columns.x,
		y: attrs.columns.y,
		tsaResid: attrs.columns.tsa_resid,
		residZ: attrs.columns.resid_z,
	};
}

export type Selection =
	| { kind: 'time'; t0: number; t1: number }
	| { kind: 'attribute'; column: 'residZ' | 'tsaResid'; min: number; max: number }
	| { kind: 'lasso'; polygon: [number, number][] }
	| null;

// Standard even-odd ray-casting point-in-polygon test.
function pointInPolygon(px: number, py: number, poly: [number, number][]): boolean {
	let inside = false;
	for (let i = 0, j = poly.length - 1; i < poly.length; j = i++) {
		const [xi, yi] = poly[i];
		const [xj, yj] = poly[j];
		const crosses = yi > py !== yj > py;
		if (crosses && px < ((xj - xi) * (py - yi)) / (yj - yi) + xi) inside = !inside;
	}
	return inside;
}

export function matches(ws: WorkingSet, sel: Selection, i: number): boolean {
	if (sel == null) return true;
	switch (sel.kind) {
		case 'time':
			return ws.t[i] >= sel.t0 && ws.t[i] <= sel.t1;
		case 'attribute': {
			const v = sel.column === 'residZ' ? ws.residZ[i] : ws.tsaResid[i];
			return v >= sel.min && v <= sel.max;
		}
		case 'lasso':
			return pointInPolygon(ws.x[i], ws.y[i], sel.polygon);
		default:
			return false;
	}
}

export interface SelectionStats {
	n: number;
	tMin: number;
	tMax: number;
	rMin: number;
	rMax: number;
	meanResidZ: number;
}

const ZERO_STATS: SelectionStats = { n: 0, tMin: 0, tMax: 0, rMin: 0, rMax: 0, meanResidZ: 0 };

export function computeStats(ws: WorkingSet, sel: Selection): SelectionStats {
	let n = 0;
	let tMin = Infinity;
	let tMax = -Infinity;
	let rMin = Infinity;
	let rMax = -Infinity;
	let sum = 0;
	for (let i = 0; i < ws.n; i++) {
		if (!matches(ws, sel, i)) continue;
		n++;
		const t = ws.t[i];
		if (t < tMin) tMin = t;
		if (t > tMax) tMax = t;
		const r = Math.hypot(ws.x[i], ws.y[i]);
		if (r < rMin) rMin = r;
		if (r > rMax) rMax = r;
		sum += ws.residZ[i];
	}
	if (n === 0) return { ...ZERO_STATS };
	return { n, tMin, tMax, rMin, rMax, meanResidZ: sum / n };
}
