import { test, expect } from '../fixtures';

/**
 * The d1-force-crawler admin module: a home-styled control panel for the
 * host-side force-crawler daemon (scripts/force_orchestrator.py --daemon).
 * Directus itself cannot spawn the daemon (it runs in a container with no
 * archive/MATLAB access), so this only verifies the module reads/writes the
 * force_crawler_state singleton + machining_force_analysis queue correctly.
 */
test('force crawler: renders status, queue stats, settings, and activity', async ({ page }) => {
	await page.goto('/admin/d1-force-crawler', { waitUntil: 'domcontentloaded' });

	await expect(page.locator('.hero h1')).toHaveText(/Force Crawler/i, { timeout: 30_000 });

	// Status card always renders (online or offline).
	await expect(page.locator('.status-card')).toBeVisible({ timeout: 20_000 });
	await expect(page.locator('.status-label')).toBeVisible();

	// Five queue-stat tiles (pending/processing/done/error/skipped).
	await expect(page.locator('.stats .stat')).toHaveCount(5);

	// Settings form is present and editable.
	const workers = page.locator('.form label', { hasText: 'Workers' }).locator('input');
	await expect(workers).toBeVisible();
	const original = await workers.inputValue();
	await workers.fill('3');
	await expect(page.locator('.savebtn')).toBeEnabled();
	// Restore, so this test doesn't mutate the live daemon's worker count.
	await workers.fill(original || '2');

	// Activity feed renders (or shows the empty state) without erroring.
	const activityCard = page.locator('.activity-card');
	await expect(activityCard).toBeVisible();
});
