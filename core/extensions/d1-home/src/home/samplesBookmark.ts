// The "Samples" bookmark on physical_samples (defined in scripts/configure_directus.sql): Home's
// "View samples" link goes to it rather than the bare collection, so users land on the same
// curated view as the sidebar bookmark. It is found by name, since its id differs between
// installs; if it is not found the link opens the collection's default view.
export const SAMPLES_LIST = '/content/physical_samples';
const SAMPLES_BOOKMARK_NAME = 'Samples';

type Api = { get: (url: string, config?: any) => Promise<any> };

export async function samplesBookmarkLink(api: Api): Promise<string> {
	try {
		const res = await api.get('/presets', {
			params: {
				filter: { bookmark: { _eq: SAMPLES_BOOKMARK_NAME }, collection: { _eq: 'physical_samples' } },
				fields: ['id', 'user', 'role'],
				sort: ['id'],
				limit: -1,
			},
		});
		const rows: { id: number; user: string | null; role: string | null }[] = res.data.data ?? [];
		// Prefer the global bookmark, then a role's, then the user's own.
		const pick = rows.find((r) => !r.user && !r.role) ?? rows.find((r) => !r.user) ?? rows[0];
		return pick ? `${SAMPLES_LIST}?bookmark=${pick.id}` : SAMPLES_LIST;
	} catch {
		return SAMPLES_LIST;
	}
}
