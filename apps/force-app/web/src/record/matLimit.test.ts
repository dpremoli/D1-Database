import { describe, expect, it } from 'vitest';
import { formatSpan, matFormatNote, matLimitSeconds, matSkipNote, MAT_MAX_BYTES } from './matLimit';

describe('matLimitSeconds (#194)', () => {
	it('is the 1.5 GB cap divided by rate x columns x 8 bytes', () => {
		expect(MAT_MAX_BYTES).toBe(1_500_000_000);
		// 10 columns at 25.6 kHz: 1.5e9 / 80 / 25600 = 732.4 s
		expect(matLimitSeconds(25_600, 10)).toBeCloseTo(732.42, 1);
		expect(matLimitSeconds(1000, 10)).toBeCloseTo(18_750, 5);
	});
	it('has fewer minutes with more columns or a higher rate', () => {
		expect(matLimitSeconds(25_600, 12)!).toBeLessThan(matLimitSeconds(25_600, 10)!);
		expect(matLimitSeconds(51_200, 10)!).toBeLessThan(matLimitSeconds(25_600, 10)!);
	});
	it('is null without a usable rate', () => {
		expect(matLimitSeconds(0)).toBeNull();
		expect(matLimitSeconds(NaN)).toBeNull();
	});
});

describe('formatSpan', () => {
	it('rounds down, never overstating a limit', () => {
		expect(formatSpan(45.9)).toBe('45 s');
		expect(formatSpan(90)).toBe('1 min 30 s');
		expect(formatSpan(120)).toBe('2 min');
		expect(formatSpan(732.4)).toBe('12 min');
	});
	it('can round a measured length instead', () => {
		expect(formatSpan(7.99, true)).toBe('8 s');
		expect(formatSpan(7.99)).toBe('7 s');
	});
});

describe('matSkipNote', () => {
	const big = { mat_written: false, fs: 25_600, n: 25_600 * 900, duration_sec: 900, channels: new Array(10).fill('c') };
	it('names the limit in minutes at the capture rate, its length, and what is kept', () => {
		const t = matSkipNote(big)!;
		expect(t).toContain('about 12 min at 25.6 kHz with 10 columns');
		expect(t).toContain('this capture is 15 min long');
		expect(t).toMatch(/full-resolution raw recording/);
		expect(t).toMatch(/upload still works/);
		expect(t).toMatch(/\.csv option is a reduced-resolution preview/);
		expect(t).not.toMatch(/\.csv copy still work/);
		expect(t).not.toContain('exceeds size limit');
	});
	it('rounds the capture length but floors the limit', () => {
		const t = matSkipNote({ ...big, duration_sec: 7.99 })!;
		expect(t).toContain('this capture is 8 s long');
		expect(t).toContain('about 12 min at');
	});
	it('counts appended extra channels as columns', () => {
		expect(matSkipNote({ ...big, channels: new Array(12).fill('c') })).toContain('with 12 columns');
	});
	it('falls back to n / fs for the length, and to a generic line without a rate', () => {
		expect(matSkipNote({ mat_written: false, fs: 1000, n: 1000 * 6000 })).toContain('100 min long');
		const t = matSkipNote({ mat_written: false })!;
		expect(t).toContain('too long for a .mat');
		expect(t).toMatch(/raw recording/);
	});
	it('is null when the .mat was written or there is no summary', () => {
		expect(matSkipNote({ mat_written: true, fs: 1000 })).toBeNull();
		expect(matSkipNote({ fs: 1000 })).toBeNull();
		expect(matSkipNote(null)).toBeNull();
	});
});

describe('v7.3 long cuts (#194)', () => {
	const long = { mat_written: true, mat_format: 'v7.3', fs: 25_600, n: 25_600 * 900, channels: new Array(10).fill('c') };
	it('shows a short saved-as-v7.3 line, not the over-limit note', () => {
		expect(matSkipNote(long)).toBeNull();
		const t = matFormatNote(long)!;
		expect(t).toContain('Saved as MATLAB v7.3 (long cut)');
		expect(t).toContain('MATLAB opens it with load()');
	});
	it('shows nothing special for a normal v5 file, an old summary or no summary', () => {
		expect(matFormatNote({ mat_written: true, mat_format: 'v5' })).toBeNull();
		expect(matFormatNote({ mat_written: true })).toBeNull();
		expect(matFormatNote(null)).toBeNull();
		expect(matFormatNote({ mat_written: false, mat_format: 'v7.3' })).toBeNull();
	});
	it('says no .mat was written because the v7.3 file failed, not because of the size limit', () => {
		const t = matSkipNote({ ...long, mat_written: false, mat_format: null })!;
		expect(t).toContain('MATLAB v7.3 file could not be written');
		expect(t).toMatch(/free disk space/);
		expect(t).toMatch(/full-resolution raw recording/);
		expect(t).not.toMatch(/can't hold more than/);
	});
	it('keeps the minutes wording for a summary from before v7.3', () => {
		expect(matSkipNote({ mat_written: false, fs: 25_600, n: 25_600 * 900, duration_sec: 900 })).toContain('about 12 min at 25.6 kHz');
	});
});
