// Client for diag-service's POST /diag/viewport. The workbench frames a region of the
// full-resolution spiral (bbox in x/y mm) and asks for ONE spatial step -- Gi*, HDBSCAN, or
// seeded segmentation -- recomputed on just those points. The service crops full.d1an,
// strides down over max_points, runs the step, and returns D1AN {x, y, value}. Never
// authoritative: the 256/rev bake stays the baked truth, this is a preview at the resolution
// the analyst is looking at.
import { parseD1an } from './diagAttrs';
import { useForceHost } from './host';

export interface ViewportStep {
	op: 'getis_ord' | 'hdbscan' | 'grow_segmentation';
	params: Record<string, unknown>;
	inputs?: Record<string, unknown>;
}

export interface ViewportResult {
	/** which spatial op produced this result -- the workbench keys its recompute guards on
	 * this (a bare result cannot tell a Gi* layer from a cluster_id layer). */
	op: ViewportStep['op'];
	x: Float32Array;
	y: Float32Array;
	value: Float32Array;
	n: number;
	/** server compute time in ms, from X-Diag-Ms; null if the header was absent. */
	ms: number | null;
}

export async function fetchViewportCompute(
	analysisId: string,
	bbox: [number, number, number, number],
	step: ViewportStep,
	opts: {
		layers?: Record<string, unknown>;
		maxPoints?: number;
		output?: string;
		signal?: AbortSignal;
	} = {},
): Promise<ViewportResult> {
	const host = useForceHost();
	const res = await fetch(`${host.diagUrl}/viewport`, {
		method: 'POST',
		signal: opts.signal,
		credentials: host.fetchCredentials,
		headers: { 'Content-Type': 'application/json', ...host.authHeaders() },
		body: JSON.stringify({
			analysis_id: analysisId,
			bbox,
			step,
			layers: opts.layers ?? null,
			max_points: opts.maxPoints ?? 1_000_000,
			output: opts.output ?? 'gi_star',
		}),
	});
	if (!res.ok) {
		throw new Error(`diag viewport: ${res.status} ${(await res.text()).slice(0, 200)}`);
	}
	const attrs = parseD1an(await res.arrayBuffer());
	const ms = res.headers.get('X-Diag-Ms');
	return {
		op: step.op,
		x: attrs.columns.x,
		y: attrs.columns.y,
		value: attrs.columns.value,
		n: attrs.n,
		ms: ms ? Number(ms) : null,
	};
}
