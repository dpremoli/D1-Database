// The crop the operator set in the final summary, as kept in a capture's summary.json by
// PUT /captures/{id}/crop (#190): sample indices at the recording rate, either side may be absent.
// Local Captures reads it back so the plots and a retried upload use it instead of auto-detection.
import type { Cache } from '@d1/force-plotting';

interface CropSummary {
	fs?: number;
	config?: { sample_rate?: number };
	crop_start_idx_override?: number | null;
	crop_end_idx_override?: number | null;
}

function rate(summary: CropSummary | null | undefined): number {
	const fs = Number(summary?.fs ?? summary?.config?.sample_rate);
	return Number.isFinite(fs) && fs > 0 ? fs : 0;
}

/** The window to display: the stored override where there is one, the cache's own detection for
 *  the other side. `overridden` is false when nothing is stored (or the rate is unknown). */
export function cropWindowSec(
	summary: CropSummary | null | undefined,
	cache: Pick<Cache, 'csSec' | 'ceSec'>,
): { startSec: number; endSec: number; overridden: boolean } {
	const fs = rate(summary);
	const s = summary?.crop_start_idx_override, e = summary?.crop_end_idx_override;
	const startSec = fs && s != null ? s / fs : cache.csSec;
	const endSec = fs && e != null ? e / fs : cache.ceSec;
	return { startSec, endSec, overridden: !!fs && (s != null || e != null) };
}

/** The override pair to upload with the analysis row, or null when none is stored. The dashboard
 *  only honours an override when both sides are set, so a missing side is filled from the cache. */
export function cropOverrideForUpload(
	summary: CropSummary | null | undefined,
	cache: Pick<Cache, 'csSec' | 'ceSec'> | null,
): { start: number; end: number } | null {
	const s = summary?.crop_start_idx_override, e = summary?.crop_end_idx_override;
	if (s == null && e == null) return null;
	if (s != null && e != null) return { start: s, end: e };
	const fs = rate(summary);
	if (!cache || !fs) return null;
	return { start: s ?? Math.round(cache.csSec * fs), end: e ?? Math.round(cache.ceSec * fs) };
}
