// Pure logic of the Projects index and the Project page: who has which role on a project, the
// index's filters and search, and the per-campaign counts and progress. No network, no Vue.
//
// Involvement columns are those of ADR-0011: the PI is `principal_investigator_person` (a people
// row whose `user_id` is the login), investigators are the M2M alias `secondary_investigators`
// whose `user_id` is a directus_users id. Nothing here reads the hidden legacy columns.

export type ProjectRole = 'pi' | 'investigator';
// 'all' = every project the user can read; 'any' = projects where the user is PI or investigator.
export type RoleFilter = 'all' | 'any' | ProjectRole;
export type StatusFilter = 'all' | 'active' | 'inactive';

export interface ProjectRow {
	project_id: string;
	project_code: string;
	project_name: string;
	is_active?: boolean | null;
	principal_investigator_person?: { person_id?: string; full_name?: string; user_id?: string | null } | null;
	// `user_id` is a bare id when only the id was requested, or an expanded user.
	secondary_investigators?: Array<{ user_id?: string | { id?: string } | null }> | null;
}

const userIdOf = (v: string | { id?: string } | null | undefined): string | null =>
	v && typeof v === 'object' ? (v.id ?? null) : (v ?? null);

// The signed-in user's role on a project. The PI wins when someone is both.
export function projectRole(project: ProjectRow, userId: string | null | undefined): ProjectRole | null {
	if (!userId) return null;
	if (project.principal_investigator_person?.user_id === userId) return 'pi';
	const isInvestigator = (project.secondary_investigators ?? []).some((i) => userIdOf(i?.user_id) === userId);
	return isInvestigator ? 'investigator' : null;
}

export const projectStatusLabel = (isActive: boolean | null | undefined): string =>
	isActive === false ? 'Inactive' : 'Active';

export interface ProjectFilters {
	role: RoleFilter;
	status: StatusFilter;
	query: string;
}

// Roles other than 'all' need the user's id.
// The search is a case-insensitive substring of the code or the name; blank matches everything.
export function filterProjects<T extends ProjectRow>(
	projects: ReadonlyArray<T>,
	filters: ProjectFilters,
	userId: string | null | undefined,
): T[] {
	const q = filters.query.trim().toLowerCase();
	return projects.filter((p) => {
		if (filters.role !== 'all') {
			const role = projectRole(p, userId);
			if (filters.role === 'any' ? role === null : role !== filters.role) return false;
		}
		if (filters.status === 'active' && p.is_active === false) return false;
		if (filters.status === 'inactive' && p.is_active !== false) return false;
		if (q && !`${p.project_code} ${p.project_name}`.toLowerCase().includes(q)) return false;
		return true;
	});
}

// ── Per-campaign counts and progress ────────────────────────────────────────────────────────────

// test_sessions.status is the lifecycle from migration 20260619000013; a test is complete once its
// data is processed or analysed.
const TEST_DONE = ['processed', 'analysed'];

export interface CampaignLite {
	campaign_id: string;
	campaign_type?: string | null;
}
export interface OpLite {
	operation_id: string;
	campaign_id?: string | null;
	process_category?: string | null;
}
export interface TestLite {
	campaign_id?: string | null;
	status?: string | null;
}
export interface AnalysisLite {
	operation_id: string;
	status?: string | null;
}

export interface CampaignProgress {
	campaign_id: string;
	samples: number;
	operations: number;
	tests: number;
	/** The progress bar: what "done" means depends on the campaign type. */
	progress: { label: string; done: number; total: number };
}

// One operation can have several force files; it counts as analysed when none is still queued,
// processing or in error and at least one is done (worst-first, as the campaign overview does).
function operationAnalysis(rows: ReadonlyArray<AnalysisLite>): 'none' | 'done' | 'skipped' | 'open' {
	const s = rows.map((r) => r.status).filter(Boolean);
	if (!s.length) return 'none';
	if (s.some((x) => x === 'error' || x === 'processing' || x === 'pending')) return 'open';
	return s.includes('done') ? 'done' : 'skipped';
}

// Machining trials show "analysed n / m" over their machining operations (an operation whose files
// were all skipped is left out, otherwise the bar could never fill); testing campaigns show
// "tests complete n / m". `samplesByCampaign` comes from the campaign_samples junction.
export function campaignProgress(input: {
	campaigns: ReadonlyArray<CampaignLite>;
	samplesByCampaign: ReadonlyMap<string, number>;
	operations: ReadonlyArray<OpLite>;
	tests: ReadonlyArray<TestLite>;
	analyses: ReadonlyArray<AnalysisLite>;
}): Map<string, CampaignProgress> {
	const analysesByOp = new Map<string, AnalysisLite[]>();
	for (const a of input.analyses) {
		const list = analysesByOp.get(a.operation_id);
		if (list) list.push(a);
		else analysesByOp.set(a.operation_id, [a]);
	}
	const out = new Map<string, CampaignProgress>();
	for (const c of input.campaigns) {
		const ops = input.operations.filter((o) => o.campaign_id === c.campaign_id);
		const tests = input.tests.filter((t) => t.campaign_id === c.campaign_id);
		let progress: CampaignProgress['progress'];
		if (c.campaign_type === 'testing_campaign') {
			progress = {
				label: 'Tests complete',
				done: tests.filter((t) => TEST_DONE.includes(t.status ?? '')).length,
				total: tests.length,
			};
		} else {
			const states = ops.map((o) => ({ o, state: operationAnalysis(analysesByOp.get(o.operation_id) ?? []) }));
			const counted = states.filter(({ o, state }) => (o.process_category === 'machining' || state !== 'none') && state !== 'skipped');
			progress = { label: 'Force analysed', done: counted.filter((x) => x.state === 'done').length, total: counted.length };
		}
		out.set(c.campaign_id, {
			campaign_id: c.campaign_id,
			samples: input.samplesByCampaign.get(c.campaign_id) ?? 0,
			operations: ops.length,
			tests: tests.length,
			progress,
		});
	}
	return out;
}

// Rows of `aggregate[count]=*&groupBy[]=<key>` as a Map. Directus returns the count as a string
// for Postgres bigint, so it is coerced; a group with no key (null) is dropped.
export function countsByKey(rows: ReadonlyArray<Record<string, unknown>>, key: string): Map<string, number> {
	const out = new Map<string, number>();
	for (const r of rows) {
		const k = r[key];
		if (k === null || k === undefined || k === '') continue;
		const n = Number(r.count);
		out.set(String(k), Number.isFinite(n) ? n : 0);
	}
	return out;
}
