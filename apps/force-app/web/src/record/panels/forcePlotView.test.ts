import { describe, expect, it } from 'vitest';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { forcePlotView, showWindowControl } from './forcePlotView';

describe('forcePlotView (#189)', () => {
	it('shows the finished plot once the cut is done and the cache is loaded', () => {
		expect(forcePlotView({ mode: 'time', isDone: true, hasCache: true })).toBe('finished');
	});
	it('stays live before the cut ends, before the cache loads, and in other modes', () => {
		expect(forcePlotView({ mode: 'time', isDone: false, hasCache: true })).toBe('live');
		expect(forcePlotView({ mode: 'time', isDone: true, hasCache: false })).toBe('live');
		expect(forcePlotView({ mode: 'spectrogram', isDone: true, hasCache: true })).toBe('live');
	});
});

describe('showWindowControl', () => {
	it('is hidden over the finished plot and for spectrum modes, shown otherwise', () => {
		expect(showWindowControl('time', 'live')).toBe(true);
		expect(showWindowControl('time', 'finished')).toBe(false);
		expect(showWindowControl('fft', 'live')).toBe(false);
		expect(showWindowControl('psd', 'live')).toBe(false);
		expect(showWindowControl('spectrogram', 'live')).toBe(true);
	});
});

// ForcePanel can't be mounted here (no DOM): its template must take both decisions from the helper
// and must not look at the save dialog (the old condition that flipped the plots).
describe('ForcePanel uses forcePlotView (#189)', () => {
	const src = readFileSync(fileURLToPath(new URL('./ForcePanel.vue', import.meta.url)), 'utf8');
	it('picks the plot and the slider through the helper', () => {
		expect(src).toContain("v-if=\"plotView === 'finished'\"");
		expect(src).toContain('v-if="showWindow"');
	});
	it('does not swap plots on saveOpen', () => {
		expect(src).not.toMatch(/FinishedForcePlot[^>]*saveOpen/);
	});
});
