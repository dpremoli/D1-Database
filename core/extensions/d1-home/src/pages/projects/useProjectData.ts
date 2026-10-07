import { onBeforeUnmount, ref, watch, type Ref } from 'vue';
import {
	DEFAULT_WEEKS, campaignProgress, countsByKey, errorText, isNotVisible, useItems, useRequestGate, weeklyActivity,
	type CampaignProgress, type WeeklyActivity,
} from '@d1/ui';
import { fetchActivityRows } from './activityData';

// Everything the Project page reads, as the signed-in user (so Directus permissions apply). Reads
// the real collections, not `project_rollup`, which ADR-0011 restricts. The project decides between
// "page" and "Not found or not visible to you"; every other block is a section that loads in
// parallel and fails on its own, so one forbidden collection does not blank the page.

export const LIST_CAP = 200;
const PROGRESS_ROW_CAP = 5000;

export interface Block<T> {
	data: T;
	loading: boolean;
	error: string;
}
const block = <T>(initial: T) => ref<Block<T>>({ data: initial, loading: false, error: '' }) as Ref<Block<T>>;

const PROJECT_FIELDS = [
	'project_id', 'project_code', 'project_name', 'description', 'document_number', 'is_active',
	'start_date', 'end_date', 'export_controlled', 'version',
	'principal_investigator_person.person_id', 'principal_investigator_person.full_name',
	'principal_investigator_person.user_id',
];

export interface ProjectCounts {
	samples: number | null;
	operations: number | null;
	tests: number | null;
	campaigns: number | null;
}

export interface Activity {
	data: WeeklyActivity | null;
	truncated: boolean;
}

export interface EquipmentUse {
	equipment_id: string;
	name: string;
	operations: number;
}

export function useProjectData(id: Ref<string>) {
	const { getItems, getItem } = useItems();
	const gate = useRequestGate();

	const project = ref<any | null>(null);
	const loading = ref(false);
	const notVisible = ref(false);
	const error = ref('');

	const investigators = block<string[]>([]);
	const counts = block<ProjectCounts>({ samples: null, operations: null, tests: null, campaigns: null });
	const campaigns = block<(any & { stats: CampaignProgress | null })[]>([]);
	const looseSamples = block<any[]>([]);
	const looseOperations = block<any[]>([]);
	const looseTests = block<any[]>([]);
	const activity = block<Activity>({ data: null, truncated: false });
	const equipment = block<EquipmentUse[]>([]);

	const all = [investigators, counts, campaigns, looseSamples, looseOperations, looseTests, activity, equipment] as Ref<Block<any>>[];

	async function fill<T>(target: Ref<Block<T>>, token: number, what: string, read: () => Promise<T>) {
		target.value = { ...target.value, loading: true, error: '' };
		try {
			const data = await read();
			if (gate.isCurrent(token)) target.value = { data, loading: false, error: '' };
		} catch (e: any) {
			if (gate.isCurrent(token)) target.value = { ...target.value, loading: false, error: `Could not load ${what}: ${errorText(e)}` };
		}
	}

	const count = async (collection: string, filter: Record<string, unknown>): Promise<number | null> => {
		try {
			const rows = await getItems(collection, { aggregate: { count: '*' }, filter, limit: 1 });
			return Number(rows[0]?.count ?? 0);
		} catch {
			// A collection the role cannot read: the tile shows a dash rather than a wrong 0.
			return null;
		}
	};

	async function loadCampaigns(token: number, projectId: string) {
		const inProject = { campaign_id: { project_id: { _eq: projectId } } };
		const rows = await getItems('campaigns', {
			filter: { project_id: { _eq: projectId } },
			fields: [
				'campaign_id', 'campaign_code', 'name', 'campaign_type', 'status', 'start_date', 'end_date',
				'owner_person_id.person_id', 'owner_person_id.full_name',
			],
			sort: ['campaign_code', 'name'],
			limit: LIST_CAP + 1,
		});
		if (!gate.isCurrent(token)) return [];
		// The numbers behind the progress bars. Each read fails on its own: the cards then show no
		// stats rather than no campaigns.
		const soft = async <T>(read: () => Promise<T>, fallback: T): Promise<{ data: T; ok: boolean }> => {
			try {
				return { data: await read(), ok: true };
			} catch {
				return { data: fallback, ok: false };
			}
		};
		const [samples, ops, tests, analyses] = await Promise.all([
			soft(() => getItems('campaign_samples', { aggregate: { count: '*' }, groupBy: ['campaign_id'], filter: inProject, limit: -1 }), [] as any[]),
			soft(() => getItems('manufacturing_operations', {
				filter: { campaign_id: { project_id: { _eq: projectId } } },
				fields: ['operation_id', 'campaign_id', 'process_category'],
				limit: PROGRESS_ROW_CAP,
			}), [] as any[]),
			soft(() => getItems('test_sessions', {
				filter: { campaign_id: { project_id: { _eq: projectId } } },
				fields: ['campaign_id', 'status'],
				limit: PROGRESS_ROW_CAP,
			}), [] as any[]),
			soft(() => getItems('machining_force_analysis', {
				filter: { operation_id: { campaign_id: { project_id: { _eq: projectId } } } },
				fields: ['operation_id', 'status'],
				limit: PROGRESS_ROW_CAP,
			}), [] as any[]),
		]);
		const complete = samples.ok && ops.ok && tests.ok;
		const stats = complete
			? campaignProgress({
					campaigns: rows,
					samplesByCampaign: countsByKey(samples.data, 'campaign_id'),
					operations: ops.data,
					tests: tests.data,
					// Without force-analysis access the machining bar would read 0 / n: leave it out.
					analyses: analyses.data,
				})
			: null;
		return rows.map((c: any) => {
			const s = stats?.get(c.campaign_id) ?? null;
			if (s && !analyses.ok && c.campaign_type !== 'testing_campaign') s.progress = { label: 'Force analysed', done: 0, total: 0 };
			return { ...c, stats: s };
		});
	}

	async function loadEquipment(projectId: string): Promise<EquipmentUse[]> {
		const groups = await getItems('manufacturing_operations', {
			aggregate: { count: '*' },
			groupBy: ['equipment_id'],
			filter: { _and: [{ project_id: { _eq: projectId } }, { equipment_id: { _nnull: true } }] },
			limit: -1,
		});
		const used = countsByKey(groups, 'equipment_id');
		if (!used.size) return [];
		const rows = await getItems('equipment', {
			filter: { equipment_id: { _in: [...used.keys()] } },
			fields: ['equipment_id', 'equipment_name'],
			limit: -1,
		});
		const names = new Map(rows.map((r: any) => [String(r.equipment_id), r.equipment_name as string]));
		return [...used.entries()]
			.map(([equipment_id, operations]) => ({ equipment_id, name: names.get(equipment_id) ?? 'Unnamed equipment', operations }))
			.sort((a, b) => b.operations - a.operations || a.name.localeCompare(b.name));
	}

	async function load() {
		const token = gate.begin();
		const projectId = id.value;
		notVisible.value = false;
		error.value = '';
		// Reloading the same project (after an edit) keeps what is on screen; another project starts clean.
		if (project.value?.project_id !== projectId) {
			project.value = null;
			for (const b of all) b.value = { data: b === activity ? { data: null, truncated: false } : b === counts ? { samples: null, operations: null, tests: null, campaigns: null } : [], loading: false, error: '' };
		}
		if (!projectId) return;

		loading.value = true;
		try {
			const row = await getItem('projects', projectId, { fields: PROJECT_FIELDS });
			if (!gate.isCurrent(token)) return;
			project.value = row;
		} catch (e: any) {
			if (!gate.isCurrent(token)) return;
			if (isNotVisible(e)) notVisible.value = true;
			else error.value = `Could not load this project: ${errorText(e)}`;
			return;
		} finally {
			if (gate.isCurrent(token)) loading.value = false;
		}

		const byProject = { project_id: { _eq: projectId } };
		await Promise.all([
			fill(investigators, token, 'the investigators', async () => {
				const rows = await getItems('project_investigators', {
					filter: byProject,
					fields: ['user_id.id', 'user_id.first_name', 'user_id.last_name'],
					limit: -1,
				});
				return rows
					.map((r: any) => [r.user_id?.first_name, r.user_id?.last_name].filter(Boolean).join(' '))
					.filter(Boolean)
					.sort((a: string, b: string) => a.localeCompare(b));
			}),
			fill(counts, token, 'the totals', async () => {
				const [samples, operations, tests, campaignCount] = await Promise.all([
					count('physical_samples', byProject),
					count('manufacturing_operations', byProject),
					count('test_sessions', byProject),
					count('campaigns', byProject),
				]);
				return { samples, operations, tests, campaigns: campaignCount };
			}),
			fill(campaigns, token, 'campaigns', () => loadCampaigns(token, projectId)),
			fill(looseSamples, token, 'samples outside campaigns', () =>
				getItems('physical_samples', {
					filter: {
						_and: [byProject, { campaigns: { _none: { campaign_id: { _nnull: true } } } }],
					},
					fields: ['sample_id', 'sample_code', 'form', 'current_status', 'material_id.common_name'],
					sort: ['sample_code'],
					limit: LIST_CAP + 1,
				}),
			),
			fill(looseOperations, token, 'operations outside campaigns', () =>
				getItems('manufacturing_operations', {
					filter: { _and: [byProject, { campaign_id: { _null: true } }] },
					fields: ['operation_id', 'pass_code', 'process_category', 'operation_date', 'sample_id.sample_code'],
					sort: ['-operation_date'],
					limit: LIST_CAP + 1,
				}),
			),
			fill(looseTests, token, 'tests outside campaigns', () =>
				getItems('test_sessions', {
					filter: { _and: [byProject, { campaign_id: { _null: true } }] },
					fields: ['session_id', 'test_type', 'status', 'session_date', 'sample_id.sample_code'],
					sort: ['-session_date'],
					limit: LIST_CAP + 1,
				}),
			),
			fill(activity, token, 'activity', async () => {
				const rows = await fetchActivityRows(getItems, projectId);
				return {
					data: weeklyActivity(rows.ops.map((r) => r.operation_date), rows.tests.map((r) => r.session_date), DEFAULT_WEEKS),
					truncated: rows.truncated,
				};
			}),
			fill(equipment, token, 'equipment', () => loadEquipment(projectId)),
		]);
	}

	watch(id, load, { immediate: true });
	onBeforeUnmount(() => gate.cancel());

	return {
		project, loading, notVisible, error,
		investigators, counts, campaigns, looseSamples, looseOperations, looseTests, activity, equipment,
		reload: load,
	};
}
