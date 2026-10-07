import { describe, expect, it, vi } from 'vitest';
import {
	campaignAssignPatch, changeOutcomeMessage, forbiddenWriteMessage, inheritCampaignProject, lostRaceMessage, projectInheritPatch,
	readCampaignProject, readCanUpdate,
} from './assign';

describe('campaignAssignPatch', () => {
	it('adds only where the record is in no campaign', () => {
		expect(campaignAssignPatch('operation_id', 'o1', 'c1', 'c1')).toEqual({
			query: { filter: { operation_id: { _eq: 'o1' }, campaign_id: { _null: true } } },
			data: { campaign_id: 'c1' },
		});
	});
	it('removes only where the record is in this campaign', () => {
		expect(campaignAssignPatch('operation_id', 'o1', 'c1', null)).toEqual({
			query: { filter: { operation_id: { _eq: 'o1' }, campaign_id: { _eq: 'c1' } } },
			data: { campaign_id: null },
		});
	});
});

describe('projectInheritPatch', () => {
	it('only touches a record whose project is still null', () => {
		expect(projectInheritPatch('session_id', 't1', 'p1')).toEqual({
			query: { filter: { session_id: { _eq: 't1' }, project_id: { _null: true } } },
			data: { project_id: 'p1' },
		});
	});
});

describe('lostRaceMessage', () => {
	it('is null when a row changed or the answer is not a list', () => {
		expect(lostRaceMessage([{ id: 1 }], true, 'X')).toBeNull();
		expect(lostRaceMessage(undefined, true, 'X')).toBeNull();
	});
	it('says who got there first', () => {
		expect(lostRaceMessage([], true, 'OP-1')).toBe('OP-1 is already in another campaign.');
		expect(lostRaceMessage([], false, 'OP-1')).toBe('OP-1 is no longer in this campaign.');
	});
});

describe('lostRaceMessage and permissions', () => {
	it('says "not permitted" instead of "lost the race" when the user may not update the record', () => {
		expect(lostRaceMessage([], true, 'OP-1', false)).toBe('OP-1: You can only add records you own or co-own.');
		expect(lostRaceMessage([], false, 'OP-1', false)).toBe('OP-1: Only the owner or a co-owner can change this record.');
	});
	it('keeps the race wording when the user may update, or it is unknown', () => {
		expect(lostRaceMessage([], true, 'OP-1', true)).toBe('OP-1 is already in another campaign.');
		expect(lostRaceMessage([], true, 'OP-1', null)).toBe('OP-1 is already in another campaign.');
	});
	it('maps a 403 to the not-permitted text and leaves other errors alone', () => {
		expect(forbiddenWriteMessage({ response: { status: 403 } }, true)).toBe('You can only add records you own or co-own.');
		expect(forbiddenWriteMessage({ response: { status: 403 } }, false)).toBe('Only the owner or a co-owner can change this record.');
		expect(forbiddenWriteMessage({ response: { status: 500 } }, true)).toBeNull();
	});
});

describe('changeOutcomeMessage', () => {
	const perm = (access: unknown) => ({ get: vi.fn().mockResolvedValue({ data: { data: { update: { access } } } }), patch: vi.fn() });
	it('asks nothing when a row changed', async () => {
		const api = perm(false);
		expect(await changeOutcomeMessage(api, 'test_sessions', 't1', [{ session_id: 't1' }], true, 'T')).toBeNull();
		expect(api.get).not.toHaveBeenCalled();
	});
	it('tells lost race from not permitted on an empty answer', async () => {
		expect(await changeOutcomeMessage(perm(false), 'test_sessions', 't1', [], true, 'T')).toContain('own or co-own');
		expect(await changeOutcomeMessage(perm(true), 'test_sessions', 't1', [], true, 'T')).toBe('T is already in another campaign.');
		const failing = { get: vi.fn().mockRejectedValue(new Error('x')), patch: vi.fn() };
		expect(await readCanUpdate(failing, 'test_sessions', 't1')).toBeNull();
	});
});

const apiWith = (project: unknown, patch = vi.fn().mockResolvedValue({})) => ({
	get: vi.fn().mockResolvedValue({ data: { data: { project_id: project } } }),
	patch,
});

describe('readCampaignProject', () => {
	it('reads a bare or expanded project id, null when none or unreadable', async () => {
		expect(await readCampaignProject(apiWith('p1'), 'c1')).toBe('p1');
		expect(await readCampaignProject(apiWith({ project_id: 'p2' }), 'c1')).toBe('p2');
		expect(await readCampaignProject(apiWith(null), 'c1')).toBeNull();
		expect(await readCampaignProject({ get: vi.fn().mockRejectedValue(new Error('x')), patch: vi.fn() }, 'c1')).toBeNull();
	});
});

describe('inheritCampaignProject', () => {
	it('patches conditionally with the campaign project', async () => {
		const api = apiWith('p1');
		expect(await inheritCampaignProject(api, 'test_sessions', 'session_id', 't1', 'c1', 'The test')).toBe('');
		expect(api.patch).toHaveBeenCalledWith('/items/test_sessions', projectInheritPatch('session_id', 't1', 'p1'));
	});
	it('sends nothing when the campaign has no project', async () => {
		const api = apiWith(null);
		expect(await inheritCampaignProject(api, 'test_sessions', 'session_id', 't1', 'c1', 'The test')).toBe('');
		expect(api.patch).not.toHaveBeenCalled();
	});
	it('stays quiet when the role may not edit the record, reports other failures', async () => {
		const forbidden = { response: { status: 403 } };
		expect(await inheritCampaignProject(apiWith('p1', vi.fn().mockRejectedValue(forbidden)), 'test_sessions', 'session_id', 't1', 'c1', 'T')).toBe('');
		const msg = await inheritCampaignProject(apiWith('p1', vi.fn().mockRejectedValue(new Error('boom'))), 'test_sessions', 'session_id', 't1', 'c1', 'T');
		expect(msg).toContain('T was added, but its project could not be set');
	});
});
