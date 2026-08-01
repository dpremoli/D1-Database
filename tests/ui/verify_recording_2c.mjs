// 2c LabAmp control (verified against the backend's MockLabAmp, no hardware). Opens the Lab
// Amplifier panel, asserts connected + sensor table, and round-trips the MEASURE/RESET mode.
//   FORCE_APP_EMAIL=… FORCE_APP_PASSWORD=… node tests/ui/verify_recording_2c.mjs
import { chromium } from '@playwright/test';

const BASE = process.env.FORCE_APP_BASE_URL || 'http://localhost:5180';
const EMAIL = process.env.FORCE_APP_EMAIL || 'admin@example.com';
const PASS = process.env.FORCE_APP_PASSWORD || '';

(async () => {
	const b = await chromium.launch();
	const c = await b.newContext({ ignoreHTTPSErrors: true, viewport: { width: 1720, height: 1040 } });
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

	const connected = await p.locator('.labamp-page .conn.ok').count();
	const mock = await p.locator('.labamp-page .mock').count();
	const rows = await p.locator('.labamp-page table tbody tr').count();
	console.log('labamp page connected:', connected === 1, '| mock:', mock === 1, '| sensor rows:', rows);
	ok = ok && connected === 1 && mock === 1 && rows === 8;

	// mode round-trip
	await p.locator('.labamp-page .seg.big button', { hasText: 'MEASURE' }).click();
	await p.waitForTimeout(500);
	const measureOn = await p.locator('.labamp-page .seg.big button.on', { hasText: 'MEASURE' }).count();
	await p.locator('.labamp-page .seg.big button', { hasText: 'RESET' }).click();
	await p.waitForTimeout(500);
	const resetOn = await p.locator('.labamp-page .seg.big button.on', { hasText: 'RESET' }).count();
	console.log('MEASURE set:', measureOn === 1, '| RESET set:', resetOn === 1);
	ok = ok && measureOn === 1 && resetOn === 1;
	await p.screenshot({ path: 'tests/ui/recording_2c_labamp.png', fullPage: true });

	if (errs.length) console.log('page console errors:', JSON.stringify(errs.slice(0, 8), null, 2));
	await b.close();
	console.log(ok ? 'PASS' : 'FAIL');
	process.exit(ok ? 0 : 1);
})();
