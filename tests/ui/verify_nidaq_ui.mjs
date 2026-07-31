// 2b prep UI: the NI-DAQ source option (channels + hardware note) and the multi-monitor pop-out
// buttons. Starting NI-DAQ here surfaces the backend's "no device" error gracefully.
//   FORCE_APP_EMAIL=… FORCE_APP_PASSWORD=… node tests/ui/verify_nidaq_ui.mjs
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

	// multi-monitor pop-out buttons (one per sidebar section)
	const popouts = await p.locator('.sidebar .popout').count();
	console.log('sidebar pop-out buttons:', popouts);
	ok = ok && popouts === 4;

	// NI-DAQ source
	await p.locator('.seg button', { hasText: 'NI-DAQ' }).click();
	await p.waitForTimeout(400);
	const channels = await p.locator('.opts textarea').count();
	const chanText = channels ? await p.locator('.opts textarea').inputValue() : '';
	const note = await p.locator('.hint.warn').count();
	console.log('NI-DAQ channels field:', channels === 1, '| lines:', chanText.split('\n').filter(Boolean).length, '| hardware note:', note === 1);
	ok = ok && channels === 1 && chanText.split('\n').filter(Boolean).length === 9 && note === 1;

	// Start NI-DAQ -> backend has no device here -> state goes to error, surfaced in the panel
	await p.locator('.btn.start').click();
	await p.waitForTimeout(4000);
	const errShown = await p.locator('.opts .err').count();
	const stateErr = await p.locator('.ro b.error').count();
	console.log('error surfaced (panel/state):', errShown >= 1, stateErr >= 1);
	await p.screenshot({ path: 'tests/ui/nidaq_ui.png', fullPage: true });
	ok = ok && errShown >= 1;

	if (errs.length) console.log('page console errors:', JSON.stringify(errs.slice(0, 8), null, 2));
	await b.close();
	console.log(ok ? 'PASS' : 'FAIL');
	process.exit(ok ? 0 : 1);
})();
