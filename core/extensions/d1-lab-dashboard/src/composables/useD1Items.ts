import { useApi } from '@directus/extensions-sdk';

export function useD1Items() {
	const api = useApi();

	async function getItems(collection: string, params: Record<string, unknown> = {}): Promise<any[]> {
		const { data } = await api.get(`/items/${collection}`, { params });
		return data.data as any[];
	}

	async function getItem(collection: string, id: string, params: Record<string, unknown> = {}): Promise<any> {
		const { data } = await api.get(`/items/${collection}/${id}`, { params });
		return data.data;
	}

	async function searchItems(collection: string, field: string, query: string, extra: Record<string, unknown> = {}): Promise<any[]> {
		return getItems(collection, {
			...extra,
			[`filter[${field}][_contains]`]: query,
		});
	}

	return { getItems, getItem, searchItems };
}
