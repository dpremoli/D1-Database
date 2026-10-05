import { describe, expect, it } from 'vitest';
import { decodeViewState, encodeViewState, VIEW_QUERY_KEYS, type ViewState } from './viewState';

const full: ViewState = {
	operation: 'OP-2026-0042', mode: 'fft', axis: 'Fx', zoom: [1.25, 9.5], crop: [0.5, 12.75],
	compare: ['row-a', 'row-b'], reference: 'row-b', diff: true, frm: 'lite', zSeries: 'Fz', scale: [-3.5, 40],
};

describe('viewState', () => {
	it('round-trips a full state', () => {
		expect(decodeViewState(encodeViewState(full))).toEqual(full);
	});

	it('omits defaults so a plain view is a short query', () => {
		expect(encodeViewState({ operation: 'OP-1', mode: 'force', axis: 'Fz', zSeries: 'none' })).toEqual({ operation: 'OP-1' });
		expect(encodeViewState({})).toEqual({});
	});

	it('only uses the declared keys', () => {
		for (const k of Object.keys(encodeViewState(full))) expect(VIEW_QUERY_KEYS).toContain(k);
	});

	it('keeps the legacy ?operation= link working', () => {
		expect(decodeViewState({ operation: 'OP-7' })).toEqual({ operation: 'OP-7' });
	});

	it('ignores unknown and malformed values field by field', () => {
		const got = decodeViewState({
			operation: 'OP-1', m: 'bogus', ax: 'Fq', z: '5,1', crop: 'a,b', cmp: ',,', ref: 'x', diff: '1',
			fm: 'huge', zs: 'Fw', cs: '1,2,3', extra: 'zzz',
		});
		expect(got).toEqual({ operation: 'OP-1' });
	});

	it('rejects non-finite and reversed windows', () => {
		expect(decodeViewState({ z: 'NaN,4', cs: '3,3', crop: '-2,5' })).toEqual({});
		expect(encodeViewState({ zoom: [NaN, 4], scale: [5, 1], crop: [Infinity, 2] })).toEqual({});
	});

	it('needs the reference to be in the compare set, and diff to have a reference', () => {
		expect(decodeViewState({ cmp: 'a,b', ref: 'c', diff: '1' })).toEqual({ compare: ['a', 'b'] });
		expect(decodeViewState({ cmp: 'a,b', diff: '1' })).toEqual({ compare: ['a', 'b'] });
		expect(encodeViewState({ compare: ['a'], reference: 'z', diff: true })).toEqual({ cmp: 'a' });
	});

	it('de-duplicates and caps the compare set', () => {
		expect(decodeViewState({ cmp: 'a,a,b,c,d,e,f,g' }).compare).toEqual(['a', 'b', 'c', 'd', 'e']);
	});

	it('takes the first of a repeated key and survives null, arrays and hostile input', () => {
		expect(decodeViewState({ ax: ['Fy', 'Fx'] })).toEqual({ axis: 'Fy' });
		expect(decodeViewState({ ax: [null] })).toEqual({});
		expect(decodeViewState(null)).toEqual({});
		expect(decodeViewState(undefined)).toEqual({});
		const hostile = new Proxy({}, { get() { throw new Error('boom'); } });
		expect(() => decodeViewState(hostile as any)).not.toThrow();
	});
});
