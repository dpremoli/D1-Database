// Pass-to-pass differencing: align two cuts' per-revolution signals onto their shared
// overlapping revolution range and subtract. What's consistent between two passes on the
// same tool/insert is most likely the tool/machine signature; what survives the subtraction
// is more likely material variation -- the highest-information single feature for telling
// those two apart, and cheap enough (one interpolation, one subtraction) to run client-side
// once both passes' WorkingSets are already loaded, unlike the server-side Gi*/HDBSCAN work.

export interface AlignedDiff {
	rev: Float32Array;
	aAligned: Float32Array;
	bAligned: Float32Array;
	diff: Float32Array;
}

// Linear interpolation mirroring numpy's np.interp (the same primitive
// scripts/diag/angular.py's angular_resample already uses server-side): `xp` must be sorted
// ascending; `x` is assumed sorted ascending too (true by construction here, since it's a
// evenly-spaced generated grid), which lets the lookup walk forward with a single pointer
// instead of binary-searching per query point.
function interp(x: Float32Array, xp: Float32Array, fp: Float32Array): Float32Array {
	const out = new Float32Array(x.length);
	let j = 0;
	for (let i = 0; i < x.length; i++) {
		const xi = x[i];
		if (xi <= xp[0]) {
			out[i] = fp[0];
			continue;
		}
		if (xi >= xp[xp.length - 1]) {
			out[i] = fp[fp.length - 1];
			continue;
		}
		while (j < xp.length - 2 && xp[j + 1] < xi) j++;
		const x0 = xp[j];
		const x1 = xp[j + 1];
		const y0 = fp[j];
		const y1 = fp[j + 1];
		const t = (xi - x0) / (x1 - x0);
		out[i] = y0 + t * (y1 - y0);
	}
	return out;
}

export function alignAndDiff(
	revA: Float32Array,
	sigA: Float32Array,
	revB: Float32Array,
	sigB: Float32Array,
	samplesPerRev: number,
): AlignedDiff {
	if (revA.length !== sigA.length) {
		throw new Error(`revA/sigA length mismatch: ${revA.length} vs ${sigA.length}`);
	}
	if (revB.length !== sigB.length) {
		throw new Error(`revB/sigB length mismatch: ${revB.length} vs ${sigB.length}`);
	}
	const lo = Math.max(revA[0], revB[0]);
	const hi = Math.min(revA[revA.length - 1], revB[revB.length - 1]);
	if (hi <= lo) {
		throw new Error(
			`no overlapping revolution range between the two cuts (A: [${revA[0]}, ${revA[revA.length - 1]}], B: [${revB[0]}, ${revB[revB.length - 1]}])`,
		);
	}
	const n = Math.floor((hi - lo) * samplesPerRev);
	if (n < 1) {
		throw new Error('overlapping revolution range too small to resample');
	}
	const rev = new Float32Array(n);
	for (let i = 0; i < n; i++) rev[i] = lo + i / samplesPerRev;

	const aAligned = interp(rev, revA, sigA);
	const bAligned = interp(rev, revB, sigB);
	const diff = new Float32Array(n);
	for (let i = 0; i < n; i++) diff[i] = aAligned[i] - bAligned[i];

	return { rev, aAligned, bAligned, diff };
}

// ---- Difference of two stored force envelopes -------------------------------------------------
// The Plot page keeps each cut's force as a min/max envelope ({ t, min, max }) on the analysis row,
// which is what Compare already has loaded for every chip. Differencing works on its mid-line,
// aligned on the overlapping stretch of the two time bases (the "rev" argument of alignAndDiff is
// just a monotone x; seconds here).

export interface EnvelopeSeries { t: ArrayLike<number>; min: ArrayLike<number>; max: ArrayLike<number> }

export interface EnvelopeDiff {
	/** Shared x (seconds) the difference is sampled on. */
	t: Float32Array;
	/** current - reference. */
	diff: Float32Array;
	mean: number;
	rms: number;
}

const MAX_DIFF_POINTS = 4000;

function midLine(s: EnvelopeSeries): { x: Float32Array; y: Float32Array } | null {
	const n = Math.min(s.t?.length ?? 0, s.min?.length ?? 0, s.max?.length ?? 0);
	if (n < 2) return null;
	const x = new Float32Array(n), y = new Float32Array(n);
	for (let i = 0; i < n; i++) { x[i] = s.t[i]; y[i] = (s.min[i] + s.max[i]) / 2; }
	return x[n - 1] > x[0] ? { x, y } : null;
}

/** Mean and root-mean-square of a difference trace. */
export function diffStats(diff: ArrayLike<number>): { mean: number; rms: number } {
	let sum = 0, sq = 0;
	for (let i = 0; i < diff.length; i++) { sum += diff[i]; sq += diff[i] * diff[i]; }
	const n = diff.length || 1;
	return { mean: sum / n, rms: Math.sqrt(sq / n) };
}

/**
 * current - reference over the time range both envelopes cover, or null when either is unusable or
 * they do not overlap. Never throws: this feeds a live readout, and a bad cut should just show
 * "no overlap" rather than break the panel.
 */
export function diffEnvelopes(current: EnvelopeSeries | null | undefined, reference: EnvelopeSeries | null | undefined): EnvelopeDiff | null {
	if (!current || !reference) return null;
	const a = midLine(current), b = midLine(reference);
	if (!a || !b) return null;
	const lo = Math.max(a.x[0], b.x[0]);
	const hi = Math.min(a.x[a.x.length - 1], b.x[b.x.length - 1]);
	if (!(hi > lo)) return null;
	// Resolve the denser of the two traces, bounded so a long recording stays cheap to redraw.
	const density = Math.max(a.x.length / (a.x[a.x.length - 1] - a.x[0]), b.x.length / (b.x[b.x.length - 1] - b.x[0]));
	const spr = Math.min(density, MAX_DIFF_POINTS / (hi - lo));
	try {
		const r = alignAndDiff(a.x, a.y, b.x, b.y, spr);
		return { t: r.rev, diff: r.diff, ...diffStats(r.diff) };
	} catch { return null; }
}
