// CloudCompare-style scalar-field colour scale: a SATURATION range (where the colour ramp hits
// its end colours) kept separate from a DISPLAYED range (a filter -- points outside are hidden or
// greyed), plus the parameters that reshape the saturation mapping itself (symmetrical,
// always-show-zero, log scale) and a step/quantisation count for the ramp.
//
// Design constraint this module exists to satisfy: every renderer's shader keeps computing colour
// with the SAME linear lookup it already uses today --
//   ct = clamp((value - satMin) / (satMax - satMin), 0, 1); colour = texture2D(uColormap, ct)
// -- unchanged. Every parameter below (symmetrical/zero/steps/log) is baked CPU-side into the LUT
// buildScaleLUT() produces; the only shader change this feature needs anywhere is a displayed-range
// branch, added per-renderer in later stages of the FRM colour-scale port
// (see .claude/plans/parallel-drifting-twilight.md).
//
// Log scale semantics (signed data, e.g. Fx spans roughly -100..+100 N): symmetric log,
// sign(v)*log1p(|v|) -- defined at 0, monotonic, signed. buildScaleLUT samples this at LINEARLY
// spaced raw values across [satMin, satMax] (matching the shader's linear index), so at a coarse
// `steps` count a log ramp becomes visibly BANDED -- logarithmically spaced colour bands on an
// otherwise linear value axis. That is the intended reading of "log scale + coarse steps", not a
// bug to "fix" by moving log() into GLSL.

import { COLORMAPS } from './liveCloud';

export interface ColorScale {
	colormap: string;
	steps: number;                          // ramp quantisation, 2..256
	satMin: number; satMax: number;         // saturation range -> ramp endpoints
	dispMin: number; dispMax: number;       // displayed range -> filter window
	greyOutOfRange: boolean;                // true = grey out-of-displayed-range points, false = hide
	alwaysShowZero: boolean;
	symmetrical: boolean;
	logScale: boolean;
	barVisible: boolean;
}

// NaN-safe clamp -- same convention as liveCloud.ts's clamp01: a NaN reaching a shader renders as
// undefined (often solid white/garbage) colour, so every boundary here defends against it rather
// than propagating it.
const clamp01 = (v: number) => (Number.isNaN(v) ? 0 : v < 0 ? 0 : v > 1 ? 1 : v);

function symlog(v: number): number {
	return Number.isFinite(v) ? Math.sign(v) * Math.log1p(Math.abs(v)) : 0;
}
function invSymlog(sv: number): number {
	return Math.sign(sv) * (Math.exp(Math.abs(sv)) - 1);
}

export function defaultScale(lo: number, hi: number): ColorScale {
	if (!(hi > lo)) hi = lo + 1;   // degenerate guard, mirrors axisAutoLimits' `if (!(hi > lo))`
	return {
		colormap: 'viridis', steps: 256,
		satMin: lo, satMax: hi, dispMin: lo, dispMax: hi,
		greyOutOfRange: true, alwaysShowZero: false, symmetrical: false, logScale: false,
		barVisible: true,
	};
}

// Re-derives satMin/satMax/dispMin/dispMax from the current scale's params. Pure and idempotent --
// applying it twice in a row is a no-op. `dataLo`/`dataHi` are used only to repair a degenerate
// saturation range (e.g. a freshly defaulted scale, or NaN survivors), never to auto-widen a range
// the user has already set.
export function applyParams(s: ColorScale, dataLo: number, dataHi: number): ColorScale {
	let { satMin, satMax, dispMin, dispMax } = s;

	if (!(satMax > satMin)) {
		satMin = dataLo; satMax = dataHi;
		if (!(satMax > satMin)) { satMin = 0; satMax = 1; }
	}
	if (s.symmetrical) {
		const M = Math.max(Math.abs(satMin), Math.abs(satMax), 1e-9);
		satMin = -M; satMax = M;
	}
	if (s.alwaysShowZero) {
		if (satMin > 0) satMin = 0;
		if (satMax < 0) satMax = 0;
	}
	if (!(dispMax > dispMin)) { dispMin = satMin; dispMax = satMax; }

	return { ...s, satMin, satMax, dispMin, dispMax };
}

// Raw value -> colour-ramp position (0..1). Symlog-aware: under logScale this is the nonlinear
// tLog(v) the module header describes: buildScaleLUT samples THIS at linearly spaced v, which is
// what produces the banding rather than a continuously compressed axis.
export function normalize(v: number, s: ColorScale): number {
	if (!Number.isFinite(v)) return 0;
	let lo = s.satMin, hi = s.satMax;
	if (!(hi > lo)) hi = lo + 1e-9;
	if (s.logScale) {
		const slo = symlog(lo), shi = symlog(hi);
		const denom = shi - slo || 1e-9;
		return clamp01((symlog(v) - slo) / denom);
	}
	return clamp01((v - lo) / (hi - lo));
}

// Inverse of normalize: colour-ramp position (0..1) -> the raw value that produces it. Exact
// inverse under both linear and symlog mapping -- `normalize(denormalize(t, s), s) === t` for any
// t in [0,1] (see colorScale.test.ts's round-trip coverage). NOTE: the default colorbar rendering
// (ColorBar.vue) places its tick labels LINEARLY in value space via niceTicks over
// [satMin, satMax] -- matching buildScaleLUT's linear-in-v indexing, so no shader/index math ever
// needs to change -- and does not call this. denormalize exists for: (a) round-trip testing of
// normalize itself, and (b) an optional colour-space-uniform tick mode (ticks placed at even ramp
// positions rather than even values, useful for a log scale where the interesting detail is
// otherwise squeezed into a sliver of the bar) that a future UI pass may opt into.
export function denormalize(t: number, s: ColorScale): number {
	const tc = clamp01(t);
	let lo = s.satMin, hi = s.satMax;
	if (!(hi > lo)) hi = lo + 1e-9;
	if (s.logScale) {
		const slo = symlog(lo), shi = symlog(hi);
		return invSymlog(slo + tc * (shi - slo));
	}
	return lo + tc * (hi - lo);
}

// Colour at a ramp position (0..1), quantised to `steps` -- the same banding buildScaleLUT bakes,
// exposed standalone so a non-WebGL consumer (frmExport.ts's 2D-canvas colorbar) renders pixel-
// identical bands to what the GPU LUT shows on screen, rather than a smooth re-sample that would
// silently diverge from it.
export function sampleScale(t: number, s: ColorScale): [number, number, number] {
	const fn = COLORMAPS[s.colormap] || COLORMAPS.viridis;
	const w = Math.max(2, Math.round(s.steps) || 256);
	const tc = clamp01(t);
	const qi = Math.round(tc * (w - 1));
	return fn(qi / (w - 1));
}

// Convenience: raw value straight to a (quantised, symlog-aware) colour in one call.
export function sampleScaleAt(v: number, s: ColorScale): [number, number, number] {
	return sampleScale(normalize(v, s), s);
}

// Build an RGBA8 colour-ramp LUT for GPU upload (THREE.DataTexture), `width` samples wide. Mirrors
// frmCloudShader.ts's buildColormapLUT byte-for-byte (Uint8ClampedArray, explicit ArrayBuffer, RGBA
// stride 4) so it is a drop-in replacement at every call site that currently builds its own LUT --
// see Stage 1/3 of the colour-scale plan.
//
// `width` is the TEXTURE's sampling resolution (independent of `s.steps`, the user-facing band
// count) -- keep it high (default 256) regardless of `steps` so banding is controlled entirely by
// `steps`'s quantisation inside sampleScale, never additionally degraded by a coarse texture.
//
// Entries are sampled at LINEARLY spaced raw values across [satMin, satMax] (not linearly spaced
// ramp positions) -- this is what keeps every shader's existing `ct = (v - satMin)/(satMax - satMin)`
// linear lookup correct unchanged: index i already corresponds to raw value
// satMin + i/(width-1)*(satMax-satMin), so a linear-in-v shader index lands on the right entry
// regardless of whether logScale reshaped the COLOUR at that entry.
export function buildScaleLUT(s: ColorScale, width = 256): Uint8ClampedArray<ArrayBuffer> {
	const w = Math.max(2, Math.round(width) || 256);
	const out = new Uint8ClampedArray(new ArrayBuffer(w * 4));
	let lo = s.satMin, hi = s.satMax;
	if (!(hi > lo)) hi = lo + 1e-9;
	const span = hi - lo;
	for (let i = 0; i < w; i++) {
		const v = lo + (i / (w - 1)) * span;
		const [r, g, b] = sampleScale(normalize(v, s), s);
		out[i * 4] = Math.round(r * 255);
		out[i * 4 + 1] = Math.round(g * 255);
		out[i * 4 + 2] = Math.round(b * 255);
		out[i * 4 + 3] = 255;
	}
	return out;
}
