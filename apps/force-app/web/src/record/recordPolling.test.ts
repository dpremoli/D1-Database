import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { IntervalGate, shouldPollBackup, shouldPollDisk } from './recordPolling';

beforeEach(() => { vi.useFakeTimers(); });
afterEach(() => { vi.useRealTimers(); });

describe('what is polled (2.6)', () => {
	it('polls disk only while recording in record mode', () => {
		expect(shouldPollDisk('record', 'recording')).toBe(true);
		expect(shouldPollDisk('record', 'finalizing')).toBe(false);
		expect(shouldPollDisk('record', 'idle')).toBe(false);
		expect(shouldPollDisk('playback', 'recording')).toBe(false);
	});
	it('polls backup progress only when a backup is configured', () => {
		expect(shouldPollBackup('record', 'recording', false)).toBe(false);
		expect(shouldPollBackup('record', 'recording', true)).toBe(true);
	});
});

describe('IntervalGate', () => {
	it('starts at once and then on the interval when turned on while already recording (a remount)', () => {
		const fn = vi.fn();
		const g = new IntervalGate(fn, 1000);
		g.set(shouldPollDisk('record', 'recording'));   // what the immediate watcher does on mount
		expect(fn).toHaveBeenCalledTimes(1);
		vi.advanceTimersByTime(2500);
		expect(fn).toHaveBeenCalledTimes(3);
		g.stop();
	});

	it('does not start twice and stops (with a final call) when turned off', () => {
		const fn = vi.fn(); const done = vi.fn();
		const g = new IntervalGate(fn, 1000, done);
		g.set(true); g.set(true);
		expect(fn).toHaveBeenCalledTimes(1);
		g.set(false);
		expect(done).toHaveBeenCalledTimes(1);
		vi.advanceTimersByTime(5000);
		expect(fn).toHaveBeenCalledTimes(1);
		expect(g.running).toBe(false);
	});

	it('picks backup polling up when the enabled flag arrives after the state', () => {
		const fn = vi.fn();
		const g = new IntervalGate(fn, 5000);
		g.set(shouldPollBackup('record', 'recording', false));
		expect(fn).not.toHaveBeenCalled();
		g.set(shouldPollBackup('record', 'recording', true));
		expect(fn).toHaveBeenCalledTimes(1);
		g.stop();
	});

	it('stop() on unmount does not run the follow-up', () => {
		const done = vi.fn();
		const g = new IntervalGate(() => {}, 1000, done);
		g.set(true); g.stop();
		expect(done).not.toHaveBeenCalled();
		expect(g.running).toBe(false);
	});
});
