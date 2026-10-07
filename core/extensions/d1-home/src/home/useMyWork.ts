import { onBeforeUnmount, ref, type Ref } from 'vue';
import {
	CURRENT_USER, campaignsMine, errorText, ownedByMe, projectsMine, samplesMine, useItems, useRequestGate,
} from '@d1/ui';

// "My work" on Home: the projects where I am PI or investigator, the campaigns I own and my newest samples, read as the
// signed-in user with explicit "mine" filters (see packages/d1-ui/src/mine.ts), so Home is personal
// even before ADR-0011 narrows what everybody can read. Each list loads and fails on its own.

export const CARD_LIMIT = 12;
export const SAMPLE_LIMIT = 10;

export interface Block<T> {
	data: T;
	loading: boolean;
	error: string;
}
const block = <T>(initial: T) => ref<Block<T>>({ data: initial, loading: true, error: '' }) as Ref<Block<T>>;

export function useMyWork() {
	const { getItems } = useItems();
	const gate = useRequestGate();

	const projects = block<any[]>([]);
	const campaigns = block<any[]>([]);
	const samples = block<any[]>([]);
	// null until known. A user with no people row owns nothing by the owner path, which is worth
	// saying out loud rather than showing three empty lists.
	const hasPerson = ref<boolean | null>(null);
	// Set when the co-owner / investigator half of a filter could not be applied (a role that may
	// not read the junction): the list then shows ownership / PI only.
	const partial = ref('');

	async function fill<T>(target: Ref<Block<T>>, token: number, what: string, read: () => Promise<T>) {
		target.value = { ...target.value, loading: true, error: '' };
		try {
			const data = await read();
			if (gate.isCurrent(token)) target.value = { data, loading: false, error: '' };
		} catch (e: any) {
			if (gate.isCurrent(token)) target.value = { data: [] as any, loading: false, error: `Could not load ${what}: ${errorText(e)}` } as Block<T>;
		}
	}

	// Try the full filter; if Directus refuses it, fall back to the owner-only half.
	async function withFallback(collection: string, full: Record<string, unknown>, fallback: Record<string, unknown>, params: Record<string, unknown>, note: string) {
		try {
			return await getItems(collection, { ...params, filter: full });
		} catch {
			partial.value = note;
			return getItems(collection, { ...params, filter: fallback });
		}
	}

	async function load() {
		const token = gate.begin();
		partial.value = '';
		await Promise.all([
			(async () => {
				try {
					const rows = await getItems('people', { filter: { user_id: { _eq: CURRENT_USER } }, fields: ['person_id'], limit: 1 });
					if (gate.isCurrent(token)) hasPerson.value = rows.length > 0;
				} catch {
					if (gate.isCurrent(token)) hasPerson.value = null;
				}
			})(),
			fill(projects, token, 'your projects', () =>
				withFallback(
					'projects',
					projectsMine,
					{ principal_investigator_person: { user_id: { _eq: CURRENT_USER } } },
					{
						fields: ['project_id', 'project_code', 'project_name', 'is_active', 'principal_investigator_person.full_name', 'principal_investigator_person.user_id'],
						sort: ['project_code'],
						limit: CARD_LIMIT,
					},
					'Projects where you are an investigator may be missing: you cannot read the investigator list.',
				),
			),
			fill(campaigns, token, 'your campaigns', () =>
				getItems('campaigns', {
					filter: campaignsMine,
					fields: ['campaign_id', 'campaign_code', 'name', 'campaign_type', 'status', 'project_id.project_code'],
					sort: ['-updated_at'],
					limit: CARD_LIMIT,
				}),
			),
			fill(samples, token, 'your samples', () =>
				withFallback(
					'physical_samples',
					samplesMine,
					ownedByMe,
					{
						fields: ['sample_id', 'sample_code', 'form', 'current_status', 'updated_at', 'material_id.common_name'],
						sort: ['-updated_at'],
						limit: SAMPLE_LIMIT,
					},
					'Samples you co-own may be missing: you cannot read the co-owner list.',
				),
			),
		]);
	}

	load();
	onBeforeUnmount(() => gate.cancel());
	return { projects, campaigns, samples, hasPerson, partial, reload: load };
}
