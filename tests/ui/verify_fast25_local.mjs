import { chromium } from '@playwright/test';
const BASE = process.env.D1_BASE_URL || 'http://localhost:8055';
const EMAIL = process.env.D1_ADMIN_EMAIL || 'admin@example.com';
const PASS = process.env.D1_ADMIN_PASSWORD || '';
const OP = 'a2e2c03a-2d05-51ed-baf4-8e03f92522b6'; // 25-machine example CSV import (now done)
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
  await p.waitForTimeout(3000);

  const traceTxt = (await p.locator('.trace-meta').first().textContent().catch(()=>'')).trim();
  console.log('trace meta:', traceTxt);
  console.log('expect 3015 rows / 32 series:', /3015 rows/.test(traceTxt) && /32 series/.test(traceTxt));

  await p.waitForTimeout(1000);
  const tiles = await p.locator('.plot-grid .plot-tile').count();
  const paths1 = await p.locator('.plot-grid .plot-tile').nth(0).locator('.fchart-svg path').count();
  const paths2 = await p.locator('.plot-grid .plot-tile').nth(1).locator('.fchart-svg path').count();
  console.log('tiles:', tiles, '| tile1 polylines:', paths1, '| tile2 polylines:', paths2);

  const tickTexts = await p.locator('.plot-grid .plot-tile').first().locator('.tick').allTextContents();
  const hasNaN = tickTexts.some(t => /NaN|undefined/.test(t));
  console.log('tile1 tick sample:', JSON.stringify(tickTexts.slice(0,6)), '| any NaN:', hasNaN);
  const legendTexts = await p.locator('.plot-grid .plot-tile').first().locator('.lg').allTextContents();
  console.log('tile1 legend:', JSON.stringify(legendTexts));

  await p.screenshot({ path: 'fast25_local.png', fullPage: false });
  console.log('errors:', errs.length ? JSON.stringify(errs.slice(0,6)) : 'none');
  await b.close();
})().catch(e => { console.error(e); process.exit(1); });
