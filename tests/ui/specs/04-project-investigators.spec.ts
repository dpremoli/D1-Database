import { test, expect } from '../fixtures';
import { gotoCreateForm, fieldByLabel, isFieldVisible } from '../helpers';

/**
 * Projects: a "Secondary Investigators" M2M field exists, preceded by a notice
 * telling the user those people get viewing access to everything connected to
 * the project.
 */
test.describe('Project — secondary investigators', () => {
	test('Secondary Investigators field and access notice are present', async ({ page }, testInfo) => {
		await gotoCreateForm(page, 'projects');

		expect(await isFieldVisible(page, 'Secondary Investigators')).toBeTruthy();

		await testInfo.attach('project-form', {
			body: await page.screenshot({ fullPage: true }),
			contentType: 'image/png',
		});

		// The presentation notice text should be on the form.
		await expect(page.getByText(/viewing access to all/i)).toBeVisible();
	});
});
