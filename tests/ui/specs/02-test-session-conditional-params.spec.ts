import { test, expect } from '../fixtures';
import { gotoCreateForm, selectDropdown, isFieldVisible } from '../helpers';

/**
 * Test Sessions: the typed test-parameter FIELDS appear inline when the matching
 * Test Type is selected (flattened onto test_sessions — migration 032).
 */
test.describe('Test Session — inline conditional parameter fields', () => {
	test('no test type → no typed param fields visible', async ({ page }) => {
		await gotoCreateForm(page, 'test_sessions');
		expect(await isFieldVisible(page, 'Hardness Scale')).toBeFalsy();
		expect(await isFieldVisible(page, 'Gauge Length')).toBeFalsy();
	});

	test('Tensile shows tensile fields inline only', async ({ page }, testInfo) => {
		await gotoCreateForm(page, 'test_sessions');
		await selectDropdown(page, 'Test Type', 'Tensile');
		await page.waitForTimeout(700);

		await testInfo.attach('after-tensile', {
			body: await page.screenshot({ fullPage: true }),
			contentType: 'image/png',
		});

		expect(await isFieldVisible(page, 'Gauge Length')).toBeTruthy();
		expect(await isFieldVisible(page, 'UTS')).toBeTruthy();
		expect(await isFieldVisible(page, 'Hardness Scale')).toBeFalsy();
	});

	test('Hardness shows hardness fields inline only', async ({ page }) => {
		await gotoCreateForm(page, 'test_sessions');
		await selectDropdown(page, 'Test Type', 'Hardness');
		await page.waitForTimeout(700);

		expect(await isFieldVisible(page, 'Hardness Scale')).toBeTruthy();
		expect(await isFieldVisible(page, 'Test Load')).toBeTruthy();
		expect(await isFieldVisible(page, 'Gauge Length')).toBeFalsy();
	});
});
