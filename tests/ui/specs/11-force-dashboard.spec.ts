import { test, expect } from '../fixtures';

/**
 * The d1-force-dashboard module: a home-styled force-analysis explorer.
 * Layout: Samples (top-left) + Operations (bottom-left), bidirectionally linked;
 * selected sample info + operation info on the right; three stacked signal charts
 * with a Force/FFT toggle beside the per-axis (Fx/Fy/Fz) FRM fingerprint.
 *
 * Requires at least one processed machining_force_analysis row (status='done').
 * Populate with: scripts/force_orchestrator.py --discover --run.
 */
test('force dashboard: drill sample → operation → charts + FRM, with toggles', async ({ page }, testInfo) => {
	await page.goto('/admin/d1-force-dashboard', { waitUntil: 'domcontentloaded' });

	// Hero renders.
	await expect(page.locator('.hero h1')).toHaveText(/Force Analysis/i, { timeout: 30_000 });

	// Samples + Operations panels populated.
	const samples = page.locator('.panel-samples .rowcard');
	const ops = page.locator('.panel-ops .rowcard');
	await expect(samples.first()).toBeVisible({ timeout: 20_000 });
	await expect(ops.first()).toBeVisible();

	const sampleCount = await samples.count();
	const opsBefore = await ops.count();
	expect(sampleCount).toBeGreaterThan(0);
	expect(opsBefore).toBeGreaterThan(0);

	// Selecting a sample marks it active and filters the operations list to it.
	await samples.first().click();
	await expect(samples.first()).toHaveClass(/active/);
	await page.waitForTimeout(400);
	expect(await ops.count()).toBeLessThanOrEqual(opsBefore);

	// Selecting an operation loads its detail (stat tiles) + charts + FRM.
	await ops.first().click();
	await expect(page.locator('.panel-ops .rowcard.active')).toBeVisible();

	// Operation info tiles.
	await expect(page.locator('.card.info .stat').first()).toBeVisible({ timeout: 20_000 });
	expect(await page.locator('.card.info .stat').count()).toBeGreaterThanOrEqual(6);

	// Three stacked signal charts (Force mode by default) each render an SVG.
	const charts = page.locator('.charts-col .chart svg');
	await expect(charts).toHaveCount(3, { timeout: 20_000 });

	// FRM fingerprint image loads (blob URL, natural size > 0).
	const frm = page.locator('.frm-img img');
	await expect(frm).toBeVisible({ timeout: 20_000 });
	await expect.poll(async () => frm.evaluate((el: HTMLImageElement) => el.naturalWidth), { timeout: 20_000 })
		.toBeGreaterThan(0);
	const fxSrc = await frm.getAttribute('src');

	// Toggle Force → FFT: charts re-render (still three SVGs), FFT button active.
	await page.getByRole('button', { name: 'FFT', exact: true }).click();
	await page.waitForTimeout(400);
	await expect(page.locator('.graphs-head .tbtn', { hasText: 'FFT' })).toHaveClass(/on/);
	await expect(charts).toHaveCount(3);

	// Toggle FRM axis Fz → Fx: image reloads (different blob src).
	await page.locator('.frm-col .toggle .tbtn', { hasText: 'Fx' }).click();
	await expect.poll(async () => frm.getAttribute('src'), { timeout: 20_000 }).not.toBe(fxSrc);
	await expect.poll(async () => frm.evaluate((el: HTMLImageElement) => el.naturalWidth), { timeout: 20_000 })
		.toBeGreaterThan(0);

	await testInfo.attach('force-dashboard', {
		body: await page.screenshot({ fullPage: true }),
		contentType: 'image/png',
	});
});

test('force dashboard: selecting an operation highlights its sample without filtering the operations list', async ({ page }) => {
	await page.goto('/admin/d1-force-dashboard', { waitUntil: 'domcontentloaded' });

	const samples = page.locator('.panel-samples .rowcard');
	const ops = page.locator('.panel-ops .rowcard');
	await expect(ops.first()).toBeVisible({ timeout: 20_000 });

	const opsBefore = await ops.count();
	test.skip(opsBefore < 2, 'need at least 2 unfiltered operations to prove nothing gets hidden');

	// No sample filter active yet: nothing in the samples list is highlighted.
	await expect(page.locator('.panel-samples .rowcard.active')).toHaveCount(0);

	// Click an operation directly (without ever clicking a sample first).
	await ops.first().click();
	await expect(page.locator('.panel-ops .rowcard.active')).toBeVisible();

	// The operations list must be UNCHANGED — selecting an op is not a filter.
	expect(await ops.count()).toBe(opsBefore);

	// Exactly one sample is now highlighted (the selected op's parent sample),
	// but the "show all" clear button must NOT appear — there is no active filter.
	await expect(page.locator('.panel-samples .rowcard.active')).toHaveCount(1);
	await expect(page.locator('.panel-ops .clearbtn')).toHaveCount(0);

	// Explicitly clicking a sample DOES activate filtering (the clear button appears).
	await samples.first().click();
	await expect(page.locator('.panel-ops .clearbtn')).toBeVisible();
});
