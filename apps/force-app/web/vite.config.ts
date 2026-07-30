import { fileURLToPath, URL } from 'node:url';
import { defineConfig } from 'vite';
import vue from '@vitejs/plugin-vue';

// The extracted plotting components (ForceDashboard.vue, FrmCloud.vue) import auth helpers
// from '@directus/extensions-sdk'. Rather than editing those large files, we alias that
// specifier to a local shim (src/shims/directus-sdk.ts) that provides drop-in useApi()/
// useStores() backed by our own axios client + auth store. This keeps the ported components
// byte-for-byte identical to the Directus module, so future upstream fixes port cleanly.
export default defineConfig({
	plugins: [vue()],
	resolve: {
		alias: {
			'@directus/extensions-sdk': fileURLToPath(new URL('./src/shims/directus-sdk.ts', import.meta.url)),
			'@': fileURLToPath(new URL('./src', import.meta.url)),
		},
	},
	server: { port: 5180 },
});
