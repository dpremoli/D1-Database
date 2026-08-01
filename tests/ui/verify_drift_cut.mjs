// Drift-comp + detect-cut toggles, and live cut-start detection: the FRM defers until the cut is
// detected, then the "Cut" readout shows the time and the spiral builds.
//   FORCE_APP_EMAIL=… FORCE_APP_PASSWORD=… node tests/ui/verify_drift_cut.mjs
import { chromium } from '@playwright/test';

const BASE = process.env.FORCE_APP_BASE_URL || 'http://localhost:5180';
const EMAIL = process.env.FORCE_APP_EMAIL || 'admin@example.com';
const PASS = process.env.FORCE_APP_PASSWORD || '';
const ptsOf = async (loc) => parseInt((await loc.innerText().catch(() => '0')).replace(/\D/g, '') || '0', 10);

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

	// processing toggles present
	const toggles = await p.locator('.proc .chk').count();
	const detectCut = await p.locator('.proc .chk', { hasText: 'Detect cut start' }).count();
	const driftComp = await p.locator('.proc .chk', { hasText: 'Drift compensation' }).count();
	console.log('processing toggles:', toggles, '| detect-cut:', detectCut === 1, '| drift-comp:', driftComp === 1);
	ok = ok && toggles === 2 && detectCut === 1 && driftComp === 1;

	// detect-cut is on by default; run a sim cut (air-cut -> ramp -> cut)
	await p.locator('label', { hasText: 'Duration' }).locator('input').fill('5');
	await p.locator('label', { hasText: 'Sample rate' }).locator('input').fill('6000');
	await p.locator('.btn.start').click();

	// wait for the cut to be detected -> "Cut" readout turns green with a time, FRM starts
	await p.locator('.ro b.cut').waitFor({ timeout: 10000 }).catch(() => {});
	await p.waitForTimeout(1500);
	const cutDetected = await p.locator('.ro b.cut').count();
	const cutText = cutDetected ? await p.locator('.ro b.cut').innerText() : '—';
	const frmPts = await ptsOf(p.locator('.pts').first());
	console.log('cut detected:', cutDetected === 1, '| cut time:', cutText, '| FRM pts after cut:', frmPts);
	await p.screenshot({ path: 'tests/ui/drift_cut.png', fullPage: true });
	ok = ok && cutDetected === 1 && /\d/.test(cutText) && frmPts > 0;

	if (errs.length) console.log('page console errors:', JSON.stringify(errs.slice(0, 8), null, 2));
	await b.close();
	console.log(ok ? 'PASS' : 'FAIL');
	process.exit(ok ? 0 : 1);
})();
