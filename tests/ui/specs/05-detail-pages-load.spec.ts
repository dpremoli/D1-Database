import { test, expect } from '../fixtures';

/**
 * Regression: opening an EXISTING record's detail page must not 500.
 *
 * A presentation/alias field (geometry_preview, investigator notice) registered
 * without `no-data` in its `special` makes Directus try to SELECT a non-existent
 * column → 500 → "Page Not Found" on every record. The create-form specs miss
 * this because new items aren't fetched from the DB. This spec loads a real row
 * for each collection and asserts the form renders.
 */
const COLLECTIONS = [
	'physical_samples',
	'projects',
	'manufacturing_operations',
	'test_sessions',
];

for (const collection of COLLECTIONS) {
	test(`${collection}: an existing record opens without error`, async ({ page }) => {
		// Find the first record's primary key via the API (uses the page's session).
		const base = process.env.D1_BASE_URL || 'http://localhost:8055';
		const resp = await page.request.get(`${base}/items/${collection}?limit=1`);
		expect(resp.ok(), `list ${collection} should be 200`).toBeTruthy();
		const body = await resp.json();
		const row = body.data?.[0];
		test.skip(!row, `no rows in ${collection} to open`);

		const pk = Object.values(row)[0] as string; // first field is the PK
		await page.goto(`/admin/content/${collection}/${pk}`, { waitUntil: 'domcontentloaded' });

		// A field form must render, and the "Page Not Found" / error state must not.
		await expect(page.locator('.field').first()).toBeVisible({ timeout: 30_000 });
		await expect(page.getByText(/Page Not Found/i)).toHaveCount(0);
	});
}
