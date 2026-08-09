import type { AxiosInstance } from 'axios';

/**
 * The subset of the Directus user record the dashboard uses for ownership scoping.
 * `role` may be a bare id string or a hydrated object depending on how far the
 * Directus user store has loaded, so both shapes are permitted.
 */
export interface ForceHostUser {
	role?: string | { id?: string; admin_access?: boolean };
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
	/** Base URL for the octree static server. No trailing slash. */
	readonly octreeUrl: string;
	/** Extra headers for raw `fetch` calls. Bearer token standalone; empty in Directus (cookie). */
	authHeaders(): Record<string, string>;
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
