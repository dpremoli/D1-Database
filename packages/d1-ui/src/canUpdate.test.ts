import { describe, expect, it } from 'vitest';
import { forbiddenReason, itemPermissionsUrl, notOwnerMessage, updateAccess } from './canUpdate';

describe('itemPermissionsUrl', () => {
	it('builds the Directus 11 item-permissions path and encodes the key', () => {
		expect(itemPermissionsUrl('physical_samples', 'a-b')).toBe('/permissions/me/physical_samples/a-b');
		expect(itemPermissionsUrl('c', 'x/y')).toBe('/permissions/me/c/x%2Fy');
	});
});

describe('updateAccess', () => {
	it('reads update.access', () => {
		expect(updateAccess({ data: { update: { access: true }, delete: { access: false }, share: { access: false } } })).toBe(true);
		expect(updateAccess({ data: { update: { access: false } } })).toBe(false);
	});
	it('is unknown (null) for anything else, so Edit stays available', () => {
		expect(updateAccess(undefined)).toBeNull();
		expect(updateAccess({})).toBeNull();
		expect(updateAccess({ data: {} })).toBeNull();
		expect(updateAccess({ data: { update: { access: 'yes' } } })).toBeNull();
	});
});

describe('notOwnerMessage', () => {
	it('names who may change the record, per collection', () => {
		for (const c of ['physical_samples', 'manufacturing_operations', 'test_sessions', undefined]) {
			expect(notOwnerMessage(c)).toBe('Only the owner or a co-owner can change this record.');
		}
		expect(notOwnerMessage('campaigns')).toBe("Only the campaign's owner can change it.");
		expect(notOwnerMessage('projects')).toBe("Only the project's PI can change it.");
	});
});

describe('forbiddenReason', () => {
	const guard = (reason: unknown) => ({ response: { status: 403, data: { errors: [{ message: 'm', extensions: { code: 'FORBIDDEN', reason } }] } } });
	it("reads the guard's extensions.reason", () => {
		expect(forbiddenReason(guard('Only the owner can change the owner.'))).toBe('Only the owner can change the owner.');
	});
	it('is null for a stock 403, an empty reason or no error', () => {
		expect(forbiddenReason({ response: { status: 403, data: { errors: [{ message: "You don't have permission" }] } } })).toBeNull();
		expect(forbiddenReason(guard('  '))).toBeNull();
		expect(forbiddenReason(guard(5))).toBeNull();
		expect(forbiddenReason(undefined)).toBeNull();
	});
});
