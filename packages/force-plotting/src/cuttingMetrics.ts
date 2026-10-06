// Cutting metrics for the Plot dashboard's "Cutting metrics" card: resultant force, Fc/Ff/Fp,
// cutting speed, cutting power and specific cutting energy over the crop window. Pure functions;
// every metric is a value or "unavailable" with a reason. Formulas, units and the axis-mapping
// assumption: docs/superpowers/specs/2026-10-06-cutting-metrics-design.md.
import type { SignalStats } from './signalStats';

export type ForceAxis = 'Fx' | 'Fy' | 'Fz';
export type CutRole = 'Fc' | 'Ff' | 'Fp';
/** Which dynamometer axis carries each ISO 3002 force (Fc main cutting, Ff feed, Fp passive). */
export type AxisMap = Record<CutRole, ForceAxis>;
export type OpKind = 'turning' | 'milling' | 'unknown';

/** Assumed default for turning on this plate; NOT documented anywhere else (spec, "Axis mapping"). */
export const DEFAULT_AXIS_MAP: AxisMap = { Fc: 'Fz', Ff: 'Fx', Fp: 'Fy' };

/** All six assignments, for the card's select. Key is `Fc/Ff/Fp` axes, e.g. "Fz/Fx/Fy". */
export const AXIS_MAPS: { key: string; map: AxisMap }[] = (() => {
	const ax: ForceAxis[] = ['Fx', 'Fy', 'Fz'];
	const out: { key: string; map: AxisMap }[] = [];
	for (const c of ax) for (const f of ax) for (const p of ax) {
		if (c === f || c === p || f === p) continue;
		out.push({ key: axisMapKey({ Fc: c, Ff: f, Fp: p }), map: { Fc: c, Ff: f, Fp: p } });
	}
	return out;
})();

export function axisMapKey(m: AxisMap): string { return `${m.Fc}/${m.Ff}/${m.Fp}`; }
export function parseAxisMap(key: string | null | undefined): AxisMap {
	return AXIS_MAPS.find((a) => a.key === key)?.map ?? DEFAULT_AXIS_MAP;
}

/** `MT*` turning, `MM*` milling (the rule force-app-web's opTypeCategory uses); anything else unknown. */
export function opKindFromSubtype(subtype: string | null | undefined): OpKind {
	const s = (subtype ?? '').trim().toUpperCase();
	if (s.startsWith('MT')) return 'turning';
	if (s.startsWith('MM')) return 'milling';
	return 'unknown';
}

export interface Metric { value: number | null; reason?: string }
const ok = (value: number): Metric => ({ value });
const na = (reason: string): Metric => ({ value: null, reason });
const pos = (v: number | null | undefined): v is number => typeof v === 'number' && Number.isFinite(v) && v > 0;

export interface CuttingInputs {
	stats: Pick<SignalStats, 'axes' | 'rpm' | 'windowSec' | 'resultant' | 'cacheCropStartSec'>;
	axisMap: AxisMap;
	opKind: OpKind;
	/** Diameter (mm) at the cache crop start, i.e. the dashboard's Diameter control. */
	diameterMm: number | null | undefined;
	feedMmPerRev: number | null | undefined;
	apMm: number | null | undefined;
}

export interface CuttingMetrics {
	resultant: { mean: Metric; peak: Metric };       // N
	Fc: { mean: Metric; peak: Metric };              // N (mapped axis)
	Ff: { mean: Metric; peak: Metric };
	Fp: { mean: Metric; peak: Metric };
	diameterMidMm: Metric;                           // mm, diameter at the window midpoint
	vcMPerMin: Metric;                               // m/min
	pcW: Metric;                                     // W
	kcMPa: Metric;                                   // N/mm² = MPa
	axisMap: AxisMap;
}

/** Diameter at the window midpoint of a face-turning spiral: D − 2·f·n·(t_mid − t_crop)/60. */
export function midWindowDiameter(
	diameterMm: number, feedMmPerRev: number, rpm: number, tMidMinusCropSec: number,
): number {
	return diameterMm - 2 * feedMmPerRev * rpm * tMidMinusCropSec / 60;
}

export function computeCuttingMetrics(inp: CuttingInputs): CuttingMetrics {
	const { stats, axisMap, opKind } = inp;
	const turning = opKind === 'turning';
	const notTurning = opKind === 'milling'
		? 'milling operation: turning geometry assumed'
		: 'operation type unknown (subtype is not MT…)';

	const force = (role: CutRole): { mean: Metric; peak: Metric } => {
		if (!turning) return { mean: na(notTurning), peak: na(notTurning) };
		const a = stats.axes[axisMap[role]];
		if (!a || !a.n) return { mean: na('no samples in the window'), peak: na('no samples in the window') };
		return { mean: ok(Math.abs(a.mean)), peak: ok(Math.max(Math.abs(a.min), Math.abs(a.max))) };
	};
	const Fc = force('Fc'), Ff = force('Ff'), Fp = force('Fp');

	const hasWin = stats.axes.Fx.n > 0;
	const resultant = hasWin
		? { mean: ok(stats.resultant.mean), peak: ok(stats.resultant.peak) }
		: { mean: na('no samples in the window'), peak: na('no samples in the window') };

	const rpm = stats.rpm.mean;
	let diameterMid: Metric, vc: Metric;
	if (!turning) { diameterMid = na(notTurning); vc = na(notTurning); }
	else if (!pos(inp.diameterMm)) { diameterMid = na('diameter missing'); vc = na('diameter missing'); }
	else if (!pos(rpm)) { diameterMid = na('RPM is zero in this window'); vc = na('RPM is zero in this window'); }
	else {
		const tMid = (stats.windowSec[0] + stats.windowSec[1]) / 2;
		// Without a feed the spiral shrinkage is unknowable; fall back to the crop-start diameter.
		const f = pos(inp.feedMmPerRev) ? inp.feedMmPerRev : 0;
		const d = midWindowDiameter(inp.diameterMm, f, rpm, tMid - stats.cacheCropStartSec);
		if (!(d > 0)) { diameterMid = na('window lies beyond the disc centre (check diameter and crop)'); vc = diameterMid; }
		else { diameterMid = ok(d); vc = ok(Math.PI * d * rpm / 1000); }
	}

	let pc: Metric, kc: Metric;
	if (Fc.mean.value == null) { pc = na(Fc.mean.reason!); kc = na(Fc.mean.reason!); }
	else {
		pc = vc.value == null ? na(vc.reason!) : ok(Fc.mean.value * vc.value / 60);
		if (!pos(inp.feedMmPerRev)) kc = na('feed not recorded');
		else if (!pos(inp.apMm)) kc = na('depth of cut not recorded');
		else kc = ok(Fc.mean.value / (inp.apMm * inp.feedMmPerRev));
	}

	return { resultant, Fc, Ff, Fp, diameterMidMm: diameterMid, vcMPerMin: vc, pcW: pc, kcMPa: kc, axisMap };
}
