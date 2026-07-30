// Recording (sim source) in the modular workspace: configure a short simulated cut, START,
// confirm the live FRM streams and the captured fingerprint renders. Complements
// verify_recording_workspace.mjs (which covers the real-file replay path).
//   FORCE_APP_EMAIL=… FORCE_APP_PASSWORD=… node tests/ui/verify_recording_2a.mjs
import { chromium } from '@playwright/test';

const BASE = process.env.FORCE_APP_BASE_URL || 'http://localhost:5180';
const EMAIL = process.env.FORCE_APP_EMAIL || 'admin@example.com';
const PASS = process.env.FORCE_APP_PASSWORD || '';

async function setNum(p, labelText, value) {
	await p.locator('label', { hasText: labelText }).locator('input').fill(String(value));
}

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
	const connected = await p.locator('.conn.ok').count();
	console.log('panels:', panels, '| stream connected:', connected === 1);

	// Simulated source (default). Short, light run.
	await setNum(p, 'Duration', 3);
	await setNum(p, 'Sample rate', 8000);
	await setNum(p, 'Spindle', 1500);
	await p.locator('.btn.start').click();

	await p.waitForTimeout(1500);
	const pts1 = parseInt((await p.locator('.pts').first().innerText().catch(() => '0')).replace(/\D/g, '') || '0', 10);
	await p.waitForTimeout(1200);
	const pts2 = parseInt((await p.locator('.pts').first().innerText().catch(() => '0')).replace(/\D/g, '') || '0', 10);
	console.log('FRM pts', pts1, '->', pts2);
	await p.screenshot({ path: 'tests/ui/recording_live.png', fullPage: true });

	await p.locator('.ro b.done').waitFor({ timeout: 15000 }).catch(() => {});
	await p.waitForTimeout(3500);
	const done = await p.locator('.ro b.done').count();
	const captured = await p.locator('.fc-pane', { hasText: /captured/i }).count();
	console.log('state done:', done === 1, '| captured fingerprint:', captured >= 1);
	await p.screenshot({ path: 'tests/ui/recording_finished.png', fullPage: true });

	ok = panels === 5 && connected === 1 && pts1 > 0 && pts2 > pts1 && done === 1 && captured >= 1;
	if (errs.length) console.log('page console errors:', JSON.stringify(errs.slice(0, 8), null, 2));
	await b.close();
	console.log(ok ? 'PASS' : 'FAIL');
	process.exit(ok ? 0 : 1);
})();
