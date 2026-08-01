import { test, expect } from '../fixtures';
import { gotoCreateForm, selectDropdown, fillInput, fieldByLabel } from '../helpers';

/**
 * Physical Samples: the custom "Shape Preview" interface (d1-geometry-preview)
 * renders a live SVG sketch from the Geometry + dimension fields as the form is
 * filled in.
 */
test.describe('Sample — live geometry preview', () => {
	test('cylindrical geometry + dimensions render an SVG sketch', async ({ page }, testInfo) => {
		await gotoCreateForm(page, 'physical_samples');

		// Geometry/dimension fields are gated on item_type = sample (Part F conditions).
		await selectDropdown(page, 'Item Type', 'Sample');
		await selectDropdown(page, 'Geometry', 'Cylindrical');
		await fillInput(page, 'Ø (mm)', '25');
		await fillInput(page, 'z / Length (mm)', '80');
		await page.waitForTimeout(800);

		const preview = fieldByLabel(page, 'Shape Preview');
		await testInfo.attach('geometry-preview', {
			body: await page.screenshot({ fullPage: true }),
			contentType: 'image/png',
		});

		// The custom interface should have drawn an <svg>.
		await expect(preview.locator('svg')).toBeVisible();
		// And the dimension summary strip should echo the entered values.
		await expect(preview).toContainText('25');
		await expect(preview).toContainText('80');
	});
});
