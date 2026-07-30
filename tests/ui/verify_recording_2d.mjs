// 2d: Directus run write-back + offline queue. Records a sim cut, picks a real Directus sample,
// logs the run (a manufacturing_operations row), verifies the row in Directus, then repeats OFFLINE
// to prove the queue holds it and flushes on reconnect. Created rows are deleted (DB left clean).
//   FORCE_APP_EMAIL=… FORCE_APP_PASSWORD=… node tests/ui/verify_recording_2d.mjs
import { chromium } from '@playwright/test';

const BASE = process.env.FORCE_APP_BASE_URL || 'http://localhost:5180';
const DIRECTUS = process.env.DIRECTUS_URL || 'http://localhost:8055';
const EMAIL = process.env.FORCE_APP_EMAIL || 'admin@example.com';
const PASS = process.env.FORCE_APP_PASSWORD || '';

async function dtoken() {
	const r = await fetch(`${DIRECTUS}/auth/login`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ email: EMAIL, password: PASS }) });
	return (await r.json()).data.access_token;
}
async function findByPass(tok, pass) {
	const r = await fetch(`${DIRECTUS}/items/manufacturing_operations?filter[pass_code][_eq]=${encodeURIComponent(pass)}&fields=operation_id,sample_id,capture_software,machining_force_captured,machining_spindle_speed_rpm`, { headers: { Authorization: `Bearer ${tok}` } });
	return (await r.json()).data || [];
}
async function del(tok, id) {
	await fetch(`${DIRECTUS}/items/manufacturing_operations/${id}`, { method: 'DELETE', headers: { Authorization: `Bearer ${tok}` } });
}

async function runShortSim(p) {
	await p.locator('label', { hasText: 'Duration' }).locator('input').fill('2');
	await p.locator('label', { hasText: 'Sample rate' }).locator('input').fill('6000');
	await p.locator('.btn.start').click();
	await p.locator('.ro b.done').waitFor({ timeout: 20000 });
	await p.waitForTimeout(500);
}

(async () => {
	const tok = await dtoken();
	const b = await chromium.launch();
	const ctx = await b.newContext({ ignoreHTTPSErrors: true, viewport: { width: 1720, height: 1040 } });
	const p = await ctx.newPage();
	const errs = [];
	p.on('console', (m) => { if (m.type() === 'error') errs.push(m.text()); });
	let ok = true;
	const created = [];

	await p.goto(BASE, { waitUntil: 'networkidle' });
	await p.fill('input[type="email"]', EMAIL);
	await p.fill('input[type="password"]', PASS);
	await p.click('button[type="submit"]');
	await p.waitForTimeout(2500);
	await p.locator('.card', { hasText: 'Recording' }).click();
	await p.waitForTimeout(1000);

	// pick a real sample (typeahead) — auto-fills Ø
	const sampleField = p.locator('.lookup').filter({ hasText: 'Sample' }).first();
	await sampleField.locator('input').click();
	await sampleField.locator('input').fill('AA');
	await p.waitForTimeout(1200);
	const opts = await sampleField.locator('.menu .mi:not(.hint)').count();
	await sampleField.locator('.menu .mi:not(.hint)').first().click();
	const sampleLabel = await sampleField.locator('input').inputValue();
	console.log('sample options:', opts, '| picked:', sampleLabel);
	ok = ok && opts > 0 && !!sampleLabel;

	// ---- ONLINE run + log ----
	const mark1 = `E2E2D-ON-${Date.now()}`;
	await runShortSim(p);
	await p.locator('label', { hasText: 'Operation / pass code' }).locator('input').fill(mark1);
	await p.locator('.btn.save').click();
	await p.waitForTimeout(2500);
	const rows1 = await findByPass(tok, mark1);
	console.log('online row created:', rows1.length === 1, rows1[0] && { sample: !!rows1[0].sample_id, forceCaptured: rows1[0].machining_force_captured, sw: rows1[0].capture_software, rpm: rows1[0].machining_spindle_speed_rpm });
	ok = ok && rows1.length === 1 && rows1[0].capture_software === 'force-app' && rows1[0].machining_force_captured === true && !!rows1[0].sample_id;
	rows1.forEach((r) => created.push(r.operation_id));
	await p.screenshot({ path: 'tests/ui/recording_2d_online.png', fullPage: true });

	// ---- OFFLINE run + log -> queued -> reconnect -> flushed ----
	await p.locator('.btn.ghost', { hasText: 'New' }).click();
	await runShortSim(p);
	await ctx.setOffline(true);
	const mark2 = `E2E2D-OFF-${Date.now()}`;
	await p.locator('label', { hasText: 'Operation / pass code' }).locator('input').fill(mark2);
	await p.locator('.btn.save').click();
	await p.waitForTimeout(1500);
	const queuedChip = await p.locator('.syncchip.warn').count();
	const rowsWhileOffline = await findByPass(tok, mark2);
	console.log('queued offline (chip):', queuedChip >= 1, '| row exists while offline:', rowsWhileOffline.length);
	await p.screenshot({ path: 'tests/ui/recording_2d_offline.png', fullPage: true });
	ok = ok && queuedChip >= 1 && rowsWhileOffline.length === 0;

	await ctx.setOffline(false);
	// wait for the online event / retry timer to flush
	let rows2 = [];
	for (let i = 0; i < 20; i++) { await p.waitForTimeout(1000); rows2 = await findByPass(tok, mark2); if (rows2.length) break; }
	console.log('flushed after reconnect:', rows2.length === 1);
	ok = ok && rows2.length === 1;
	rows2.forEach((r) => created.push(r.operation_id));

	// cleanup
	for (const id of created) await del(tok, id);
	console.log('cleaned up rows:', created.length);

	if (errs.length) console.log('page console errors:', JSON.stringify(errs.slice(0, 8), null, 2));
	await b.close();
	console.log(ok ? 'PASS' : 'FAIL');
	process.exit(ok ? 0 : 1);
})();
