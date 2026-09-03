// Hand-painted layers for the Diagnostics Workbench. A layer is polygons in (x, y) mm on the
// angular-resampled analysis grid (the coords DiagScatter renders) — never a per-point array,
// so it survives a re-bake at any samples_per_rev. CRUD goes through the Directus items API;
// rasterisation to per-point booleans is entirely server-side (scripts/diag/layers.py).
import { useForceHost } from './host';

export type LayerRole = 'mask' | 'label' | 'seed';

export interface LayerGeometry {
	/** A list of rings; each ring a list of [x, y] vertices in mm. Union, even-odd fill. */
	polygons: [number, number][][];
}

export interface DiagLayer {
	layer_id: string;
	analysis_id: string;
	name: string;
	role: LayerRole;
	geometry: LayerGeometry;
	value: Record<string, unknown> | null;
	version: number;
}

const FIELDS = ['layer_id', 'analysis_id', 'name', 'role', 'geometry', 'value', 'version'];

/** The shape POST /diag/preview wants: keyed by layer name, service-relevant fields only. */
export function layersForRequest(layers: DiagLayer[]) {
	const out: Record<string, { role: LayerRole; geometry: LayerGeometry; value: unknown; version: number }> = {};
	for (const l of layers) {
		out[l.name] = { role: l.role, geometry: l.geometry, value: l.value, version: l.version };
	}
	return out;
}

export async function fetchLayers(analysisId: string): Promise<DiagLayer[]> {
	const res = await useForceHost().api.get('/items/diag_layer', {
		params: { filter: { analysis_id: { _eq: analysisId } }, fields: FIELDS, limit: -1, sort: 'name' },
	});
	return (res.data?.data ?? []) as DiagLayer[];
}

export async function saveLayer(
	l: Partial<DiagLayer> & { analysis_id: string; name: string; role: LayerRole; geometry: LayerGeometry },
): Promise<DiagLayer> {
	const api = useForceHost().api;
	const payload = {
		analysis_id: l.analysis_id,
		name: l.name,
		role: l.role,
		geometry: l.geometry,
		value: l.value ?? null,
		// bump version on every write so the bake-hash fingerprint tracks geometry edits
		version: (l.version ?? 0) + 1,
	};
	if (l.layer_id) {
		const res = await api.patch(`/items/diag_layer/${l.layer_id}`, payload, { params: { fields: FIELDS } });
		return res.data.data as DiagLayer;
	}
	const res = await api.post('/items/diag_layer', payload, { params: { fields: FIELDS } });
	return res.data.data as DiagLayer;
}

export async function deleteLayer(layerId: string): Promise<void> {
	await useForceHost().api.delete(`/items/diag_layer/${layerId}`);
}
