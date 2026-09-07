// Spindle angle derivation and the RCD rotating->fixed frame transform. See
// docs/superpowers/specs/2026-09-07-milling-path-models-and-polar-design.md §2.
import type { Cache } from './liveCache';

export type AngleSource = 'tacho' | 'force_vector' | 'index_pulse';

export interface AngleParams {
	source: AngleSource;
	ppr: number;             // tacho: pulses per rev
	offsetDeg: number;       // rotate φ=0 onto a chosen tooth
	direction: 1 | -1;       // spindle sense
	engagementN: number;     // force_vector: |Fxy| below this ⇒ φ is NaN
}

export class AngleSourceUnavailableError extends Error {
	constructor(public readonly source: AngleSource) {
		super(`angle source "${source}" is not implemented yet`);
		this.name = 'AngleSourceUnavailableError';
	}
}

const TWO_PI = 2 * Math.PI;
function wrap2pi(x: number): number { const m = x % TWO_PI; return m < 0 ? m + TWO_PI : m; }

/**
 * Spindle angle phi (radians, [0, 2*PI)) for each entry in `idx`, written into `out`.
 * `out` must be at least `idx.length` long. NaN marks "angle unknown at this sample".
 */
export function spindleAngle(c: Cache, p: AngleParams, idx: Int32Array, out: Float32Array): void {
	const offset = (p.offsetDeg * Math.PI) / 180;
	const ppr = p.ppr > 0 ? p.ppr : 1;

	if (p.source === 'index_pulse') throw new AngleSourceUnavailableError('index_pulse');

	if (p.source === 'tacho') {
		const revs = c.revs;
		const revs0 = revs[idx[0]] ?? 0;
		for (let k = 0; k < idx.length; k++) {
			const i = idx[k];
			const r = ((revs[i] - revs0) / ppr) * p.direction;
			out[k] = wrap2pi(r * TWO_PI + offset);
		}
		return;
	}

	// force_vector
	for (let k = 0; k < idx.length; k++) {
		const i = idx[k];
		const fx = c.Fx[i], fy = c.Fy[i];
		if (Math.hypot(fx, fy) < p.engagementN) { out[k] = NaN; continue; }
		const raw = Math.atan2(fy, fx) * p.direction;
		out[k] = wrap2pi(raw + offset);
	}
}

export interface FixedFrame { Ff: Float32Array; FfN: Float32Array }

/**
 * RCD 9170B §8.1.1: rotate the tool-frame radial forces Fx/Fy into the workpiece
 * (fixed) frame using the immersion angle phi. At phi=90deg the frames coincide
 * (Fig. 37): Ff=Fx, FfN=Fy.
 *
 * VERIFICATION DEBT: the sign convention and phi=0 reference depend on spindle
 * rotation sense and where the tool's reference edge sits relative to the
 * dynamometer's engraved X marking. This is a correct rotation; it has not been
 * checked against a real cut. `AngleParams.offsetDeg`/`direction` (upstream, in the
 * phi this consumes) exist to calibrate that without touching this formula.
 */
export function toFixedFrame(
	fx: Float32Array, fy: Float32Array, phi: Float32Array, idx: Int32Array,
): FixedFrame {
	const n = idx.length;
	const Ff = new Float32Array(n), FfN = new Float32Array(n);
	for (let k = 0; k < n; k++) {
		const i = idx[k];
		const s = Math.sin(phi[k]), co = Math.cos(phi[k]);
		Ff[k] = fx[i] * s + fy[i] * co;
		FfN[k] = -fx[i] * co + fy[i] * s;
	}
	return { Ff, FfN };
}
