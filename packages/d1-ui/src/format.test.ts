import { describe, expect, it } from 'vitest';
import { errorText, formatDate, formatNumber, isNotVisible } from './format';

describe('formatDate', () => {
	it('formats an ISO date for en-GB', () => {
		expect(formatDate('2026-03-05T10:00:00Z')).toBe('5 Mar 2026');
	});
	it('uses the fallback for empty or invalid input', () => {
		expect(formatDate(null, 'undated')).toBe('undated');
		expect(formatDate('not a date', '?')).toBe('?');
	});
});

describe('formatNumber', () => {
	it('adds a unit and trims trailing zeros', () => {
		expect(formatNumber('20.000', 'mm')).toBe('20 mm');
		expect(formatNumber(12.5, 'mm')).toBe('12.5 mm');
	});
	it('is empty for a missing or non-numeric value', () => {
		expect(formatNumber(null, 'mm')).toBe('');
		expect(formatNumber('abc')).toBe('');
	});
	it('keeps zero', () => {
		expect(formatNumber(0, 'g')).toBe('0 g');
	});
});

describe('errorText', () => {
	it('prefers the Directus message', () => {
		expect(errorText({ response: { data: { errors: [{ message: 'nope' }] } }, message: 'x' })).toBe('nope');
		expect(errorText({ message: 'x' })).toBe('x');
		expect(errorText(undefined, 'fallback')).toBe('fallback');
	});
});

describe('isNotVisible', () => {
	it('treats 403 and 404 alike', () => {
		expect(isNotVisible({ response: { status: 403 } })).toBe(true);
		expect(isNotVisible({ response: { status: 404 } })).toBe(true);
		expect(isNotVisible({ response: { status: 500 } })).toBe(false);
		expect(isNotVisible(new Error('offline'))).toBe(false);
	});
});
