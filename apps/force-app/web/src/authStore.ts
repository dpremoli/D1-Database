// Auth store — reuses Directus authentication. The standalone app has no user database of
// its own; it POSTs credentials to Directus /auth/login, holds the returned access + refresh
// tokens, and attaches the access token as a Bearer on every API call (see directusClient.ts).
//
// This module deliberately uses a BARE axios instance (not directusClient) for the auth
// endpoints, so there is no import cycle and a refresh can never recurse through the 401
// interceptor that itself triggers the refresh.
import axios from 'axios';
import { reactive, computed } from 'vue';
import { getConfig } from './config';

export interface DirectusUser {
	id: string;
	role: string | { id: string; admin_access?: boolean } | null;
	admin_access?: boolean;
	first_name?: string | null;
	last_name?: string | null;
	email?: string | null;
}

interface AuthState {
	accessToken: string | null;
	refreshToken: string | null;
	// epoch ms when the access token expires (server `expires` is a duration in ms).
	expiresAt: number;
	user: DirectusUser | null;
}

const LS_KEY = 'force-app.auth';

function loadPersisted(): Partial<AuthState> {
	try {
		return JSON.parse(localStorage.getItem(LS_KEY) || '{}');
	} catch {
		return {};
	}
}

const persisted = loadPersisted();
const state = reactive<AuthState>({
	accessToken: persisted.accessToken ?? null,
	refreshToken: persisted.refreshToken ?? null,
	expiresAt: persisted.expiresAt ?? 0,
	user: persisted.user ?? null,
});

function persist() {
	// Persist the refresh token (survives reload) + last known user for a warm start. The
	// access token is short-lived; we keep it too so a quick reload doesn't force a refresh.
	localStorage.setItem(
		LS_KEY,
		JSON.stringify({
			accessToken: state.accessToken,
			refreshToken: state.refreshToken,
			expiresAt: state.expiresAt,
			user: state.user,
		}),
	);
}

// A bare client for the auth endpoints only — no interceptors, no Bearer, no refresh loop.
function authClient() {
	return axios.create({ baseURL: getConfig().directusUrl, headers: { 'Content-Type': 'application/json' } });
}

// Directus 11 moved admin_access/app_access from roles to POLICIES, so `role.admin_access`
// is not a real field — requesting it made Directus collapse the whole response to just {id}
// (dropping `role`), which broke admin detection. Fetch only valid fields: `role` (M2O id
// string, matched against the app's ADMIN_ROLE_IDS) plus the policy-derived admin flag.
const USER_FIELDS = ['id', 'first_name', 'last_name', 'email', 'role', 'policies.policy.admin_access'];

export const authStore = {
	state,
	isAuthenticated: computed(() => !!state.refreshToken || !!state.accessToken),
	currentUser: computed(() => state.user),

	getAccessToken(): string | null {
		return state.accessToken;
	},

	async login(email: string, password: string): Promise<void> {
		const res = await authClient().post('/auth/login', { email, password, mode: 'json' });
		const data = res.data?.data ?? {};
		state.accessToken = data.access_token ?? null;
		state.refreshToken = data.refresh_token ?? null;
		state.expiresAt = Date.now() + (Number(data.expires) || 0);
		persist();
		await this.fetchCurrentUser();
	},

	// Exchange the refresh token for a fresh access token. Returns false if it can't (caller
	// then routes to /login). Concurrent 401s share one in-flight refresh via `refreshing`.
	async refresh(): Promise<boolean> {
		if (!state.refreshToken) return false;
		if (refreshing) return refreshing;
		refreshing = (async () => {
			try {
				const res = await authClient().post('/auth/refresh', { refresh_token: state.refreshToken, mode: 'json' });
				const data = res.data?.data ?? {};
				state.accessToken = data.access_token ?? null;
				state.refreshToken = data.refresh_token ?? state.refreshToken;
				state.expiresAt = Date.now() + (Number(data.expires) || 0);
				persist();
				return !!state.accessToken;
			} catch {
				this.clear();
				return false;
			} finally {
				refreshing = null;
			}
		})();
		return refreshing;
	},

	async fetchCurrentUser(): Promise<void> {
		if (!state.accessToken) return;
		try {
			const res = await authClient().get('/users/me', {
				params: { fields: USER_FIELDS },
				headers: { Authorization: `Bearer ${state.accessToken}` },
			});
			const me = res.data?.data ?? {};
			// Flatten the policy admin flag to a top-level `admin_access` boolean, which is one of
			// the signals the ownership-scoping logic checks (alongside ADMIN_ROLE_IDS on `role`).
			const policies: any[] = Array.isArray(me.policies) ? me.policies : [];
			const admin_access = policies.some((p) => p?.policy?.admin_access === true);
			state.user = {
				id: me.id,
				role: me.role ?? null,
				admin_access,
				first_name: me.first_name ?? null,
				last_name: me.last_name ?? null,
				email: me.email ?? null,
			};
			persist();
		} catch {
			/* leave the warm-start user in place */
		}
	},

	async logout(): Promise<void> {
		const rt = state.refreshToken;
		this.clear();
		if (rt) {
			try {
				await authClient().post('/auth/logout', { refresh_token: rt, mode: 'json' });
			} catch {
				/* best effort */
			}
		}
	},

	clear(): void {
		state.accessToken = null;
		state.refreshToken = null;
		state.expiresAt = 0;
		state.user = null;
		localStorage.removeItem(LS_KEY);
	},
};

let refreshing: Promise<boolean> | null = null;
