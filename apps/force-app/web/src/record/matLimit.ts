// #194: a cut over MAT_MAX_BYTES (n x columns x 8 bytes; MAT5's 32-bit size field) is written by
// finalize.py as a MATLAB v7.3 file (summary.json's mat_format "v7.3"), so its .mat exists and bakes.
// Only when that file could not be written (no free disk, a write error) is there no .mat, and the
// note says so. A summary from before v7.3 (no mat_format key) with mat_written false was skipped by
// the size limit alone: summary.json's fs, n and channels turn that into minutes.

/** Mirror of MAT_MAX_BYTES in backend/app/finalize.py. Keep the two in step. */
export const MAT_MAX_BYTES = 1_500_000_000;
const BYTES_PER_VALUE = 8;
const DEFAULT_COLUMNS = 10; // Time + 8 force channels + Tacho

/** Longest recording, in seconds, that fits in one .mat at `fs` Hz with `columns` columns. */
export function matLimitSeconds(fs: number, columns: number = DEFAULT_COLUMNS): number | null {
	if (!(fs > 0) || !(columns > 0)) return null;
	return MAT_MAX_BYTES / (columns * BYTES_PER_VALUE) / fs;
}

/** "12 min", "1 min 30 s" style. Rounded down by default so a limit is never overstated;
 * pass `round` for a measured length, so 7.99 s reads "8 s" like the dialog header. */
export function formatSpan(seconds: number, round = false): string {
	const s = Math.max(0, round ? Math.round(seconds) : Math.floor(seconds));
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
	/** "v5" | "v7.3"; null when no .mat exists; absent in summaries from before v7.3 (#194). */
	mat_format?: string | null;
	fs?: number;
	n?: number;
	channels?: unknown[];
	duration_sec?: number;
}

/** The short line under the .mat option for a long cut saved as MATLAB v7.3; null for any other file. */
export function matFormatNote(summary: MatSummaryLike | null | undefined): string | null {
	if (!summary || summary.mat_written === false || summary.mat_format !== 'v7.3') return null;
	return 'Saved as MATLAB v7.3 (long cut): MATLAB opens it with load(); scipy.io.loadmat cannot read this format.';
}

/**
 * The note under the "Save a local copy (.mat)" option when finalize wrote no .mat; null when it
 * did (or the summary says nothing about it). A summary that has a mat_format key comes from a
 * recorder that writes v7.3 for long cuts, so the size limit is not the reason: the file could not
 * be written. Without a usable rate an older summary still gets the limit explained.
 */
export function matSkipNote(summary: MatSummaryLike | null | undefined): string | null {
	if (!summary || summary.mat_written !== false) return null;
	const kept = 'The full-resolution raw recording is kept (in Local Captures), and database upload still works; the .csv option is a reduced-resolution preview.';
	if ('mat_format' in summary) {
		return `No .mat was written: this capture is too long for a standard .mat, and the MATLAB v7.3 file could not be written (not enough free disk space, or a write error - see the recorder log). ${kept}`;
	}
	const fs = Number(summary.fs);
	const columns = Array.isArray(summary.channels) && summary.channels.length ? summary.channels.length : DEFAULT_COLUMNS;
	const limit = matLimitSeconds(fs, columns);
	if (limit == null) return `This capture is too long for a .mat file (the format caps it at about 1.5 GB), so none was written. ${kept}`;
	const dur = Number(summary.duration_sec) > 0 ? Number(summary.duration_sec) : (Number(summary.n) > 0 ? Number(summary.n) / fs : null);
	const len = dur != null ? `, and this capture is ${formatSpan(dur, true)} long` : '';
	return `A .mat file can't hold more than about ${formatSpan(limit)} at ${formatRate(fs)} with ${columns} columns${len}, so none was written. ${kept}`;
}
