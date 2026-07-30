// End-to-end for recording slice 2a: log in → Recording → configure a short sim run → START →
// live frames stream (FRM point count grows, elapsed advances) → run completes → finished cut
// renders via FrmCloud. Requires the recorder backend (:8200) + web dev server + live Directus.
//   FORCE_APP_EMAIL=… FORCE_APP_PASSWORD=… node tests/ui/verify_recording_2a.mjs
import { chromium } from '@playwright/test';

const BASE = process.env.FORCE_APP_BASE_URL || 'http://localhost:5180';
const EMAIL = process.env.FORCE_APP_EMAIL || process.env.DIRECTUS_ADMIN_EMAIL || 'admin@example.com';
const PASS = process.env.FORCE_APP_PASSWORD || process.env.DIRECTUS_ADMIN_PASSWORD || '';

async function setNum(p, labelText, value) {
	const inp = p.locator('label', { hasText: labelText }).locator('input');
	await inp.fill(String(value));
}

(async () => {
	const b = await chromium.launch();
	const c = await b.newContext({ ignoreHTTPSErrors: true, viewport: { width: 1600, height: 1000 } });
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
	const onRecord = /\/record/.test(p.url());
	const connected = await p.locator('.conn.ok').count();
	console.log('reached /record:', onRecord, '| stream connected:', connected === 1);

	// short, light run
	await setNum(p, 'Duration', 3);
	await setNum(p, 'Sample rate', 8000);
	await setNum(p, 'Spindle', 1500);
	await p.click('.btn.start');

	// watch live streaming: FRM points should climb and elapsed advance
	await p.waitForTimeout(1500);
	const pts1 = parseInt((await p.locator('.pts').first().innerText()).replace(/\D/g, '') || '0', 10);
	const live = await p.locator('.live-badge').count();
	await p.waitForTimeout(1200);
	const pts2 = parseInt((await p.locator('.pts').first().innerText()).replace(/\D/g, '') || '0', 10);
	console.log('live badge:', live === 1, '| FRM pts', pts1, '->', pts2);
	await p.screenshot({ path: 'tests/ui/recording_live.png', fullPage: true });

	// wait for the run to finish and the captured view to render
	await p.locator('text=Captured fingerprint').waitFor({ timeout: 15000 }).catch(() => {});
	await p.waitForTimeout(3500);
	const captured = await p.locator('text=Captured fingerprint').count();
	const canvas = await p.locator('.finished-frm canvas').count();
	const summary = await p.locator('.summary').count();
	console.log('captured view:', captured === 1, '| finished canvas:', canvas, '| summary:', summary === 1);
	await p.screenshot({ path: 'tests/ui/recording_finished.png', fullPage: true });

	ok = onRecord && connected === 1 && live === 1 && pts2 > pts1 && pts1 > 0 && captured === 1 && canvas >= 1;
	if (errs.length) console.log('page console errors:', JSON.stringify(errs.slice(0, 8), null, 2));
	await b.close();
	console.log(ok ? 'PASS' : 'FAIL');
	process.exit(ok ? 0 : 1);
})();
