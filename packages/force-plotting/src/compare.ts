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
