import { defineConfig } from '@playwright/test';

// Drives the real vite dev server directly (not the Electron shell — see
// apps/force-app/desktop/playwright.config.ts for that). Requires `npm run dev` already running
// on the port vite.config.ts fixes (5180 — Directus's CORS_ORIGIN is only configured for that
// origin, so a different port fails every cross-origin request) and a real local Directus up at
// http://localhost (the dev .env points there), since these tests log in for real rather than
// stubbing the backend.
export default defineConfig({
	testDir: '.',
	timeout: 30_000,
	retries: 0,
	workers: 1,
	reporter: 'list',
	use: {
		baseURL: 'http://localhost:5180',
	},
});
