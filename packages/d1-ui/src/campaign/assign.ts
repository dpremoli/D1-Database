// What the campaign pickers send to Directus when a record is put into (or taken out of) a
// campaign. Pure request builders plus one small async helper, unit tested without Vue.
//
// Two rules live here:
//  1. The campaign_id change is conditional (add only where `campaign_id` is still null, remove only
//     where it is this campaign), so two people or tabs cannot take the same record. Directus
//     answers a batch update with the rows it changed; an empty answer means someone got there first.
//  2. A record picked into a campaign also gets the campaign's project when it has none (the
//     d1-project-inherit rule), and a project it already has is never overwritten. That is a second,
//     conditional request (`project_id _null`), because one batch body cannot be per-row.

import { errorText, isForbidden } from '../format';
import { itemPermissionsUrl, NOT_OWNER_MESSAGE, NOT_YOUR_RECORD_MESSAGE, updateAccess } from '../canUpdate';

export interface BatchPatch {
	query: { filter: Record<string, unknown> };
	data: Record<string, unknown>;
}

// Add (`campaign` = this campaign's id) or remove (`campaign` = null) one record.
export function campaignAssignPatch(pk: string, id: string, campaignId: string, campaign: string | null): BatchPatch {
	return {
		query: { filter: { [pk]: { _eq: id }, campaign_id: campaign ? { _null: true } : { _eq: campaignId } } },
		data: { campaign_id: campaign },
	};
}

// Copies `projectId` onto the one record, only where its project_id is still null.
export function projectInheritPatch(pk: string, id: string, projectId: string): BatchPatch {
	return { query: { filter: { [pk]: { _eq: id }, project_id: { _null: true } } }, data: { project_id: projectId } };
}

// The message for a conditional campaign change that touched no row, or null when it changed one.
// An empty answer has two causes that look the same: someone got there first, or the user's update
// rule (row-level visibility, ADR-0011) does not cover the record, so the batch matched nothing.
// `canUpdate` (from the item-permissions endpoint) tells them apart; false means "not permitted".
export function lostRaceMessage(changed: unknown, adding: boolean, label: string, canUpdate?: boolean | null): string | null {
	if (!Array.isArray(changed) || changed.length) return null;
	if (canUpdate === false) return `${label}: ${notPermittedMessage(adding)}`;
	return adding ? `${label} is already in another campaign.` : `${label} is no longer in this campaign.`;
}

// What to tell a user whose write was refused: adding needs a record they own or co-own, changing
// or removing needs the owner or a co-owner.
export function notPermittedMessage(adding: boolean): string {
	return adding ? NOT_YOUR_RECORD_MESSAGE : NOT_OWNER_MESSAGE;
}

// A refused write (403) as text, null for any other failure (the caller shows errorText then).
export function forbiddenWriteMessage(e: unknown, adding: boolean): string | null {
	return isForbidden(e) ? notPermittedMessage(adding) : null;
}

interface Api {
	get(url: string, config?: any): Promise<any>;
	patch(url: string, body?: any): Promise<any>;
}

// May the signed-in user update this record? null when unknown (the read failed).
export async function readCanUpdate(api: Api, collection: string, id: string): Promise<boolean | null> {
	try {
		return updateAccess((await api.get(itemPermissionsUrl(collection, id))).data);
	} catch {
		return null;
	}
}

// lostRaceMessage for a batch answer, asking the permissions endpoint only when the answer is empty.
export async function changeOutcomeMessage(
	api: Api,
	collection: string,
	id: string,
	changed: unknown,
	adding: boolean,
	label: string,
): Promise<string | null> {
	if (!Array.isArray(changed) || changed.length) return null;
	return lostRaceMessage(changed, adding, label, await readCanUpdate(api, collection, id));
}

// The project of campaign `campaignId` as the signed-in user sees it; null when it has none or the
// read failed (inheriting is then skipped, the project rule falls back to the campaign anyway).
export async function readCampaignProject(api: Api, campaignId: string): Promise<string | null> {
	try {
		const res = await api.get(`/items/campaigns/${campaignId}`, { params: { fields: 'project_id' } });
		const v = res.data?.data?.project_id;
		return (v && typeof v === 'object' ? v.project_id : v) || null;
	} catch {
		return null;
	}
}

// After `id` was put into the campaign: give it the campaign's project if it has none. Returns an
// error text to show, or '' (nothing to do, done, or the role may not edit that field).
export async function inheritCampaignProject(
	api: Api,
	collection: string,
	pk: string,
	id: string,
	campaignId: string,
	label: string,
): Promise<string> {
	const projectId = await readCampaignProject(api, campaignId);
	if (!projectId) return '';
	try {
		await api.patch(`/items/${collection}`, projectInheritPatch(pk, id, projectId));
		return '';
	} catch (e) {
		// A role that may add the record to the campaign but not edit it: nothing to report.
		return isForbidden(e) ? '' : `${label} was added, but its project could not be set: ${errorText(e)}`;
	}
}
