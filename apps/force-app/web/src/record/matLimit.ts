// #194: why a capture has no .mat, in words an operator can act on. finalize.py skips the .mat when
// n x columns x 8 bytes (float64) is over MAT_MAX_BYTES, because MAT5 stores an element size in a
// 32-bit field. The summary.json it writes carries fs, n, channels and mat_skip_reason, so the
// limit can be turned into minutes at this capture's own rate and column count.

/** Mirror of MAT_MAX_BYTES in backend/app/finalize.py. Keep the two in step. */
export const MAT_MAX_BYTES = 1_500_000_000;
const BYTES_PER_VALUE = 8;
const DEFAULT_COLUMNS = 10; // Time + 8 force channels + Tacho

/** Longest recording, in seconds, that fits in one .mat at `fs` Hz with `columns` columns. */
export function matLimitSeconds(fs: number, columns: number = DEFAULT_COLUMNS): number | null {
	if (!(fs > 0) || !(columns > 0)) return null;
	return MAT_MAX_BYTES / (columns * BYTES_PER_VALUE) / fs;
}

/** "12 min", "1 min 30 s" style, rounded down so the limit is never overstated. */
export function formatSpan(seconds: number): string {
	const s = Math.max(0, Math.floor(seconds));
	if (s < 60) return `${s} s`;
	if (s < 600) {
		const m = Math.floor(s / 60), r = s % 60;
		return r ? `${m} min ${r} s` : `${m} min`;
	}
	return `${Math.floor(s / 60)} min`;
}

function formatRate(fs: number): string {
	return fs >= 1000 ? `${Number((fs / 1000).toFixed(2))} kHz` : `${fs} Hz`;
}

export interface MatSummaryLike {
	mat_written?: boolean;
	fs?: number;
	n?: number;
	channels?: unknown[];
	duration_sec?: number;
}

/**
 * The note under the "Save a local copy (.mat)" option when finalize wrote no .mat; null when it
 * did (or the summary says nothing about it). Without a usable rate it still explains the limit.
 */
export function matSkipNote(summary: MatSummaryLike | null | undefined): string | null {
	if (!summary || summary.mat_written !== false) return null;
	const kept = 'The raw recording and the live cache are kept, and database upload and the .csv copy still work.';
	const fs = Number(summary.fs);
	const columns = Array.isArray(summary.channels) && summary.channels.length ? summary.channels.length : DEFAULT_COLUMNS;
	const limit = matLimitSeconds(fs, columns);
	if (limit == null) return `This capture is too long for a .mat file (the format caps it at about 1.5 GB), so none was written. ${kept}`;
	const dur = Number(summary.duration_sec) > 0 ? Number(summary.duration_sec) : (Number(summary.n) > 0 ? Number(summary.n) / fs : null);
	const len = dur != null ? `, and this capture is ${formatSpan(dur)} long` : '';
	return `A .mat file can't hold more than about ${formatSpan(limit)} at ${formatRate(fs)} with ${columns} columns${len}, so none was written. ${kept}`;
}
