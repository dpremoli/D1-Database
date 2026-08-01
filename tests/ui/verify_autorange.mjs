// LabAmp auto-range on the Lab Amp page (mock): measure -> recommend (smaller ranges than the
// over-ranged default) -> apply -> channels report OK and the sensor table updates.
//   FORCE_APP_EMAIL=… FORCE_APP_PASSWORD=… node tests/ui/verify_autorange.mjs
import { chromium } from '@playwright/test';

const BASE = process.env.FORCE_APP_BASE_URL || 'http://localhost:5180';
const EMAIL = process.env.FORCE_APP_EMAIL || 'admin@example.com';
const PASS = process.env.FORCE_APP_PASSWORD || '';

(async () => {
	const b = await chromium.launch();
	const c = await b.newContext({ ignoreHTTPSErrors: true, viewport: { width: 1720, height: 1100 } });
	const p = await c.newPage();
	const errs = [];
	p.on('console', (m) => { if (m.type() === 'error') errs.push(m.text()); });
	let ok = true;

	await p.goto(BASE, { waitUntil: 'networkidle' });
	await p.fill('input[type="email"]', EMAIL);
	await p.fill('input[type="password"]', PASS);
	await p.click('button[type="submit"]');
	await p.waitForTimeout(2500);
	await p.locator('.sidebar .navitem', { hasText: 'Lab Amp' }).click();
	await p.waitForTimeout(1500);

	const card = p.locator('section.card', { hasText: 'Auto-range' });
	console.log('auto-range card:', await card.count() === 1);
	ok = ok && (await card.count()) === 1;

	await card.locator('button', { hasText: 'Measure' }).click();
	await p.waitForTimeout(1000);
	const recRows = await card.locator('tbody tr').count();
	const firstRec = parseInt((await card.locator('tbody tr').first().locator('td').nth(3).innerText()).replace(/\D/g, '') || '0', 10);
	console.log('recommendation rows:', recRows, '| ch1 recommended range:', firstRec);
	ok = ok && recRows === 8 && firstRec > 0 && firstRec < 1000;   // shrunk from 10000

	await card.locator('button', { hasText: 'Apply recommended' }).click();
	await p.waitForTimeout(1200);
	const okTags = await card.locator('.tag.ok').count();
	// sensor table (Channels card) now shows the smaller ranges
	const chCard = p.locator('section.card', { hasText: 'Channels' });
	const firstRange = parseInt((await chCard.locator('tbody tr').first().locator('td').last().innerText()).replace(/\D/g, '') || '0', 10);
	console.log('OK tags after apply:', okTags, '| sensor-table ch1 range:', firstRange);
	await p.screenshot({ path: 'tests/ui/autorange.png', fullPage: true });
	ok = ok && okTags === 8 && firstRange > 0 && firstRange < 1000;

	if (errs.length) console.log('page console errors:', JSON.stringify(errs.slice(0, 8), null, 2));
	await b.close();
	console.log(ok ? 'PASS' : 'FAIL');
	process.exit(ok ? 0 : 1);
})();
