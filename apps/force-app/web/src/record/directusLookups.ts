// Directus-backed typeahead lookups for the Metadata pickers. Small, focused reads over the SPA's
// authenticated `api` client. Each returns [{ id, label, extra? }].
import { api } from '../directusClient';

export interface LookupItem { id: string; label: string; extra?: Record<string, any>; }

export async function searchSamples(q: string): Promise<LookupItem[]> {
	const filter: any = {};
	if (q?.trim()) filter.sample_code = { _icontains: q.trim() };
	const res = await api.get('/items/physical_samples', {
		params: { filter, limit: 20, sort: 'code_sort', fields: ['sample_id', 'sample_code', 'diameter_mm', 'nickname'] },
	});
	return (res.data?.data ?? []).map((r: any) => ({
		id: r.sample_id, label: r.sample_code || r.sample_id, extra: { diameter_mm: r.diameter_mm, nickname: r.nickname },
	}));
}

export async function searchOperators(q: string): Promise<LookupItem[]> {
	const filter: any = { is_operator: { _eq: true } };
	if (q?.trim()) filter.full_name = { _icontains: q.trim() };
	const res = await api.get('/items/people', { params: { filter, limit: 20, sort: 'full_name', fields: ['person_id', 'full_name'] } });
	return (res.data?.data ?? []).map((r: any) => ({ id: r.person_id, label: r.full_name || r.person_id }));
}

// manufacturing_operations requires a method_id (m2o -> manufacturing_methods). Cache the method
// list and resolve one for a machining/turning run (matching op-type hint, else "Machining").
let methodsCache: LookupItem[] | null = null;
export async function getMethods(): Promise<LookupItem[]> {
	if (!methodsCache) {
		const res = await api.get('/items/manufacturing_methods', { params: { limit: 100, fields: ['method_id', 'method_name'] } });
		methodsCache = (res.data?.data ?? []).map((r: any) => ({ id: r.method_id, label: r.method_name || '' }));
	}
	return methodsCache;
}
export async function resolveMachiningMethodId(hint?: string): Promise<string | null> {
	const ms = await getMethods();
	const norm = (s?: string) => (s || '').toLowerCase();
	if (hint) {
		const h = norm(hint);
		const m = ms.find((x) => norm(x.label).includes(h) || (h.length > 3 && h.includes(norm(x.label))));
		if (m) return m.id;
	}
	const machining = ms.find((x) => norm(x.label).includes('machining')) || ms.find((x) => norm(x.label).includes('turning'));
	return machining?.id ?? ms[0]?.id ?? null;
}

export async function searchEquipment(q: string): Promise<LookupItem[]> {
	const filter: any = { is_active: { _eq: true } };
	if (q?.trim()) filter.equipment_name = { _icontains: q.trim() };
	const res = await api.get('/items/equipment', {
		params: { filter, limit: 20, sort: 'equipment_name', fields: ['equipment_id', 'equipment_name', 'equipment_code', 'equipment_type'] },
	});
	return (res.data?.data ?? []).map((r: any) => ({
		id: r.equipment_id, label: r.equipment_name || r.equipment_code || r.equipment_id, extra: { type: r.equipment_type },
	}));
}
