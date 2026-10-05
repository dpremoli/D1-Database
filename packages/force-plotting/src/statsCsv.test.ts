import { describe, expect, it } from 'vitest';
import { toCsv } from './csvExport';
import { statsCsvColumns } from './statsCsv';
import type { SignalStats } from './signalStats';

const ax = { n: 10, mean: 1, rms: 2, std: 3, min: -1, max: 4, p2p: 5, effBits: 11.5, railLoPct: 0.1, railHiPct: 0.2, clipped: false };
const stats: SignalStats = { windowSec: [1, 3], axes: { Fx: ax, Fy: ax, Fz: ax }, rpm: { mean: 1200, std: 1, min: 1190, max: 1210 } };

describe('statsCsvColumns', () => {
	it('names the whole-signal columns *_whole and keeps the window columns', () => {
		const header = toCsv(statsCsvColumns(() => stats), []).trim().split(',');
		expect(header).toContain('window_start_s');
		expect(header).toEqual(expect.arrayContaining(['dyn_range_bits_whole', 'rail_lo_pct_whole', 'rail_hi_pct_whole', 'clipped_whole']));
		expect(header).not.toContain('rail_lo_pct');
		expect(header).not.toContain('dyn_range_bits');
	});
	it('writes the values under those headers', () => {
		const csv = toCsv(statsCsvColumns(() => stats), [{ axis: 'Fx', ...ax }]);
		expect(csv.split('\r\n')[1]).toBe('Fx,1,3,10,1,2,3,-1,4,5,11.5,0.1,0.2,false,1200,1,1190,1210');
	});
});
