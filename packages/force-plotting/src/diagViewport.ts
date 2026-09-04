// Client for diag-service's POST /diag/viewport. The workbench frames a region of the
// full-resolution spiral (bbox in x/y mm) and asks for ONE spatial step -- Gi*, HDBSCAN,
// GMM, or seeded segmentation -- recomputed on just those points. The service crops
// full.d1an, strides down over max_points, runs the step, and returns D1AN {x, y, value}.
// Never authoritative: the 256/rev bake stays the baked truth, this is a preview at the
// resolution the analyst is looking at.
import { parseD1an } from './diagAttrs';
import { authorizedFetch, useForceHost } from './host';
import { diagRequestError } from './diagError';

// The single source of truth for "which ops can run on a framed viewport" -- every other
// file that needs this union (DiagnosticsWorkbench, RecipePanel, SpatialPanel) imports it
// from here rather than repeating the literal, so a new spatial step is one edit instead of
// several silently-drifting ones.
export type ViewportOp = 'getis_ord' | 'hdbscan' | 'grow_segmentation' | 'gmm_segmentation';

export interface ViewportStep {
	op: ViewportOp;
	params: Record<string, unknown>;
	inputs?: Record<string, unknown>;
}

export interface ViewportResult {
	/** which spatial op produced this result -- the workbench keys its recompute guards on
	 * this (a bare result cannot tell a Gi* layer from a cluster_id layer). */
	op: ViewportStep['op'];
	x: Float32Array;
	y: Float32Array;
	/** Present unless `opts.outputs` was requested -- the single legacy column. */
	value?: Float32Array;
	/** Present when `opts.outputs` was requested: one entry per requested column, keyed by
	 *  its real name (e.g. 'gmm_id', 'gmm_prob') rather than the generic 'value'. Lets a
	 *  caller colour by one and modulate opacity by another in a single round trip -- the
	 *  case a value+confidence step (gmm_segmentation, and any future one) needs. */
	columns?: Record<string, Float32Array>;
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
		/** Request several of the step's produced columns at once instead of the single
		 *  legacy 'value' column. Each must be a column the op actually produces -- the
		 *  service 422s otherwise. Mutually exclusive with `output` in effect: passing this
		 *  ignores `output` server-side. */
		outputs?: string[];
		signal?: AbortSignal;
	} = {},
): Promise<ViewportResult> {
	const res = await authorizedFetch(`${useForceHost().diagUrl}/viewport`, {
		method: 'POST',
		signal: opts.signal,
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify({
			analysis_id: analysisId,
			bbox,
			step,
			layers: opts.layers ?? null,
			max_points: opts.maxPoints ?? 1_000_000,
			output: opts.output ?? 'gi_star',
			...(opts.outputs ? { outputs: opts.outputs } : {}),
		}),
	});
	if (!res.ok) {
		throw diagRequestError('viewport recompute', res.status, await res.text());
	}
	const attrs = parseD1an(await res.arrayBuffer());
	const ms = res.headers.get('X-Diag-Ms');
	const base = { op: step.op, x: attrs.columns.x, y: attrs.columns.y, n: attrs.n,
		ms: ms ? Number(ms) : null };
	if (opts.outputs) {
		const columns: Record<string, Float32Array> = {};
		for (const name of opts.outputs) columns[name] = attrs.columns[name];
		return { ...base, columns };
	}
	return { ...base, value: attrs.columns.value };
}
