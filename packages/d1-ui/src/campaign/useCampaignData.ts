import { computed, onBeforeUnmount, ref, watch, type Ref } from 'vue';
import { errorText } from '../format';
import { useItems } from '../composables/useItems';
import { useRequestGate } from '../composables/useRequestGate';
import { buildMatrix } from './matrix';
import { isForbidden } from './errors';
import { buildOverview } from './rollup';

// Everything the campaign overview needs, read as the signed-in user (so Directus permissions
// apply). The four reads run in parallel and each fails on its own: a role that may not read
// `machining_force_analysis` still sees the samples, operations and tests, with a note.

export const LIST_CAP = 200;

export interface CampaignSection<T> {
	data: T;
	loading: boolean;
	error: string;
}

const section = <T>(data: T): CampaignSection<T> => ({ data, loading: false, error: '' });

export function useCampaignData(campaignId: Ref<string>) {
	const { getItems } = useItems();
	const gate = useRequestGate();

	const junction = ref(section<any[]>([]));
	const operations = ref(section<any[]>([]));
	const tests = ref(section<any[]>([]));
	const analyses = ref(section<any[]>([]));
	// No access to the force-analysis table is a normal state for some roles: say so, don't alarm.
	const analysisUnavailable = ref(false);

	async function fill<T>(
		target: Ref<CampaignSection<T[]>>,
		token: number,
		what: string,
		read: () => Promise<T[]>,
		onError?: (e: unknown) => boolean,
	) {
		target.value = { ...target.value, loading: true, error: '' };
		try {
			const data = await read();
			if (gate.isCurrent(token)) target.value = { data, loading: false, error: '' };
		} catch (e) {
			if (!gate.isCurrent(token)) return;
			// `handled` means the caller turned the failure into a state of its own (no error line).
			const handled = onError?.(e) ?? false;
			target.value = { data: [], loading: false, error: handled ? '' : `Could not load ${what}: ${errorText(e)}` };
		}
	}

	async function load() {
		const token = gate.begin();
		const cid = campaignId.value;
		if (!cid) return;
		analysisUnavailable.value = false;
		await Promise.all([
			fill(junction, token, 'the sample list', () =>
				getItems('campaign_samples', {
					filter: { campaign_id: { _eq: cid } },
					fields: ['id', 'sample_id.sample_id', 'sample_id.sample_code'],
					limit: -1,
				}),
			),
			fill(operations, token, "the campaign's operations", () =>
				getItems('manufacturing_operations', {
					filter: { campaign_id: { _eq: cid } },
					fields: [
						'operation_id', 'pass_code', 'operation_sequence', 'process_category',
						'sample_id.sample_id', 'sample_id.sample_code',
					],
					sort: ['operation_sequence', 'pass_code'],
					limit: -1,
				}),
			),
			fill(tests, token, 'test sessions', () =>
				getItems('test_sessions', {
					filter: { campaign_id: { _eq: cid } },
					fields: ['session_id', 'test_type', 'status', 'session_date', 'sample_id.sample_id', 'sample_id.sample_code'],
					sort: ['-session_date'],
					limit: -1,
				}),
			),
			fill(
				analyses,
				token,
				'force-analysis status',
				() =>
					getItems('machining_force_analysis', {
						filter: { operation_id: { campaign_id: { _eq: cid } } },
						fields: ['operation_id', 'status', 'error_message', 'diag_status', 'diag_error'],
						limit: -1,
					}),
				(e) => {
					if (!isForbidden(e)) return false;
					analysisUnavailable.value = true;
					return true;
				},
			),
		]);
	}

	function reset() {
		junction.value = section([]);
		operations.value = section([]);
		tests.value = section([]);
		analyses.value = section([]);
	}

	watch(
		campaignId,
		() => {
			reset();
			load();
		},
		{ immediate: true },
	);
	onBeforeUnmount(() => gate.cancel());

	const input = computed(() => ({
		samples: junction.value.data,
		operations: operations.value.data,
		tests: tests.value.data,
		analyses: analyses.value.data,
	}));
	const overview = computed(() => buildOverview(input.value));
	const matrix = computed(() => buildMatrix(input.value));
	const loading = computed(
		() => junction.value.loading || operations.value.loading || tests.value.loading || analyses.value.loading,
	);

	return { junction, operations, tests, analyses, analysisUnavailable, overview, matrix, loading, reload: load };
}
