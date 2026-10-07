import { onBeforeUnmount, ref } from 'vue';
import {
	countsByKey, datesByKey, errorText, useItems, useRequestGate, weeklyActivity, DEFAULT_WEEKS,
	type ProjectRow, type WeeklyActivity,
} from '@d1/ui';
import { fetchActivityRows } from './activityData';

// Everything the Projects index reads, as the signed-in user. The project list is the page; the
// counts and the activity are decoration that loads in parallel and fails on its own, so a role
// that cannot read samples still gets its project cards.

export const PROJECT_CAP = 500;

export interface IndexProject extends ProjectRow {
	description?: string | null;
	start_date?: string | null;
	end_date?: string | null;
}

const PROJECT_FIELDS = [
	'project_id', 'project_code', 'project_name', 'is_active', 'start_date', 'end_date',
	'principal_investigator_person.person_id', 'principal_investigator_person.full_name',
	'principal_investigator_person.user_id',
	'secondary_investigators.user_id',
];

export function useProjectsIndex() {
	const { getItems } = useItems();
	const gate = useRequestGate();

	const projects = ref<IndexProject[]>([]);
	const loading = ref(false);
	const error = ref('');

	const campaignCounts = ref(new Map<string, number>());
	const sampleCounts = ref(new Map<string, number>());
	const countsError = ref('');
	const activity = ref(new Map<string, WeeklyActivity>());
	const activityError = ref('');
	const truncated = ref(false);

	async function load() {
		const token = gate.begin();
		loading.value = true;
		error.value = '';
		countsError.value = '';
		activityError.value = '';
		try {
			const rows = await getItems('projects', { fields: PROJECT_FIELDS, sort: ['project_code'], limit: PROJECT_CAP });
			if (!gate.isCurrent(token)) return;
			projects.value = rows;
		} catch (e: any) {
			if (!gate.isCurrent(token)) return;
			error.value = `Could not load projects: ${errorText(e)}`;
			projects.value = [];
			return;
		} finally {
			if (gate.isCurrent(token)) loading.value = false;
		}

		const grouped = (collection: string) =>
			getItems(collection, {
				aggregate: { count: '*' },
				groupBy: ['project_id'],
				filter: { project_id: { _nnull: true } },
				limit: -1,
			});

		await Promise.all([
			(async () => {
				try {
					const [campaigns, samples] = await Promise.all([grouped('campaigns'), grouped('physical_samples')]);
					if (!gate.isCurrent(token)) return;
					campaignCounts.value = countsByKey(campaigns, 'project_id');
					sampleCounts.value = countsByKey(samples, 'project_id');
				} catch (e: any) {
					if (gate.isCurrent(token)) countsError.value = `Could not load counts: ${errorText(e)}`;
				}
			})(),
			(async () => {
				try {
					const rows = await fetchActivityRows(getItems);
					if (!gate.isCurrent(token)) return;
					const ops = datesByKey(rows.ops, (r) => r.project_id, (r) => r.operation_date);
					const tests = datesByKey(rows.tests, (r) => r.project_id, (r) => r.session_date);
					const now = new Date();
					const out = new Map<string, WeeklyActivity>();
					for (const p of projects.value) {
						out.set(p.project_id, weeklyActivity(ops.get(p.project_id) ?? [], tests.get(p.project_id) ?? [], DEFAULT_WEEKS, now));
					}
					activity.value = out;
					truncated.value = rows.truncated;
				} catch (e: any) {
					if (gate.isCurrent(token)) activityError.value = `Could not load activity: ${errorText(e)}`;
				}
			})(),
		]);
	}

	load();
	onBeforeUnmount(() => gate.cancel());

	return { projects, loading, error, campaignCounts, sampleCounts, countsError, activity, activityError, truncated, reload: load };
}
