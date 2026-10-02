import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { createDebouncedSaver, defaultPlotPrefs, parsePlotPrefs } from './plotPrefs';

describe('parsePlotPrefs (#108)', () => {
	it('gives the defaults with nothing stored, or junk', () => {
		expect(parsePlotPrefs(null)).toEqual(defaultPlotPrefs());
		expect(parsePlotPrefs('not json')).toEqual(defaultPlotPrefs());
		expect(parsePlotPrefs('[1,2]')).toEqual(defaultPlotPrefs());
		expect(parsePlotPrefs('42')).toEqual(defaultPlotPrefs());
	});

	it('round-trips valid values', () => {
		const p = { forceMode: 'fft', frmAxis: 'Fx', colormap: 'inferno', pointSize: 3.2, windowSec: 45, liveFrmStride: 10,
			polarRadius: 'Mz', polarAngleSource: 'force_vector', polarBins: 72 };
		expect(parsePlotPrefs(JSON.stringify(p))).toEqual(p);
	});

	it('replaces each bad field with its default and keeps the good ones', () => {
		const p = parsePlotPrefs(JSON.stringify({
			frmAxis: 'Fq', colormap: 'nope', pointSize: 'big', windowSec: 0, liveFrmStride: 3,
			polarRadius: 'Fxy', polarBins: null,
		}));
		const d = defaultPlotPrefs();
		expect(p.frmAxis).toBe(d.frmAxis);
		expect(p.colormap).toBe(d.colormap);
		expect(p.pointSize).toBe(d.pointSize);
		expect(p.windowSec).toBe(d.windowSec);
		expect(p.liveFrmStride).toBe(d.liveFrmStride);
		expect(p.polarBins).toBe(d.polarBins);
		expect(p.polarRadius).toBe('Fxy');
	});

	it('clamps numbers to the ranges the controls offer', () => {
		const p = parsePlotPrefs(JSON.stringify({ pointSize: 99, windowSec: 1e6, polarBins: 1 }));
		expect(p.pointSize).toBe(5);
		expect(p.windowSec).toBe(300);
		expect(p.polarBins).toBe(4);
	});

	it('does not take an inherited property for a colormap', () => {
		expect(parsePlotPrefs(JSON.stringify({ colormap: 'toString' })).colormap).toBe('viridis');
	});

	it('ignores unknown keys', () => {
		expect(parsePlotPrefs(JSON.stringify({ evil: true }))).not.toHaveProperty('evil');
	});
});

describe('createDebouncedSaver (#108)', () => {
	beforeEach(() => { vi.useFakeTimers(); });
	afterEach(() => { vi.useRealTimers(); });

	it('writes once, with the latest value, after a burst of changes', () => {
		const save = vi.fn();
		const s = createDebouncedSaver<number>(save, 250);
		let v = 1;
		for (let i = 0; i < 10; i++) { v = i; s.schedule(() => v); vi.advanceTimersByTime(50); }
		expect(save).not.toHaveBeenCalled();
		vi.advanceTimersByTime(250);
		expect(save).toHaveBeenCalledTimes(1);
		expect(save).toHaveBeenCalledWith(9);
	});

	it('flush writes a pending change at once, and only once', () => {
		const save = vi.fn();
		const s = createDebouncedSaver<string>(save, 250);
		s.flush();
		expect(save).not.toHaveBeenCalled();
		s.schedule(() => 'x');
		s.flush();
		expect(save).toHaveBeenCalledWith('x');
		vi.advanceTimersByTime(1000);
		s.flush();
		expect(save).toHaveBeenCalledTimes(1);
	});
});
