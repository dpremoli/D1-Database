// Client for diag-service's POST /diag/preview. The workbench edits a recipe object and posts
// it here; the service re-runs the recipe from the operation's base.d1an and returns D1AN
// column bytes, which parse straight into a WorkingSet. Preview is a float32 approximation —
// the response carries X-Diag-Preview: approximate, and the bake stays authoritative.
import { parseD1an, type DiagAttrs } from './diagAttrs';
import { useForceHost } from './host';
import type { Recipe } from './recipeChannels';

export interface DiagPreview {
	attrs: DiagAttrs;
	/** server compute time in ms, from X-Diag-Ms; null if the header was absent. */
	ms: number | null;
	/** X-Diag-Cache: 'hit' | 'miss'. */
	cache: string;
}

export async function fetchDiagPreview(
	analysisId: string,
	recipe: Recipe,
	fromStep: number | null,
	signal?: AbortSignal,
): Promise<DiagPreview> {
	const host = useForceHost();
	const res = await fetch(`${host.diagUrl}/preview`, {
		method: 'POST',
		signal,
		credentials: host.fetchCredentials,
		headers: { 'Content-Type': 'application/json', ...host.authHeaders() },
		body: JSON.stringify({
			analysis_id: analysisId,
			recipe,
			from_step: fromStep,
			layers: null,
		}),
	});
	if (!res.ok) {
		throw new Error(`diag preview: ${res.status} ${(await res.text()).slice(0, 200)}`);
	}
	const msHeader = res.headers.get('X-Diag-Ms');
	return {
		attrs: parseD1an(await res.arrayBuffer()),
		ms: msHeader ? Number(msHeader) : null,
		cache: res.headers.get('X-Diag-Cache') || 'miss',
	};
}
