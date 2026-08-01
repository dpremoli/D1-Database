import { test, expect } from '../fixtures';

/**
 * "Ask the Database" chat module (Path B).
 *
 * The UI test stubs the /d1-ask/chat proxy response with `page.route` so the
 * assertions are deterministic — it verifies the page contract (SQL block,
 * result table, rendered chart), not the (nondeterministic) local LLM. Two
 * API-level checks assert the endpoint's auth boundary directly, the same way
 * spec 05 uses `page.request`.
 *
 * A live end-to-end smoke through the real Ollama + plugin runs only when
 * D1_LLM_LIVE=1, so CI stays deterministic.
 */

const STUBBED = {
	sql: 'SELECT material, sample_count FROM v_complete_sample_history',
	columns: ['material', 'sample_count'],
	rows: [
		{ material: 'Aluminium', sample_count: 12 },
		{ material: 'Titanium', sample_count: 5 },
	],
	chart: {
		type: 'bar',
		x: 'material',
		y: ['sample_count'],
		title: 'Samples per material',
	},
};

test('chat page renders SQL, table and chart (stubbed proxy)', async ({ page }) => {
	await page.route('**/d1-ask/chat', (route) =>
		route.fulfill({ status: 200, json: STUBBED }),
	);

	await page.goto('/admin/ask-db', { waitUntil: 'domcontentloaded' });

	const input = page.locator('[data-test="ask-input"]');
	await expect(input).toBeVisible({ timeout: 30_000 });
	await input.fill('how many samples per material?');
	await page.locator('[data-test="ask-submit"]').click();

	// SQL is shown (transparency), the table renders the stubbed rows, and the
	// chart panel draws a Plotly SVG.
	await expect(page.locator('[data-test="ask-sql"]')).toContainText(/select/i);
	const table = page.locator('[data-test="ask-table"]');
	await expect(table).toContainText('Aluminium');
	await expect(table).toContainText('12');
	// Plotly renders several nested <svg> layers; assert at least the main one drew.
	await expect(page.locator('[data-test="ask-chart"] svg').first()).toBeVisible({
		timeout: 15_000,
	});

	await page.screenshot({ path: 'artifacts/ask-db-chat.png', fullPage: true });
});

test('proxy endpoint rejects unauthenticated requests', async ({ request }) => {
	// The `request` fixture carries no Directus session — the endpoint must 401
	// before doing any LLM/DB work.
	const resp = await request.post('/d1-ask/chat', {
		data: { messages: [{ role: 'user', content: 'anything' }] },
	});
	expect(resp.status()).toBe(401);
});

test('proxy endpoint passes the auth gate for a logged-in session', async ({ page }) => {
	// Uses the page's authenticated session (cookie), like spec 05. We only
	// assert the auth gate passed and the route exists — the downstream may be
	// 200 (plugin up), 422 (guard rejected), or 502 (plugin down), but never 401
	// (unauthorised) or 404 (endpoint missing / not loaded).
	const resp = await page.request.post('/d1-ask/chat', {
		data: { messages: [{ role: 'user', content: 'how many samples are there?' }] },
	});
	expect([200, 422, 502]).toContain(resp.status());
});

test('live end-to-end through Ollama + plugin', async ({ page }) => {
	test.skip(process.env.D1_LLM_LIVE !== '1', 'set D1_LLM_LIVE=1 to run the live smoke');

	await page.goto('/admin/ask-db', { waitUntil: 'domcontentloaded' });
	await page.locator('[data-test="ask-input"]').fill('how many physical samples are there?');
	await page.locator('[data-test="ask-submit"]').click();

	// A real answer arrives as either a table with rows or a safe-rejection note;
	// allow generous time for a cold local model.
	await expect(page.locator('[data-test="ask-table"], .answer.error')).toBeVisible({
		timeout: 120_000,
	});
});
