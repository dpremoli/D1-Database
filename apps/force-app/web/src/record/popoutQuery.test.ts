import { describe, expect, it } from 'vitest';
import { buildPopoutQuery, parsePopoutQuery, POPOUT_DEFAULTS, type PopoutState } from './popoutQuery';

const full: PopoutState = {
	mode: 'spectrogram', channels: ['Fx', 'Fz2', 'Tacho'], windowSec: 45, colormap: 'inferno',
	pointSize: 3.4, frmAxis: 'Fx', stride: 10, radius: 'Mz', angle: 'force_vector',
};

describe('popout query', () => {
	it('round-trips the force pop-out', () => {
		const back = parsePopoutQuery(buildPopoutQuery('force', full));
		expect(back).toMatchObject({ mode: 'spectrogram', channels: ['Fx', 'Fz2', 'Tacho'], windowSec: 45 });
		// fields the force window doesn't carry stay at their defaults
		expect(back.colormap).toBe(POPOUT_DEFAULTS.colormap);
		expect(back.stride).toBe(POPOUT_DEFAULTS.stride);
	});

	it('round-trips the FRM pop-out', () => {
		expect(parsePopoutQuery(buildPopoutQuery('frm', full)))
			.toMatchObject({ colormap: 'inferno', pointSize: 3.4, frmAxis: 'Fx', stride: 10 });
	});

	it('round-trips the polar pop-out', () => {
		expect(parsePopoutQuery(buildPopoutQuery('polar', full)))
			.toMatchObject({ radius: 'Mz', angle: 'force_vector', colormap: 'inferno', pointSize: 3.4 });
	});

	it('accepts a string and a leading ?, and the URLs older builds opened', () => {
		const old = '?mode=fft&channels=Fx,Fy&window=30';
		expect(parsePopoutQuery(old)).toMatchObject({ mode: 'fft', channels: ['Fx', 'Fy'], windowSec: 30 });
	});

	it('returns defaults for an empty query', () => {
		expect(parsePopoutQuery('')).toEqual(POPOUT_DEFAULTS);
	});

	it('falls back to the default for junk, one field at a time', () => {
		const junk = parsePopoutQuery('mode=bogus&channels=,nope,,&window=abc&colormap=toString&pointSize=huge&frmAxis=Fq&stride=3&radius=R&angle=x');
		expect(junk).toEqual(POPOUT_DEFAULTS);
		const mixed = parsePopoutQuery('mode=bogus&colormap=bgyr&stride=25');
		expect(mixed).toMatchObject({ mode: 'time', colormap: 'bgyr', stride: 25 });
	});

	it('clamps numbers and drops unknown channels, keeping the channel order', () => {
		const s = parsePopoutQuery('channels=Fz,junk,Fx,Fx&window=99999&pointSize=50');
		expect(s.channels).toEqual(['Fx', 'Fz']);
		expect(s.windowSec).toBe(300);
		expect(s.pointSize).toBe(5);
	});

	it('only carries the fields its panel uses', () => {
		expect([...buildPopoutQuery('force', full).keys()]).toEqual(['mode', 'channels', 'window']);
		expect([...buildPopoutQuery('frm', full).keys()]).toEqual(['colormap', 'pointSize', 'frmAxis', 'stride']);
	});
});
