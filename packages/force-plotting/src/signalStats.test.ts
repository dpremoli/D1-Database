import { describe, expect, it } from 'vitest';
import { resolveStatsWindow } from './signalStats';

const cache = { csSec: 2, ceSec: 9 };

describe('resolveStatsWindow', () => {
	// The old `cropStartSec || c.csSec` read a crop that really starts at 0 s as "unset" and analysed
	// from the cache's own start (2 s) instead.
	it('honours a crop start of 0', () => {
		expect(resolveStatsWindow(0, 5, cache)).toEqual([0, 5]);
	});
	it('uses the cache crop when the dashboard has none (the 0/0 default, or nulls)', () => {
		expect(resolveStatsWindow(0, 0, cache)).toEqual([2, 9]);
		expect(resolveStatsWindow(null, null, cache)).toEqual([2, 9]);
		expect(resolveStatsWindow(undefined, undefined, cache)).toEqual([2, 9]);
	});
	it('a set crop passes through unchanged', () => {
		expect(resolveStatsWindow(1.5, 4, cache)).toEqual([1.5, 4]);
	});
	it('a missing start falls back to the cache start when the end is set', () => {
		expect(resolveStatsWindow(null, 4, cache)).toEqual([2, 4]);
	});
});
