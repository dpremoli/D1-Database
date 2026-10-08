import { describe, expect, it } from 'vitest';
import { cropOverrideForUpload, cropWindowSec } from './cropOverride';

const cache = { csSec: 1, ceSec: 9 };

describe('cropWindowSec', () => {
	it('uses the stored override, converted from sample indices', () => {
		expect(cropWindowSec({ fs: 1000, crop_start_idx_override: 2500, crop_end_idx_override: 7000 }, cache))
			.toEqual({ startSec: 2.5, endSec: 7, overridden: true });
	});
	it('falls back to the cache detection for a side that is not stored', () => {
		expect(cropWindowSec({ fs: 1000, crop_start_idx_override: 2500 }, cache)).toEqual({ startSec: 2.5, endSec: 9, overridden: true });
	});
	it('is the cache detection when nothing is stored or the rate is unknown', () => {
		expect(cropWindowSec({ fs: 1000 }, cache)).toEqual({ startSec: 1, endSec: 9, overridden: false });
		expect(cropWindowSec({ crop_start_idx_override: 5 }, cache)).toEqual({ startSec: 1, endSec: 9, overridden: false });
	});
	it('reads the rate from the config when the summary has no fs', () => {
		expect(cropWindowSec({ config: { sample_rate: 500 }, crop_start_idx_override: 1000, crop_end_idx_override: 2000 }, cache).startSec).toBe(2);
	});
});

describe('cropOverrideForUpload', () => {
	it('is null when nothing is stored', () => {
		expect(cropOverrideForUpload({ fs: 1000 }, cache)).toBeNull();
	});
	it('passes both stored sides through', () => {
		expect(cropOverrideForUpload({ crop_start_idx_override: 1, crop_end_idx_override: 2 }, null)).toEqual({ start: 1, end: 2 });
	});
	it('fills a missing side from the cache, since the dashboard needs both', () => {
		expect(cropOverrideForUpload({ fs: 1000, crop_end_idx_override: 5000 }, cache)).toEqual({ start: 1000, end: 5000 });
		expect(cropOverrideForUpload({ fs: 1000, crop_end_idx_override: 5000 }, null)).toBeNull();
	});
});
