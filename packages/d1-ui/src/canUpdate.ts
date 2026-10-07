// Pure parts of useCanUpdate: the URL of Directus 11's item-permissions endpoint and how to read
// its answer. Row-level visibility (ADR-0011) means a user can read a record they may not edit
// (an investigator, someone who only sees it through a campaign...), so a page asks before it
// offers Edit.

// `GET /permissions/me/:collection/:pk` answers `{ data: ItemPermissions }` (@directus/types):
// `update.access` is true when the signed-in user's update permission covers this very row.
export function itemPermissionsUrl(collection: string, id: string): string {
	return `/permissions/me/${encodeURIComponent(collection)}/${encodeURIComponent(id)}`;
}

// true / false when the answer says so; null when it does not (unknown). Callers show the Edit
// button unless this is exactly false: the server enforces the rule anyway, so a failed or odd
// answer must not take Edit away from someone who may use it.
export function updateAccess(body: unknown): boolean | null {
	const access = (body as any)?.data?.update?.access;
	return typeof access === 'boolean' ? access : null;
}

// Messages for a refused write (HTTP 403 / FORBIDDEN) on a record the user may read but not change.
export const NOT_OWNER_MESSAGE = 'Only the owner or a co-owner can change this record.';
export const NOT_YOUR_RECORD_MESSAGE = 'You can only add records you own or co-own.';

export const NOT_CAMPAIGN_OWNER_MESSAGE = "Only the campaign's owner can change it.";
export const NOT_PI_MESSAGE = "Only the project's PI can change it.";

// The refusal text for a record of `collection` when the server gave no reason of its own: campaigns
// have no co-owners and projects are the PI's; samples, operations and tests are the owner's or a
// co-owner's. Anything else gets the generic owner text.
export function notOwnerMessage(collection?: string | null): string {
	if (collection === 'campaigns') return NOT_CAMPAIGN_OWNER_MESSAGE;
	if (collection === 'projects') return NOT_PI_MESSAGE;
	return NOT_OWNER_MESSAGE;
}

// The d1-access-guard's own reason for a refusal: it throws a 403 FORBIDDEN whose
// `extensions.reason` (also the message) says exactly what was refused, for example that only the
// owner may change the owner. Directus's stock 403 ("You don't have permission to access this.")
// has no reason, so it gives null and the caller falls back to notOwnerMessage().
export function forbiddenReason(e: any): string | null {
	const reason = e?.response?.data?.errors?.[0]?.extensions?.reason;
	return typeof reason === 'string' && reason.trim() ? reason.trim() : null;
}
