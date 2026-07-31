// Modular Recording workspace + real-file replay. Verifies the 5 draggable panels render, then
// replays a REAL 10-AA-MF cut (fetched from Directus) through the live pipeline at high speed and
// confirms the live spiral/FFT stream and the captured fingerprint renders.
//   FORCE_APP_EMAIL=… FORCE_APP_PASSWORD=… node tests/ui/verify_recording_workspace.mjs
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
	await p.locator('.sidebar .navitem', { hasText: 'Record' }).click();
	await p.waitForTimeout(1500);

	// 5 modular panels
	const panels = await p.locator('.panel-frame').count();
	const titles = await p.locator('.panel-title').allInnerTexts();
	console.log('panels:', panels, '| titles:', JSON.stringify(titles));
	ok = ok && panels === 5;

	// switch to Replay, search for a real cut, pick the first, set a high speed
	await p.locator('.seg button', { hasText: 'Replay real file' }).click();
	await p.locator('label', { hasText: 'Find a cut' }).locator('input').fill('10-AA-MF');
	await p.waitForTimeout(1500);
	const cuts = await p.locator('.cut').count();
	console.log('replay cut matches:', cuts);
	await p.locator('.cut').first().click();
	await p.locator('label', { hasText: 'Replay speed' }).locator('input').fill('40');
	await p.locator('.btn.start').click();

	// live: FRM points grow, FFT tab shows a spectrum
	await p.waitForTimeout(2000);
	const pts1 = parseInt((await p.locator('.pts').first().innerText().catch(() => '0')).replace(/\D/g, '') || '0', 10);
	await p.locator('.force-panel .segbtn', { hasText: 'FFT' }).click();
	await p.waitForTimeout(1500);
	const fftCanvas = await p.locator('.live-fft canvas').count();
	const pts2 = parseInt((await p.locator('.pts').first().innerText().catch(() => '0')).replace(/\D/g, '') || '0', 10);
	console.log('FRM pts', pts1, '->', pts2, '| fft canvas:', fftCanvas);
	await p.screenshot({ path: 'tests/ui/recording_workspace_live.png', fullPage: true });

	// wait for the replay to finish and the captured fingerprint to render (FrmCloud 'captured' pane)
	await p.locator('.ro b.done').waitFor({ timeout: 40000 }).catch(() => {});
	await p.waitForTimeout(4000);
	const done = await p.locator('.ro b.done').count();
	const capturedPane = await p.locator('.fc-pane', { hasText: /captured/i }).count();
	const frmCanvas = await p.locator('.frm-panel canvas').count();
	console.log('state done:', done === 1, '| captured pane:', capturedPane, '| frm canvas:', frmCanvas);
	await p.screenshot({ path: 'tests/ui/recording_workspace_finished.png', fullPage: true });

	ok = ok && cuts > 0 && pts2 > pts1 && pts1 > 0 && fftCanvas >= 1 && done === 1 && capturedPane >= 1;
	if (errs.length) console.log('page console errors:', JSON.stringify(errs.slice(0, 8), null, 2));
	await b.close();
	console.log(ok ? 'PASS' : 'FAIL');
	process.exit(ok ? 0 : 1);
})();
