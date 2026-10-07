import { describe, expect, it } from 'vitest';
import { itemPermissionsUrl, updateAccess } from './canUpdate';

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
