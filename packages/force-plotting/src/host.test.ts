import { describe, expect, it, beforeEach } from 'vitest';
import { setForceHost, useForceHost, resetForceHost, type ForceHost } from './host';

const stub: ForceHost = {
	api: {} as ForceHost['api'],
	currentUser: () => ({ admin_access: true }),
	filterUrl: '/filter',
	octreeUrl: '/octrees',
	authHeaders: () => ({}),
	fetchCredentials: 'include',
	openRecord: () => {},
	downloadAsset: async () => {},
	dense: false,
};

describe('force host', () => {
	beforeEach(() => resetForceHost());

	it('throws a diagnostic error when no host has been installed', () => {
		expect(() => useForceHost()).toThrow(/setForceHost/);
	});

	it('returns the installed host', () => {
		setForceHost(stub);
		expect(useForceHost().filterUrl).toBe('/filter');
	});

	it('reads through getters so runtime config changes are picked up', () => {
		let url = '/filter';
		setForceHost({ ...stub, get filterUrl() { return url; } });
		url = 'https://elsewhere.example/filter';
		expect(useForceHost().filterUrl).toBe('https://elsewhere.example/filter');
	});
});
