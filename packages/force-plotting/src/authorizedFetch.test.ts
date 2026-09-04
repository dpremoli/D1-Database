// The regression gate for `diag preview: 401 {"detail":"not permitted"}`.
//
// directusClient gives axios a 401 -> refresh -> retry interceptor, but the diag and filter
// clients call raw `fetch` with host.authHeaders(). Once the short-lived access token
// expired, those requests 401'd forever while the rest of the app kept working. These cases
// pin the retry, the single-flight refresh, and the degrade paths.
import { describe, expect, it, beforeEach, vi } from 'vitest';
import {
	authorizedFetch, resetAuthRefresh, resetForceHost, setForceHost, type ForceHost,
} from './host';

function hostWith(over: Partial<ForceHost> = {}): ForceHost {
	return {
		api: {} as ForceHost['api'],
		currentUser: () => null,
		filterUrl: '/filter',
		diagUrl: '/diag',
		octreeUrl: '/octrees',
		authHeaders: () => ({}),
		fetchCredentials: 'omit',
		openRecord: () => {},
		downloadAsset: async () => {},
		dense: false,
		...over,
	};
}

const ok = () => new Response('ok', { status: 200 });
const unauthorized = () => new Response(JSON.stringify({ detail: 'not permitted' }), { status: 401 });

beforeEach(() => {
	resetForceHost();
	resetAuthRefresh();
	vi.restoreAllMocks();
});

describe('authorizedFetch', () => {
	it('refreshes once and retries when the access token has expired', async () => {
		let token = 'stale';
		const refreshAuth = vi.fn(async () => { token = 'fresh'; return true; });
		const fetchMock = vi.fn(async (_u: string, _i?: RequestInit) => (token === 'fresh' ? ok() : unauthorized()));
		vi.stubGlobal('fetch', fetchMock);
		setForceHost(hostWith({ refreshAuth, authHeaders: () => ({ Authorization: `Bearer ${token}` }) }));

		const res = await authorizedFetch('/diag/preview', { method: 'POST' });

		expect(res.status).toBe(200);
		expect(refreshAuth).toHaveBeenCalledTimes(1);
		expect(fetchMock).toHaveBeenCalledTimes(2);
		// The retry must carry the NEW token, not the one captured on the first attempt.
		expect((fetchMock.mock.calls[1][1] as RequestInit).headers)
			.toMatchObject({ Authorization: 'Bearer fresh' });
	});

	it('surfaces the 401 with its body intact when the refresh also fails', async () => {
		vi.stubGlobal('fetch', vi.fn(async () => unauthorized()));
		setForceHost(hostWith({ refreshAuth: async () => false }));

		const res = await authorizedFetch('/diag/preview');

		expect(res.status).toBe(401);
		// The caller builds its error message from this body; consuming it here would break that.
		expect(await res.text()).toContain('not permitted');
	});

	it('shares one in-flight refresh across concurrent 401s', async () => {
		// The workbench fires a preview plus one viewport recompute per spatial panel. Without
		// single-flight, every refresh after the first presents a rotated token and fails.
		let token = 'stale';
		const refreshAuth = vi.fn(async () => {
			await new Promise((r) => setTimeout(r, 5));
			token = 'fresh';
			return true;
		});
		vi.stubGlobal('fetch', vi.fn(async () => (token === 'fresh' ? ok() : unauthorized())));
		setForceHost(hostWith({ refreshAuth }));

		const all = await Promise.all([
			authorizedFetch('/diag/preview'),
			authorizedFetch('/diag/viewport'),
			authorizedFetch('/diag/viewport'),
		]);

		expect(all.every((r) => r.status === 200)).toBe(true);
		expect(refreshAuth).toHaveBeenCalledTimes(1);
	});

	it('does not retry a request whose caller already aborted', async () => {
		// A superseded keystroke must not spend a refresh.
		const refreshAuth = vi.fn(async () => true);
		vi.stubGlobal('fetch', vi.fn(async () => unauthorized()));
		setForceHost(hostWith({ refreshAuth }));
		const ac = new AbortController();
		ac.abort();

		const res = await authorizedFetch('/diag/preview', { signal: ac.signal });

		expect(res.status).toBe(401);
		expect(refreshAuth).not.toHaveBeenCalled();
	});

	it('makes a single attempt for a host with nothing to refresh (Directus cookie auth)', async () => {
		const fetchMock = vi.fn(async () => unauthorized());
		vi.stubGlobal('fetch', fetchMock);
		setForceHost(hostWith({ refreshAuth: undefined }));

		expect((await authorizedFetch('/diag/preview')).status).toBe(401);
		expect(fetchMock).toHaveBeenCalledTimes(1);
	});

	it('treats a throwing refreshAuth as a failed refresh rather than propagating', async () => {
		vi.stubGlobal('fetch', vi.fn(async () => unauthorized()));
		setForceHost(hostWith({ refreshAuth: async () => { throw new Error('network down'); } }));

		await expect(authorizedFetch('/diag/preview')).resolves.toMatchObject({ status: 401 });
	});

	it('applies the host credentials mode and merges auth over caller headers', async () => {
		const fetchMock = vi.fn(async (_u: string, _i?: RequestInit) => ok());
		vi.stubGlobal('fetch', fetchMock);
		setForceHost(hostWith({ authHeaders: () => ({ Authorization: 'Bearer t' }) }));

		await authorizedFetch('/diag/preview', {
			method: 'POST', headers: { 'Content-Type': 'application/json' },
		});

		const init = fetchMock.mock.calls[0][1] as RequestInit;
		expect(init.credentials).toBe('omit');
		expect(init.headers).toMatchObject({
			'Content-Type': 'application/json', Authorization: 'Bearer t',
		});
	});

	it('does not refresh on a non-401 failure', async () => {
		const refreshAuth = vi.fn(async () => true);
		vi.stubGlobal('fetch', vi.fn(async () => new Response('nope', { status: 422 })));
		setForceHost(hostWith({ refreshAuth }));

		expect((await authorizedFetch('/diag/preview')).status).toBe(422);
		expect(refreshAuth).not.toHaveBeenCalled();
	});
});
