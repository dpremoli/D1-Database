import { chromium } from '@playwright/test';
import path from 'node:path';
const BASE = process.env.D1_BASE_URL || 'http://localhost:8055';
const EMAIL = process.env.D1_ADMIN_EMAIL || 'admin@example.com';
const PASS = process.env.D1_ADMIN_PASSWORD || '';
const OP = 'a2e2c03a-2d05-51ed-baf4-8e03f92522b6';
const CSV = path.resolve(process.env.REPO_ROOT || '../..', 'FAST Data/25 example.CSV');
(async () => {
  const b = await chromium.launch();
  const c = await b.newContext({ ignoreHTTPSErrors: true, viewport: { width: 1600, height: 950 } });
  const p = await c.newPage();
  const errs = [];
  p.on('console', m => { if (m.type()==='error' && !m.text().includes('auth/refresh') && !m.text().includes('status of 400')) errs.push(m.text()); });
  p.on('pageerror', e => errs.push('PAGEERROR: ' + e.message));
  await p.goto(`${BASE}/admin/login`);
  await p.fill('input[type="email"]', EMAIL);
  await p.fill('input[type="password"]', PASS);
  await p.click('button[type="submit"]');
  await p.waitForTimeout(2500);

  await p.goto(`${BASE}/admin/d1-fast-dashboard?operation=${OP}`, { waitUntil: 'networkidle' });
  await p.waitForTimeout(2500);

  console.log('uploading:', CSV);
  await p.setInputFiles('input[type="file"]', CSV);
  // wait for the row to actually flip to pending (import-msg shows the queued text)
  await p.waitForFunction(() => {
    const m = document.querySelector('.import-msg')?.textContent || '';
    return /Queued|importing|waiting/i.test(m);
  }, { timeout: 15000 }).catch(()=>{});

  // now poll ONLY the authoritative import-msg for the terminal "Imported." set by pollImport
  let done = false;
  for (let i = 0; i < 90; i++) {
    await p.waitForTimeout(2000);
    const msg = (await p.locator('.import-msg').first().textContent().catch(()=>'')).trim();
    if (i % 3 === 0) console.log(`  t+${i*2}s  import-msg="${msg}"`);
    if (/Imported\./.test(msg)) { done = true; break; }
    if (/failed|stalled/i.test(msg)) { console.log('FAILED msg:', msg); break; }
  }
  console.log('upload reached done:', done);

  await p.waitForTimeout(2000);
  const trace = (await p.locator('.trace-meta').first().textContent().catch(()=>'')).trim();
  const paths1 = await p.locator('.plot-grid .plot-tile').nth(0).locator('.fchart-svg path').count();
  const paths2 = await p.locator('.plot-grid .plot-tile').nth(1).locator('.fchart-svg path').count();
  console.log('final trace:', trace);
  console.log('tile1 polylines:', paths1, '| tile2 polylines:', paths2);
  await p.screenshot({ path: 'fast25_upload.png', fullPage: false });
  console.log('errors:', errs.length ? JSON.stringify(errs.slice(0,6)) : 'none');
  await b.close();
  process.exit(done && paths1 > 0 ? 0 : 1);
})().catch(e => { console.error(e); process.exit(1); });
