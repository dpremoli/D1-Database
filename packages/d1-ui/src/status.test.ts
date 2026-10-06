import { describe, expect, it } from 'vitest';
import { DIAG_STATUS, FORCE_STATUS, SAMPLE_STATUS, TEST_STATUS, humanise, statusStyle } from './status';

describe('vocabularies', () => {
	it('covers the whole test-session lifecycle', () => {
		expect(Object.keys(TEST_STATUS)).toEqual([
			'registered',
			'pending_processing',
			'processing',
			'processed',
			'analysing',
			'analysed',
			'failed',
		]);
	});

	it('covers the force work-queue states', () => {
		expect(Object.keys(FORCE_STATUS)).toEqual(['pending', 'processing', 'done', 'error', 'skipped']);
	});

	it('covers the diagnostics states (null means not requested)', () => {
		expect(Object.keys(DIAG_STATUS)).toEqual(['pending', 'processing', 'done', 'error']);
	});

	it('covers the sample statuses', () => {
		expect(Object.keys(SAMPLE_STATUS)).toEqual(['active', 'consumed', 'destroyed', 'archived']);
	});

	it('marks failures as danger and finished work as success', () => {
		expect(TEST_STATUS.failed.tone).toBe('danger');
		expect(FORCE_STATUS.error.tone).toBe('danger');
		expect(TEST_STATUS.analysed.tone).toBe('success');
		expect(FORCE_STATUS.done.tone).toBe('success');
	});
});

describe('statusStyle', () => {
	it('looks a value up in the right vocabulary', () => {
		expect(statusStyle('test', 'pending_processing')).toEqual({ label: 'Pending processing', tone: 'info' });
		expect(statusStyle('force', 'done')?.label).toBe('Analysed');
		expect(statusStyle('diag', 'done')?.label).toBe('Diagnostics built');
		expect(statusStyle('sample', 'consumed')?.tone).toBe('warning');
	});

	it('returns null for a missing value', () => {
		expect(statusStyle('test', null)).toBeNull();
		expect(statusStyle('test', undefined)).toBeNull();
		expect(statusStyle('diag', '')).toBeNull();
	});

	it('shows an unknown value in neutral rather than hiding it', () => {
		expect(statusStyle('test', 'on_hold')).toEqual({ label: 'On hold', tone: 'neutral' });
	});
});

describe('humanise', () => {
	it('capitalises and replaces underscores', () => {
		expect(humanise('heat_treatment')).toBe('Heat treatment');
		expect(humanise('')).toBe('');
	});
});
