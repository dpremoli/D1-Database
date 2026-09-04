// Client for diag-service's POST /diag/preview. The workbench edits a recipe object and posts
// it here; the service re-runs the recipe from the operation's base.d1an and returns D1AN
// column bytes, which parse straight into a WorkingSet. Preview is a float32 approximation —
// the response carries X-Diag-Preview: approximate, and the bake stays authoritative.
import { parseD1an, type DiagAttrs } from './diagAttrs';
import { authorizedFetch, useForceHost } from './host';
import { diagRequestError } from './diagError';
import type { Recipe } from './recipeChannels';

export interface DiagPreview {
	attrs: DiagAttrs;
	/** server compute time in ms, from X-Diag-Ms; null if the header was absent. */
	ms: number | null;
	/** X-Diag-Cache: 'hit' | 'miss'. */
	cache: string;
	/** Ops the service switched off for this preview because they cannot run from base.d1an
	 *  (base-tier steps need the full-rate signal). Empty when the whole recipe previewed. */
	skipped: string[];
}

export async function fetchDiagPreview(
	analysisId: string,
	recipe: Recipe,
	fromStep: number | null,
	signal?: AbortSignal,
	layers?: Record<string, unknown>,
): Promise<DiagPreview> {
	const res = await authorizedFetch(`${useForceHost().diagUrl}/preview`, {
		method: 'POST',
		signal,
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify({
			analysis_id: analysisId,
			recipe,
			from_step: fromStep,
			layers: layers ?? null,
		}),
	});
	if (!res.ok) {
		throw diagRequestError('preview', res.status, await res.text());
	}
	const msHeader = res.headers.get('X-Diag-Ms');
	const skipped = res.headers.get('X-Diag-Skipped') || '';
	return {
		attrs: parseD1an(await res.arrayBuffer()),
		ms: msHeader ? Number(msHeader) : null,
		cache: res.headers.get('X-Diag-Cache') || 'miss',
		skipped: skipped ? skipped.split(',').filter(Boolean) : [],
	};
}
