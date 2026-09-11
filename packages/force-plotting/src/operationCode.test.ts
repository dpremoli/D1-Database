import { describe, expect, it } from 'vitest';
import { computeAutoCode, num } from './operationCode';

describe('num', () => {
	it('renders without trailing-zero noise', () => {
		expect(num(80)).toBe('80');
		expect(num(0.05)).toBe('0.05');
		expect(num(0.1)).toBe('0.1');
	});
	it('returns empty for null/undefined/blank/NaN', () => {
		expect(num(null)).toBe('');
		expect(num(undefined)).toBe('');
		expect(num('')).toBe('');
		expect(num('not a number')).toBe('');
	});
});

describe('computeAutoCode / machining', () => {
	// Golden case from tests/ui/specs/08-operation-code-autogen.spec.ts — the parity lock between
	// this module and OperationCode.vue's own `autoCode` computed (the two consumers of the one
	// true naming source). If this ever needs to change, the Playwright spec's expectation and
	// this test must change together.
	it('matches the canonical Playwright golden case', () => {
		const code = computeAutoCode({
			processCategory: 'machining',
			sampleCode: '9-AA-MR-2023-3-24',
			operationSequence: '6',
			machiningOperationSubtype: 'MM-S',
			machiningCuttingSpeedMPerMin: 80,
			machiningFeedMmPerRev: 0.05,
			machiningAxialDepthOfCutMm: 0.1,
		});
		expect(code).toBe('9-AA-MR-2023-3-24-MM-S6-80MPM_0.05feed_0.1DoC');
	});

	it('omits parameter tokens that are unset', () => {
		const code = computeAutoCode({
			processCategory: 'machining',
			sampleCode: '10-AA-MF-2023-03-31',
			operationSequence: 3,
			machiningOperationSubtype: 'F',
		});
		expect(code).toBe('10-AA-MF-2023-03-31-F3');
	});

	it('drops the sequence suffix cleanly when unset', () => {
		const code = computeAutoCode({
			processCategory: 'machining',
			sampleCode: '10-AA-MF-2023-03-31',
			operationSequence: null,
			machiningOperationSubtype: 'F',
			machiningFeedMmPerRev: 0.05,
		});
		expect(code).toBe('10-AA-MF-2023-03-31-F-0.05feed');
	});
});

describe('computeAutoCode / other categories', () => {
	it('sintering: date + MF{n} + params, no sample prefix', () => {
		const code = computeAutoCode({
			processCategory: 'sintering',
			sampleCode: null,
			operationSequence: null,
			operationDate: '2026-03-05',
			sinterMf: 42,
			sinteringMaxTempCelsius: 1200,
			sinteringMaxForceKn: 30,
			sinteringMouldDiameterMm: 20,
		});
		expect(code).toBe('05-03-26-MF42-1200C_30kN_20dia');
	});

	it('heat_treatment: HT{type}{seq} + params', () => {
		const code = computeAutoCode({
			processCategory: 'heat_treatment',
			sampleCode: '7-BB-HT-2026-01-01',
			operationSequence: 2,
			htTreatmentType: 'anneal',
			htPeakTempCelsius: 950,
			htHoldTimeMin: 60,
			htCoolingMethod: 'furnace',
		});
		expect(code).toBe('7-BB-HT-2026-01-01-HTA2-950C_60min_FC');
	});

	it('unknown category falls back to sample + sequence', () => {
		expect(computeAutoCode({ processCategory: 'other', sampleCode: 'X-1', operationSequence: 4 })).toBe('X-1-4');
		expect(computeAutoCode({ processCategory: '', sampleCode: 'X-1', operationSequence: null })).toBe('X-1');
	});
});
