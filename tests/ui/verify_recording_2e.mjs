// 2e safety alarms: set a low force threshold, run a sim cut whose peak exceeds it, confirm the
// alarm overlay trips + the panel shows it, then Acknowledge clears it. (Audio not asserted.)
//   FORCE_APP_EMAIL=… FORCE_APP_PASSWORD=… node tests/ui/verify_recording_2e.mjs
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
	await p.locator('.card', { hasText: 'Recording' }).click();
	await p.waitForTimeout(1200);

	const panels = await p.locator('.panel-frame').count();
	const alarmsPanel = await p.locator('.panel-frame', { hasText: 'Safety Alarms' }).count();
	console.log('panels:', panels, '| alarms panel present:', alarmsPanel === 1);
	ok = ok && alarmsPanel === 1;

	// set a low force threshold (sim peak Fz ~160 N will exceed 50)
	await p.locator('.alarms .thr input').first().fill('50');

	// short sim run
	await p.locator('label', { hasText: 'Duration' }).locator('input').fill('4');
	await p.locator('label', { hasText: 'Sample rate' }).locator('input').fill('6000');
	await p.locator('.btn.start').click();

	// alarm overlay should appear once the peak crosses 50 N
	await p.locator('.alarm-overlay').waitFor({ timeout: 10000 });
	const overlay = await p.locator('.alarm-overlay').count();
	const trippedPanel = await p.locator('.alarms .status.tripped').count();
	const items = await p.locator('.alarm-overlay .ao-item').count();
	console.log('alarm overlay:', overlay === 1, '| panel tripped:', trippedPanel === 1, '| alarm items:', items);
	await p.screenshot({ path: 'tests/ui/recording_2e_alarm.png', fullPage: true });
	ok = ok && overlay === 1 && trippedPanel === 1 && items >= 1;

	// acknowledge -> overlay clears
	await p.locator('.ao-ack').click();
	await p.waitForTimeout(600);
	const overlayAfter = await p.locator('.alarm-overlay').count();
	console.log('overlay after acknowledge:', overlayAfter === 0);
	ok = ok && overlayAfter === 0;

	if (errs.length) console.log('page console errors:', JSON.stringify(errs.slice(0, 8), null, 2));
	await b.close();
	console.log(ok ? 'PASS' : 'FAIL');
	process.exit(ok ? 0 : 1);
})();
