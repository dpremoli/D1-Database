import { fileURLToPath, URL } from 'node:url';
import { defineConfig } from 'vite';
import { configDefaults } from 'vitest/config';
import vue from '@vitejs/plugin-vue';

// Served at a sub-path (/app/) behind Caddy in production so it shares the Directus origin over
// Tailscale; at root ('/') in dev. `base` flows into import.meta.env.BASE_URL, which the router uses.
//
// The `desktop` mode builds the SAME sources for the Electron shell, which serves them from the
// root of a custom protocol (app://force/). A '/app/' base there would emit asset URLs that
// resolve to app://force/app/assets/... — nothing exists at that path, the protocol handler's SPA
// history fallback returns index.html as text/html, and the module script is rejected (blank
// window). Desktop therefore builds with base '/' into a separate outDir (dist-desktop) so the
// two variants coexist without clobbering each other. See package.json's build:desktop script.
export default defineConfig(({ mode }) => ({
	base: mode === 'desktop' ? '/' : mode === 'production' ? '/app/' : '/',
	plugins: [vue()],
	resolve: {
		alias: {
			'@': fileURLToPath(new URL('./src', import.meta.url)),
		},
	},
	server: { port: 5180 },
	// vitest's default include glob (**/*.{test,spec}.*) otherwise also picks up e2e/*.spec.ts —
	// those are @playwright/test files (a real Directus login, a real browser), not vitest's.
	test: { exclude: [...configDefaults.exclude, 'e2e/**'] },
}));
