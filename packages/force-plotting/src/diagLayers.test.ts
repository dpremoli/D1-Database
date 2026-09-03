import { describe, expect, it } from 'vitest';
import { layersForRequest, type DiagLayer } from './diagLayers';

const L = (over: Partial<DiagLayer>): DiagLayer => ({
	layer_id: 'id',
	analysis_id: 'a',
	name: 'chuck',
	role: 'mask',
	geometry: { polygons: [[[0, 0], [1, 0], [1, 1]]] },
	value: null,
	version: 1,
	...over,
});

describe('layersForRequest', () => {
	it('keys layers by name and keeps only the service-relevant fields', () => {
		const out = layersForRequest([L({ name: 'chuck' }), L({ name: 'edge', role: 'label' })]);
		expect(Object.keys(out).sort()).toEqual(['chuck', 'edge']);
		expect(out.chuck).toEqual({
			role: 'mask',
			geometry: { polygons: [[[0, 0], [1, 0], [1, 1]]] },
			value: null,
			version: 1,
		});
		expect((out.chuck as Record<string, unknown>).layer_id).toBeUndefined();
	});

	it('is empty for no layers', () => {
		expect(layersForRequest([])).toEqual({});
	});
});
