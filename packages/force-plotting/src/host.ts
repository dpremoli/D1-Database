import type { AxiosInstance } from 'axios';

/**
 * The subset of the Directus user record the dashboard uses for ownership scoping.
 * `role` may be a bare id string or a hydrated object depending on how far the
 * Directus user store has loaded, so both shapes are permitted. It is also nullable:
 * Directus genuinely allows a user with no role assigned, and both hosts' user types
 * reflect that with `role: null` — ForceDashboard.vue's `isAdminRole` already treats
 * that safely (optional chaining falls through to `undefined`, matching no admin role id).
 */
export interface ForceHostUser {
	role?: string | { id?: string; admin_access?: boolean } | null;
	admin_access?: boolean;
	[key: string]: unknown;
}

/**
 * Everything the shared plotting code needs from its embedding environment.
 *
 * Two environments implement this: the Directus admin module (same-origin,
 * cookie-authenticated, in-app router) and the standalone force app
 * (cross-origin, Bearer-authenticated, separate tab). These were previously two
 * forked copies of the whole dashboard; this interface is the entire real
 * difference between them.
 *
 * `filterUrl` and `octreeUrl` are declared readonly rather than as methods so
 * implementations can supply them as getters — the standalone app's service URLs
 * are reconfigurable at runtime via Settings > General, so a value captured once
 * at setup would go stale.
 */
export interface ForceHost {
	/** Authenticated axios instance: Directus's `useApi()` or the standalone Bearer client. */
	api: AxiosInstance;
	/** Current user, for admin-role/ownership scoping. Called during computed evaluation so reactivity tracks. */
	currentUser(): ForceHostUser | null;
	/** Base URL for the filter sidecar (/run, /fft, /spectrogram). No trailing slash. */
	readonly filterUrl: string;
	/** Base URL for the diag preview sidecar (/preview). No trailing slash. Same runtime-
	 *  reconfigurable getter treatment as filterUrl. */
	readonly diagUrl: string;
	/** Base URL for the octree static server. No trailing slash. */
	readonly octreeUrl: string;
	/** Extra headers for raw `fetch` calls. Bearer token standalone; empty in Directus (cookie). */
	authHeaders(): Record<string, string>;
	/**
	 * Exchange the refresh token for a new access token, resolving false when it cannot.
	 *
	 * `authHeaders()` reads whatever access token the store holds at that moment, so raw
	 * `fetch` calls had no equivalent of directusClient's axios 401-refresh interceptor:
	 * once the short-lived access token expired every sidecar request 401'd forever, while
	 * the rest of the app carried on refreshing transparently. `authorizedFetch` uses this
	 * hook to close that gap.
	 *
	 * Optional: the Directus module authenticates by session cookie and has nothing to
	 * refresh, so it omits this and `authorizedFetch` degrades to a single attempt.
	 */
	refreshAuth?(): Promise<boolean>;
	/** Credentials mode for raw `fetch` calls. 'include' in Directus (session cookie); 'omit' standalone. */
	fetchCredentials: RequestCredentials;
	/** Open a Directus record editor for the given collection and primary key. */
	openRecord(collection: string, id: string): void;
	/** Download a Directus file by id, handling whichever auth style applies. */
	downloadAsset(fileId: string): Promise<void>;
	/** Tighter padding for the standalone app, which has no Directus chrome competing for space. */
	dense: boolean;
}

// A module-level singleton rather than Vue provide/inject: filterChain.ts is a
// plain module with no component instance, so inject() is unavailable there.
let current: ForceHost | null = null;

export function setForceHost(host: ForceHost): void {
	current = host;
}

export function useForceHost(): ForceHost {
	if (!current) {
		throw new Error(
			'@d1/force-plotting: no host installed. Call setForceHost() in the consuming ' +
			'component before rendering ForceDashboard.',
		);
	}
	return current;
}

/** Test-only: clear the installed host so cases start from a known state. */
export function resetForceHost(): void {
	current = null;
}

// One in-flight refresh shared by every concurrent 401. The workbench fires several sidecar
// requests per interaction (a preview plus one viewport recompute per spatial panel); without
// this they would each trigger their own refresh, and every refresh after the first would
// present an already-rotated refresh token and fail.
let refreshing: Promise<boolean> | null = null;

function refreshOnce(host: ForceHost): Promise<boolean> {
	if (!host.refreshAuth) return Promise.resolve(false);
	if (!refreshing) {
		refreshing = Promise.resolve(host.refreshAuth())
			.catch(() => false)
			.finally(() => { refreshing = null; });
	}
	return refreshing;
}

/** Test-only: drop any in-flight refresh so cases do not leak into one another. */
export function resetAuthRefresh(): void {
	refreshing = null;
}

/**
 * `fetch` with the host's auth headers, retried once through `refreshAuth` on a 401.
 *
 * This is the raw-fetch counterpart of directusClient's axios response interceptor. Sidecar
 * clients (diag preview, diag viewport, filter chain) must go through it rather than calling
 * `fetch` with `host.authHeaders()` directly, or they resume 401ing the moment the access
 * token expires.
 *
 * The retry is deliberately not attempted when the caller's signal has already aborted: a
 * debounced keystroke that superseded this request should not spend a refresh on it.
 */
export async function authorizedFetch(url: string, init: RequestInit = {}): Promise<Response> {
	const host = useForceHost();
	const send = () => fetch(url, {
		...init,
		credentials: host.fetchCredentials,
		headers: { ...(init.headers as Record<string, string> | undefined), ...host.authHeaders() },
	});

	const res = await send();
	// 403 as well as 401: Directus answers a MISSING or unusable token with 403 on item
	// reads, and diag-service forwards whichever status Directus gave it. Retrying only on
	// 401 therefore left exactly the expired-token case unhandled -- the one this exists for.
	// A genuine permissions 403 costs one wasted refresh and then fails identically.
	const retryable = res.status === 401 || res.status === 403;
	if (!retryable || !host.refreshAuth || init.signal?.aborted) return res;

	// The 401 body is left unread on purpose. When the refresh fails this response is handed
	// back to the caller, which reads it to build its error message — draining it here would
	// make that read throw on an already-consumed body.
	if (!(await refreshOnce(host))) return res;
	if (init.signal?.aborted) return res;
	return send();
}
