import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { debounceFlush } from './debounceFlush';

beforeEach(() => { vi.useFakeTimers(); });
afterEach(() => { vi.useRealTimers(); });

describe('debounceFlush', () => {
	it('collapses a burst of calls into one write after the last one', () => {
		const fn = vi.fn();
		const d = debounceFlush(fn, 250);
		for (let i = 0; i < 100; i++) { d.call(); vi.advanceTimersByTime(10); }
		expect(fn).not.toHaveBeenCalled();
		vi.advanceTimersByTime(250);
		expect(fn).toHaveBeenCalledTimes(1);
	});
	it('flush runs a pending write now, once, and is a no-op when nothing is pending', () => {
		const fn = vi.fn();
		const d = debounceFlush(fn, 250);
		d.flush();
		expect(fn).not.toHaveBeenCalled();
		d.call();
		d.flush();
		expect(fn).toHaveBeenCalledTimes(1);
		vi.advanceTimersByTime(1000);
		expect(fn).toHaveBeenCalledTimes(1);
	});
	it('cancel drops the pending write', () => {
		const fn = vi.fn();
		const d = debounceFlush(fn, 250);
		d.call();
		d.cancel();
		vi.advanceTimersByTime(1000);
		expect(fn).not.toHaveBeenCalled();
	});
});

describe('LivePanelWindow URL write-back wiring', () => {
	const src = readFileSync(fileURLToPath(new URL('./LivePanelWindow.vue', import.meta.url)), 'utf8');
	it('debounces replaceState writes and flushes on pagehide, beforeunload and unmount', () => {
		expect(src).toMatch(/debounceFlush\(syncUrl, 250\)/);
		expect(src).toMatch(/addEventListener\('pagehide', flushUrl\)/);
		expect(src).toMatch(/addEventListener\('beforeunload', flushUrl\)/);
		expect(src).toMatch(/urlSync\.flush\(\);\s*client\.disconnect\(\)/);
	});
});
