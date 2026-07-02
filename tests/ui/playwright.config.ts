import { defineConfig, devices } from '@playwright/test';

/**
 * Playwright config for D1-Database Directus UI tests.
 *
 * Targets the local Directus instance. Override the base URL / credentials
 * with env vars when pointing at another environment:
 *   D1_BASE_URL, D1_ADMIN_EMAIL, D1_ADMIN_PASSWORD
 */
export default defineConfig({
	testDir: './specs',
	fullyParallel: false,
	workers: 1,
	retries: 1,
	timeout: 60_000,
	expect: { timeout: 15_000 },
	reporter: [['list'], ['html', { open: 'never', outputFolder: 'report' }]],
	use: {
		baseURL: process.env.D1_BASE_URL || 'http://localhost:8055',
		trace: 'retain-on-failure',
		screenshot: 'only-on-failure',
		video: 'retain-on-failure',
	},
	projects: [
		{
			name: 'chromium',
			use: {
				...devices['Desktop Chrome'],
			},
		},
	],
});
