// The Directus REST client used by the ported plotting components (via the useApi() shim).
// It is a plain axios instance pointed at the configured Directus origin, with:
//   - a request interceptor that attaches the Bearer access token, and
//   - a response interceptor that, on 401, transparently refreshes the token once and retries,
//     falling back to the unauthorized handler (→ /login) when the refresh also fails.
// This reproduces, cross-origin, what the Directus session cookie did for the embedded module.
import axios, { type AxiosError, type InternalAxiosRequestConfig } from 'axios';
import { getConfig } from './config';
import { authStore } from './authStore';

let onUnauthorized: (() => void) | null = null;
export function setUnauthorizedHandler(fn: () => void): void {
	onUnauthorized = fn;
}

export const api = axios.create();

api.interceptors.request.use((cfg: InternalAxiosRequestConfig) => {
	// baseURL is resolved per-request so a runtime /config.json (loaded at boot) is honoured.
	cfg.baseURL = getConfig().directusUrl;
	const tok = authStore.getAccessToken();
	if (tok) {
		cfg.headers.set('Authorization', `Bearer ${tok}`);
	}
	return cfg;
});

api.interceptors.response.use(
	(res) => res,
	async (error: AxiosError) => {
		const cfg = error.config as (InternalAxiosRequestConfig & { _retried?: boolean }) | undefined;
		const status = error.response?.status;
		if (status === 401 && cfg && !cfg._retried && authStore.state.refreshToken) {
			cfg._retried = true;
			const ok = await authStore.refresh();
			if (ok) {
				cfg.headers.set('Authorization', `Bearer ${authStore.getAccessToken()}`);
				return api.request(cfg);
			}
		}
		if (status === 401) {
			authStore.clear();
			onUnauthorized?.();
		}
		return Promise.reject(error);
	},
);

// Authenticated Bearer header for the sidecar `fetch()` calls (filter-service, and any octree
// requests that need auth). Kept here so there is one source of truth for the auth header.
export function authHeaders(): Record<string, string> {
	const tok = authStore.getAccessToken();
	return tok ? { Authorization: `Bearer ${tok}` } : {};
}
