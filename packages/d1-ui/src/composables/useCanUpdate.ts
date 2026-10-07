import { ref, watch, type Ref } from 'vue';
import { useApi } from '@directus/extensions-sdk';
import { itemPermissionsUrl, updateAccess } from '../canUpdate';
import { useRequestGate } from './useRequestGate';

// Whether the signed-in user may update one record, from Directus's item-permissions endpoint.
// `canUpdate` is true / false, or null while unknown (not asked yet, or the answer failed): pages
// show Edit unless it is exactly false, because the server enforces the rule anyway.
export function useCanUpdate(collection: string, id: Ref<string | null | undefined>) {
	const api = useApi();
	const gate = useRequestGate();
	const canUpdate = ref<boolean | null>(null);

	async function refresh() {
		const token = gate.begin();
		const pk = id.value;
		if (!pk) {
			canUpdate.value = null;
			return;
		}
		try {
			const res = await api.get(itemPermissionsUrl(collection, pk));
			if (gate.isCurrent(token)) canUpdate.value = updateAccess(res.data);
		} catch {
			if (gate.isCurrent(token)) canUpdate.value = null;
		}
	}

	watch(id, refresh, { immediate: true });
	return { canUpdate, refresh };
}
