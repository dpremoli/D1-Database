import { describe, expect, it } from 'vitest';
import { recordRoute } from './recordRoute';
import { rollupKey, rollupTargets } from './rollupLinks';

const ops = [
	{
		operation_id: 'o1',
		pass_code: '12-AB-7-F9',
		sample_id: { sample_id: 's1', sample_code: '12-AB-7' },
		equipment_id: { equipment_id: 'e1', equipment_code: 'LATHE-1' },
		tool_id: { tool_id: 't1', tool_code: 'T-04' },
		insert_edge_id: { edge_id: 'g1', edge_code: 'CNMG-1-A', insert_id: { insert_id: 'i1', insert_code: 'CNMG-1' } },
		material_id: { material_id: 'm1', alloy_code: 'Ti-6Al-4V' },
	},
	{
		operation_id: 'o2',
		pass_code: 'F-251',
		// the user may not read these relations: Directus gives the bare id, not an object
		sample_id: 's2',
		equipment_id: null,
		tool_id: undefined,
		insert_edge_id: 'g2',
		material_id: null,
	},
];

describe('rollupTargets', () => {
	const map = rollupTargets(ops);

	it('resolves each kind of rollup row to its record', () => {
		expect(map.get(rollupKey('operation', '12-AB-7-F9'))).toEqual({ collection: 'manufacturing_operations', id: 'o1' });
		expect(map.get(rollupKey('sample', '12-AB-7'))).toEqual({ collection: 'physical_samples', id: 's1' });
		expect(map.get(rollupKey('equipment', 'LATHE-1'))).toEqual({ collection: 'equipment', id: 'e1' });
		expect(map.get(rollupKey('tool', 'T-04'))).toEqual({ collection: 'tools', id: 't1' });
		expect(map.get(rollupKey('insert_edge', 'CNMG-1-A'))).toEqual({ collection: 'insert_edges', id: 'g1' });
		expect(map.get(rollupKey('cutting_insert', 'CNMG-1'))).toEqual({ collection: 'cutting_inserts', id: 'i1' });
		expect(map.get(rollupKey('material', 'Ti-6Al-4V'))).toEqual({ collection: 'materials', id: 'm1' });
	});
	it('leaves out records the user cannot read', () => {
		expect(map.get(rollupKey('operation', 'F-251'))).toEqual({ collection: 'manufacturing_operations', id: 'o2' });
		expect([...map.keys()].filter((k) => k.startsWith('sample:'))).toEqual(['sample:12-AB-7']);
	});
	it('does not mix kinds that share a code', () => {
		const m = rollupTargets([{ operation_id: 'o', pass_code: 'X', sample_id: { sample_id: 's', sample_code: 'X' } }]);
		expect(m.get(rollupKey('operation', 'X'))?.id).toBe('o');
		expect(m.get(rollupKey('sample', 'X'))?.id).toBe('s');
	});
	it('copes with nothing', () => {
		expect(rollupTargets(null).size).toBe(0);
		expect(rollupTargets([{}]).size).toBe(0);
	});
	it('feeds recordRoute: Explorer pages where they exist, the Data Studio form otherwise', () => {
		const route = (kind: string, code: string) => {
			const t = map.get(rollupKey(kind, code))!;
			return recordRoute(t.collection, t.id);
		};
		expect(route('operation', '12-AB-7-F9')).toBe('/home/operations/o1');
		expect(route('sample', '12-AB-7')).toBe('/home/samples/s1');
		expect(route('equipment', 'LATHE-1')).toBe('/content/equipment/e1');
	});
});
