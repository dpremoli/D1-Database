import { describe, expect, it } from 'vitest';
import { formatDuration } from './format';

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
