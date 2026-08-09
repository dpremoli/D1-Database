import { fileURLToPath, URL } from 'node:url';
import { defineConfig } from 'vite';
import vue from '@vitejs/plugin-vue';

// Served at a sub-path (/app/) behind Caddy in production so it shares the Directus origin over
// Tailscale; at root ('/') in dev. `base` flows into import.meta.env.BASE_URL, which the router uses.
export default defineConfig(({ mode }) => ({
	base: mode === 'production' ? '/app/' : '/',
	plugins: [vue()],
	resolve: {
		alias: {
			'@': fileURLToPath(new URL('./src', import.meta.url)),
		},
	},
	server: { port: 5180 },
}));
