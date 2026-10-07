// Links for the rows of the project items view (d1-project-items).
//
// `project_rollup` rows carry a hashed row_id, a kind and a display code, but not the id of the
// record they describe, so there is nothing to link to. The project's operations do know them:
// each operation names its sample, machine, tool, edge, insert and material. Reading those
// (as the signed-in user, so only what they may see) gives code -> record for every kind, and a
// rollup row whose record is not in the result simply stays plain text.

import { asRecord } from './format';

// project_rollup.kind -> the collection the record lives in (recordRoute() then decides the page).
export const ROLLUP_COLLECTION: Record<string, string> = {
	operation: 'manufacturing_operations',
	sample: 'physical_samples',
	equipment: 'equipment',
	tool: 'tools',
	insert_edge: 'insert_edges',
	cutting_insert: 'cutting_inserts',
	material: 'materials',
};

// What to read from the project's operations to resolve every kind above.
export const ROLLUP_OPERATION_FIELDS = [
	'operation_id', 'pass_code',
	'sample_id.sample_id', 'sample_id.sample_code',
	'equipment_id.equipment_id', 'equipment_id.equipment_code',
	'tool_id.tool_id', 'tool_id.tool_code',
	'insert_edge_id.edge_id', 'insert_edge_id.edge_code',
	'insert_edge_id.insert_id.insert_id', 'insert_edge_id.insert_id.insert_code',
	'material_id.material_id', 'material_id.alloy_code',
];

export interface RollupTarget {
	collection: string;
	id: string;
}

export const rollupKey = (kind: string, code: string | null | undefined) => `${kind}:${code ?? ''}`;

// code -> record, for every kind the operations can resolve. `ops` are the rows read with
// ROLLUP_OPERATION_FIELDS.
export function rollupTargets(ops: any[] | null | undefined): Map<string, RollupTarget> {
	const out = new Map<string, RollupTarget>();
	const add = (kind: string, code: unknown, id: unknown) => {
		if (typeof code !== 'string' || !code || (typeof id !== 'string' && typeof id !== 'number')) return;
		out.set(rollupKey(kind, code), { collection: ROLLUP_COLLECTION[kind], id: String(id) });
	};
	for (const op of ops ?? []) {
		add('operation', op?.pass_code, op?.operation_id);
		const sample = asRecord(op?.sample_id);
		add('sample', sample?.sample_code, sample?.sample_id);
		const equipment = asRecord(op?.equipment_id);
		add('equipment', equipment?.equipment_code, equipment?.equipment_id);
		const tool = asRecord(op?.tool_id);
		add('tool', tool?.tool_code, tool?.tool_id);
		const edge = asRecord(op?.insert_edge_id);
		add('insert_edge', edge?.edge_code, edge?.edge_id);
		const insert = asRecord(edge?.insert_id);
		add('cutting_insert', insert?.insert_code, insert?.insert_id);
		const material = asRecord(op?.material_id);
		add('material', material?.alloy_code, material?.material_id);
	}
	return out;
}
