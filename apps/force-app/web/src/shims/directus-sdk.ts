// Drop-in replacement for the small slice of '@directus/extensions-sdk' the ported plotting
// components use: useApi() and useStores().useUserStore(). Vite aliases the SDK specifier to
// this file (see vite.config.ts), so ForceDashboard.vue / FrmCloud.vue import it unchanged.
import { api } from '../directusClient';
import { authStore } from '../authStore';

// The Directus module called `useApi()` to get its authenticated axios instance. We return our
// own Bearer-authenticated client, which exposes the same axios .get/.post/.patch/.delete surface.
export function useApi() {
	return api;
}

// The module used `useStores().useUserStore().currentUser` for role/ownership scoping. Mirror
// just that shape. `currentUser` is a computed ref; components read `.currentUser` (auto-unwrapped
// in templates, and here in setup we expose the unwrapped value via a getter so `.currentUser`
// works identically to the Directus store).
export function useStores() {
	return {
		useUserStore() {
			return {
				get currentUser() {
					return authStore.currentUser.value;
				},
			};
		},
	};
}

// defineModule is only referenced by the original index.ts, which we do not port. Provide a
// no-op so any stray import resolves rather than crashing the bundle.
export function defineModule<T>(config: T): T {
	return config;
}
