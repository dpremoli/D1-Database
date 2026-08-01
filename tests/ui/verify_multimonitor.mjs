// Multi-monitor: ONE recording session, live views split across windows. The recorder broadcasts
// each frame to every connected client, so a detached /live/frm window renders the same session
// started from the main Record window.
//   FORCE_APP_EMAIL=… FORCE_APP_PASSWORD=… node tests/ui/verify_multimonitor.mjs
import { chromium } from '@playwright/test';

const BASE = process.env.FORCE_APP_BASE_URL || 'http://localhost:5180';
const EMAIL = process.env.FORCE_APP_EMAIL || 'admin@example.com';
const PASS = process.env.FORCE_APP_PASSWORD || '';
const ptsOf = async (loc) => parseInt((await loc.innerText().catch(() => '0')).replace(/\D/g, '') || '0', 10);

(async () => {
	const b = await chromium.launch();
	const c = await b.newContext({ ignoreHTTPSErrors: true, viewport: { width: 1500, height: 950 } });
	const A = await c.newPage(); // "monitor 1" — the Record workspace
	const errs = [];
	A.on('console', (m) => { if (m.type() === 'error') errs.push('A:' + m.text()); });
	let ok = true;

	await A.goto(BASE, { waitUntil: 'networkidle' });
	await A.fill('input[type="email"]', EMAIL);
	await A.fill('input[type="password"]', PASS);
	await A.click('button[type="submit"]');
	await A.waitForTimeout(2500);

	// "monitor 2" — a detached live FRM window in the SAME context (shares the login), opened BEFORE start
	const Bpage = await c.newPage();
	Bpage.on('console', (m) => { if (m.type() === 'error') errs.push('B:' + m.text()); });
	await Bpage.goto(`${BASE}/live/frm`, { waitUntil: 'networkidle' });
	await Bpage.waitForTimeout(1200);
	const liveWindow = await Bpage.locator('.live-window').count();
	const bConnected = await Bpage.locator('.conn.ok').count();
	console.log('detached window rendered:', liveWindow === 1, '| connected:', bConnected === 1);
	ok = ok && liveWindow === 1 && bConnected === 1;

	// Start the recording from window A
	await A.locator('label', { hasText: 'Duration' }).locator('input').fill('5');
	await A.locator('label', { hasText: 'Sample rate' }).locator('input').fill('6000');
	await A.locator('.btn.start').click();
	await A.waitForTimeout(2500);

	// Both windows show live points from the SAME session
	const aPts = await ptsOf(A.locator('.pts').first());
	const bPts = await ptsOf(Bpage.locator('.pts').first());
	const bRecording = await Bpage.locator('.state.recording').count();
	console.log('window A FRM pts:', aPts, '| detached window B FRM pts:', bPts, '| B shows recording:', bRecording === 1);
	await Bpage.screenshot({ path: 'tests/ui/multimonitor_frm.png', fullPage: true });
	ok = ok && aPts > 0 && bPts > 0 && bRecording === 1;

	if (errs.length) console.log('page console errors:', JSON.stringify(errs.slice(0, 8), null, 2));
	await b.close();
	console.log(ok ? 'PASS' : 'FAIL');
	process.exit(ok ? 0 : 1);
})();
