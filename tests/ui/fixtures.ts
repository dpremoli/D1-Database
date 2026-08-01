import { test as base } from '@playwright/test';
import { login } from './helpers';

/**
 * Base test with a logged-in page. Each test logs in fresh so every browser
 * context owns its own (non-shared, non-rotated) Directus session.
 */
export const test = base.extend({
	page: async ({ page }, use) => {
		await login(page);
		await use(page);
	},
});

export { expect } from '@playwright/test';
