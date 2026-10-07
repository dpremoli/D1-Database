import { describe, expect, it } from 'vitest';
import { campaignProgress, countsByKey, filterProjects, projectRole, projectStatusLabel, type ProjectRow } from './projects';
import { coOwnedByMe, forceErrorOnMyOperations, ownedByMe, projectsMine, samplesMine } from './mine';

const project = (over: Partial<ProjectRow> & { project_id: string }): ProjectRow => ({
	project_code: 'P',
	project_name: 'Project',
	is_active: true,
	...over,
});

const pi = project({
	project_id: 'a',
	project_code: 'AI4340',
	project_name: 'FAST rolled plate detection',
	principal_investigator_person: { person_id: 'p1', full_name: 'Ada', user_id: 'u1' },
});
const inv = project({
	project_id: 'b',
	project_code: 'MA100',
	project_name: 'Machining of Ti',
	is_active: false,
	secondary_investigators: [{ user_id: 'u2' }, { user_id: { id: 'u1' } }],
});
const other = project({ project_id: 'c', project_code: 'ZZ9', project_name: 'Unrelated' });

describe('projectRole', () => {
	it('is pi, investigator (bare or expanded id) or null', () => {
		expect(projectRole(pi, 'u1')).toBe('pi');
		expect(projectRole(inv, 'u1')).toBe('investigator');
		expect(projectRole(inv, 'u2')).toBe('investigator');
		expect(projectRole(other, 'u1')).toBeNull();
	});
	it('is null without a user id, and the PI role wins', () => {
		expect(projectRole(pi, null)).toBeNull();
		const both = { ...pi, secondary_investigators: [{ user_id: 'u1' }] };
		expect(projectRole(both, 'u1')).toBe('pi');
	});
});

describe('filterProjects', () => {
	const all = [pi, inv, other];
	const f = (over: Partial<Parameters<typeof filterProjects>[1]>) =>
		filterProjects(all, { role: 'all', status: 'all', query: '', ...over }, 'u1').map((p) => p.project_id);
	it('shows everything by default', () => expect(f({})).toEqual(['a', 'b', 'c']));
	it('filters by role', () => {
		expect(f({ role: 'pi' })).toEqual(['a']);
		expect(f({ role: 'investigator' })).toEqual(['b']);
		expect(f({ role: 'any' })).toEqual(['a', 'b']);
	});
	it('filters by status; a null is_active counts as active', () => {
		expect(f({ status: 'active' })).toEqual(['a', 'c']);
		expect(f({ status: 'inactive' })).toEqual(['b']);
		const unknown = filterProjects([project({ project_id: 'x', is_active: null })], { role: 'all', status: 'active', query: '' }, 'u1');
		expect(unknown).toHaveLength(1);
	});
	it('searches code or name, case-insensitively', () => {
		expect(f({ query: 'ai43' })).toEqual(['a']);
		expect(f({ query: ' machining ' })).toEqual(['b']);
		expect(f({ query: 'nothing' })).toEqual([]);
	});
	it('combines filters', () => expect(f({ role: 'any', status: 'active' })).toEqual(['a']));
	it('role filters match nothing without a user id', () => {
		expect(filterProjects(all, { role: 'any', status: 'all', query: '' }, null)).toEqual([]);
	});
});

describe('projectStatusLabel', () => {
	it('maps is_active', () => {
		expect(projectStatusLabel(true)).toBe('Active');
		expect(projectStatusLabel(false)).toBe('Inactive');
		expect(projectStatusLabel(null)).toBe('Active');
	});
});

describe('campaignProgress', () => {
	const campaigns = [
		{ campaign_id: 'm', campaign_type: 'machining_trial' },
		{ campaign_id: 't', campaign_type: 'testing_campaign' },
		{ campaign_id: 'e', campaign_type: 'machining_trial' },
	];
	const result = campaignProgress({
		campaigns,
		samplesByCampaign: new Map([['m', 4], ['t', 2]]),
		operations: [
			{ operation_id: 'o1', campaign_id: 'm', process_category: 'machining' },
			{ operation_id: 'o2', campaign_id: 'm', process_category: 'machining' },
			{ operation_id: 'o3', campaign_id: 'm', process_category: 'machining' },
			{ operation_id: 'o4', campaign_id: 'm', process_category: 'machining' },
			{ operation_id: 'o5', campaign_id: 'm', process_category: 'imaging' },
		],
		tests: [
			{ campaign_id: 't', status: 'analysed' },
			{ campaign_id: 't', status: 'processed' },
			{ campaign_id: 't', status: 'failed' },
			{ campaign_id: 'm', status: 'registered' },
		],
		analyses: [
			{ operation_id: 'o1', status: 'done' },
			{ operation_id: 'o1', status: 'done' },
			{ operation_id: 'o2', status: 'done' },
			{ operation_id: 'o2', status: 'error' },
			{ operation_id: 'o3', status: 'skipped' },
		],
	});
	it('counts samples, operations and tests per campaign', () => {
		expect(result.get('m')).toMatchObject({ samples: 4, operations: 5, tests: 1 });
		expect(result.get('t')).toMatchObject({ samples: 2, operations: 0, tests: 3 });
		expect(result.get('e')).toMatchObject({ samples: 0, operations: 0, tests: 0 });
	});
	it('machining trial: analysed over machining operations, skipped and non-machining left out', () => {
		// o1 done, o2 has an error (open), o3 all skipped (left out), o4 no files yet (counted, not done),
		// o5 imaging with no files (left out)
		expect(result.get('m')!.progress).toEqual({ label: 'Force analysed', done: 1, total: 3 });
	});
	it('testing campaign: tests complete over all tests', () => {
		expect(result.get('t')!.progress).toEqual({ label: 'Tests complete', done: 2, total: 3 });
	});
	it('an empty campaign has a 0 / 0 bar, not NaN', () => {
		expect(result.get('e')!.progress.total).toBe(0);
	});
});

describe('countsByKey', () => {
	it('coerces string counts and drops null keys', () => {
		const m = countsByKey([{ project_id: 'a', count: '3' }, { project_id: null, count: '9' }, { project_id: 'b', count: 2 }], 'project_id');
		expect([...m]).toEqual([['a', 3], ['b', 2]]);
	});
});

describe('mine filters', () => {
	it('use the ADR-0011 involvement paths with $CURRENT_USER', () => {
		expect(ownedByMe).toEqual({ owner_person_id: { user_id: { _eq: '$CURRENT_USER' } } });
		expect(coOwnedByMe).toEqual({ co_owners: { _some: { user_id: { _eq: '$CURRENT_USER' } } } });
		expect(samplesMine).toEqual({ _or: [ownedByMe, coOwnedByMe] });
		expect(JSON.stringify(projectsMine)).toContain('principal_investigator_person');
		expect(JSON.stringify(projectsMine)).toContain('secondary_investigators');
		expect(forceErrorOnMyOperations).toEqual({
			_and: [ownedByMe, { force_analyses: { _some: { status: { _eq: 'error' } } } }],
		});
	});
});
