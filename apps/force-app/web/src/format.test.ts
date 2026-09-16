import { describe, expect, it } from 'vitest';
import { formatBandwidth, formatDuration } from './format';

describe('formatDuration', () => {
	it('formats sub-minute durations as m:ss', () => {
		expect(formatDuration(0)).toBe('0:00');
		expect(formatDuration(5)).toBe('0:05');
		expect(formatDuration(59)).toBe('0:59');
	});

	it('formats sub-hour durations as m:ss without an hours component', () => {
		expect(formatDuration(60)).toBe('1:00');
		expect(formatDuration(125)).toBe('2:05');
		expect(formatDuration(3599)).toBe('59:59');
	});

	it('switches to h:mm:ss at exactly one hour', () => {
		expect(formatDuration(3600)).toBe('1:00:00');
		expect(formatDuration(3661)).toBe('1:01:01');
		expect(formatDuration(7325)).toBe('2:02:05');
	});

	it('truncates fractional seconds rather than rounding', () => {
		expect(formatDuration(59.9)).toBe('0:59');
	});

	it('falls back to 0:00 for negative or non-finite input', () => {
		expect(formatDuration(-1)).toBe('0:00');
		expect(formatDuration(NaN)).toBe('0:00');
		expect(formatDuration(Infinity)).toBe('0:00');
	});
});

describe('formatBandwidth', () => {
	it('formats each unit tier', () => {
		expect(formatBandwidth(500)).toBe('500 B/s');
		expect(formatBandwidth(2500)).toBe('2.5 KB/s');
		expect(formatBandwidth(2_500_000)).toBe('2.50 MB/s');
	});

	// #38: a live rate hovering right at the 1e6 KB/MB boundary used to flicker between "1 MB/s"
	// and "1000 KB/s" on every tick, because the raw (unrounded) byte rate was compared against
	// the threshold while the DISPLAYED value was already rounded past it -- 999,950 B/s took the
	// KB branch but rendered as "1000.0 KB/s", the exact value that should have promoted it.
	it('promotes to MB once the rounded KB value would display as 1000.0', () => {
		expect(formatBandwidth(999_950)).toBe('1.00 MB/s');
		expect(formatBandwidth(1_000_000)).toBe('1.00 MB/s');
	});

	it('stays on KB just below where rounding would tip it over to MB', () => {
		expect(formatBandwidth(999_940)).toBe('999.9 KB/s');
	});
});
