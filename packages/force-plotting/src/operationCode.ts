// Canonical operation-name ("pass_code") generation logic. `manufacturing_operations.pass_code`
// has no DB default/trigger (verified against the live schema) — this is a faithful, pure,
// framework-agnostic port of the ONLY thing that generates it today:
// core/extensions/d1-operation-code/src/OperationCode.vue's `autoCode` computed. Async lookups
// (the sample's code, and the sintering running-count) stay in each caller, exactly as
// OperationCode.vue already keeps them out of its own `autoCode` computed — this module takes
// them as already-resolved plain inputs.

// Render a number without trailing-zero noise: 80 -> "80", 0.05 -> "0.05".
export function num(v: unknown): string {
	if (v === null || v === undefined || v === '') return '';
	const n = Number(v);
	if (Number.isNaN(n)) return '';
	return String(parseFloat(n.toPrecision(6)));
}

// DD-MM-YY for the sintering code (FAST ops carry no sample, so the date + a global counter are
// what make the code unique). Empty when no date is set yet.
function dateCode(v: unknown): string {
	if (!v) return '';
	const d = new Date(v as string);
	if (Number.isNaN(d.getTime())) return '';
	const p = (x: number) => String(x).padStart(2, '0');
	return `${p(d.getDate())}-${p(d.getMonth() + 1)}-${String(d.getFullYear()).slice(-2)}`;
}

const HT_TYPE: Record<string, string> = {
	anneal: 'A', solution_treat: 'S', age: 'AG', quench: 'Q',
	temper: 'T', stress_relieve: 'SR', normalise: 'N', other: 'X',
};
const HT_COOL: Record<string, string> = {
	furnace: 'FC', air: 'AC', water_quench: 'WQ', oil_quench: 'OQ', forced_air: 'FA', other: 'X',
};
const DEFORM_TOKEN: Record<string, string> = {
	rolling: 'DR', forging: 'DF', extrusion: 'DE', drawing: 'DD', other: 'DX',
};

export interface AutoCodeInput {
	processCategory: string | null | undefined;
	sampleCode: string | null;          // resolved by the caller (async physical_samples lookup)
	operationSequence: unknown;
	operationDate?: unknown;
	// machining
	machiningOperationSubtype?: unknown;
	machiningCuttingSpeedMPerMin?: unknown;
	machiningFeedMmPerRev?: unknown;
	machiningAxialDepthOfCutMm?: unknown;
	// sintering — sinterMf is the caller-resolved "next MF number" running count (async, needs a
	// count query against manufacturing_operations); pass it only for a NEW sintering record.
	sinterMf?: number | null;
	sinteringMaxTempCelsius?: unknown;
	sinteringMaxForceKn?: unknown;
	sinteringMouldDiameterMm?: unknown;
	// heat_treatment
	htTreatmentType?: string | null;
	htPeakTempCelsius?: unknown;
	htHoldTimeMin?: unknown;
	htCoolingMethod?: string | null;
	// deformation
	deformDeformationType?: string | null;
	deformDeformationTempCelsius?: unknown;
	deformTotalReductionPct?: unknown;
	deformPassCount?: unknown;
	// additive
	amProcessVariant?: string | null;
	amLaserPowerW?: unknown;
	amScanSpeedMmPerS?: unknown;
	amLayerThicknessMm?: unknown;
}

export function computeAutoCode(v: AutoCodeInput): string {
	const sample = v.sampleCode ?? '';
	const cat = v.processCategory ?? '';

	// Per-sample sequence number — the unique identifier every operation carries, so two ops on
	// the same sample never collide even with identical parameters.
	const seq = v.operationSequence;
	const seqStr = seq === '' || seq === null || seq === undefined ? '' : String(seq);

	let token = '';
	let parts: string[] = [];

	if (cat === 'machining') {
		token = `${v.machiningOperationSubtype ?? ''}${seqStr}`;
		parts = [
			num(v.machiningCuttingSpeedMPerMin) && `${num(v.machiningCuttingSpeedMPerMin)}MPM`,
			num(v.machiningFeedMmPerRev) && `${num(v.machiningFeedMmPerRev)}feed`,
			num(v.machiningAxialDepthOfCutMm) && `${num(v.machiningAxialDepthOfCutMm)}DoC`,
		].filter(Boolean) as string[];
	} else if (cat === 'sintering') {
		const dcode = dateCode(v.operationDate);
		const nStr = v.sinterMf != null ? String(v.sinterMf) : seqStr;
		const mf = `MF${nStr}`;
		const sparams = [
			num(v.sinteringMaxTempCelsius) && `${num(v.sinteringMaxTempCelsius)}C`,
			num(v.sinteringMaxForceKn) && `${num(v.sinteringMaxForceKn)}kN`,
			num(v.sinteringMouldDiameterMm) && `${num(v.sinteringMouldDiameterMm)}dia`,
		].filter(Boolean).join('_');
		return [dcode, mf, sparams].filter(Boolean).join('-');
	} else if (cat === 'heat_treatment') {
		token = `HT${HT_TYPE[v.htTreatmentType ?? ''] ?? ''}${seqStr}`;
		parts = [
			num(v.htPeakTempCelsius) && `${num(v.htPeakTempCelsius)}C`,
			num(v.htHoldTimeMin) && `${num(v.htHoldTimeMin)}min`,
			HT_COOL[v.htCoolingMethod ?? ''],
		].filter(Boolean) as string[];
	} else if (cat === 'deformation') {
		token = `${DEFORM_TOKEN[v.deformDeformationType ?? ''] ?? 'D'}${seqStr}`;
		parts = [
			num(v.deformDeformationTempCelsius) && `${num(v.deformDeformationTempCelsius)}C`,
			num(v.deformTotalReductionPct) && `${num(v.deformTotalReductionPct)}pct`,
			num(v.deformPassCount) && `${num(v.deformPassCount)}p`,
		].filter(Boolean) as string[];
	} else if (cat === 'additive') {
		token = `${v.amProcessVariant ?? 'AM'}${seqStr}`;
		parts = [
			num(v.amLaserPowerW) && `${num(v.amLaserPowerW)}W`,
			num(v.amScanSpeedMmPerS) && `${num(v.amScanSpeedMmPerS)}mmps`,
			num(v.amLayerThicknessMm) && `${num(v.amLayerThicknessMm)}mm`,
		].filter(Boolean) as string[];
	} else {
		return seqStr ? `${sample}-${seqStr}` : sample;   // unknown category — sample + seq
	}

	let code = sample;
	if (token) code = code ? `${code}-${token}` : token;
	if (code && parts.length) code = `${code}-${parts.join('_')}`;
	return code;
}
