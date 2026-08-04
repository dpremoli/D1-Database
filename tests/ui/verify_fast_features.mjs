import { chromium } from '@playwright/test';
const BASE = process.env.D1_BASE_URL || 'http://localhost:8055';
const EMAIL = process.env.D1_ADMIN_EMAIL || 'admin@example.com';
const PASS = process.env.D1_ADMIN_PASSWORD || '';
const OP = 'a2e2c03a-2d05-51ed-baf4-8e03f92522b6'; // has a done trace (32 series)
(async () => {
  const b = await chromium.launch();
  const c = await b.newContext({ ignoreHTTPSErrors: true, viewport: { width: 1700, height: 1000 } });
  const p = await c.newPage();
  const errs = [];
  p.on('console', m => { if (m.type()==='error' && !/auth\/refresh|status of 400/.test(m.text())) errs.push(m.text()); });
  p.on('pageerror', e => errs.push('PAGEERROR: ' + e.message));
  await p.goto(`${BASE}/admin/login`);
  await p.fill('input[type="email"]', EMAIL); await p.fill('input[type="password"]', PASS);
  await p.click('button[type="submit"]'); await p.waitForTimeout(2500);

  // clear the saved FAST layout so the fresh 2×3 category default seeds
  await p.goto(`${BASE}/admin/`, { waitUntil: 'domcontentloaded' });
  await p.evaluate(() => localStorage.removeItem('d1-fast-dashboard-v1'));

  await p.goto(`${BASE}/admin/d1-fast-dashboard?operation=${OP}`, { waitUntil: 'networkidle' });
  await p.waitForTimeout(4000);

  const tiles = await p.locator('.plot-grid .plot-tile').count();
  const withSeries = await p.locator('.plot-grid .plot-tile .fchart-svg').count();
  console.log('default tiles:', tiles, '(expect 6) | tiles rendering a chart:', withSeries);
  // grid columns (expect 2)
  const cols = await p.locator('.plot-grid').evaluate(el => getComputedStyle(el).gridTemplateColumns.split(' ').length);
  console.log('plot-grid columns:', cols, '(expect 2)');

  // open-form button present
  console.log('open-op-form button:', await p.locator('.openbtn').count() > 0);

  // collapse the operations column, expect the fold-restore button to appear
  await p.locator('.panel-head .collapsebtn').first().click().catch(()=>{});
  await p.waitForTimeout(500);
  const opsHidden = await p.locator('.panel-head').count(); // operations panel gone?
  const restore = await p.locator('.expandbtn').count();
  console.log('after collapse — restore buttons:', restore, '| operations panel-heads left:', opsHidden);
  // restore
  await p.locator('.expandbtn').first().click().catch(()=>{});
  await p.waitForTimeout(400);

  // zoom: turn on rect tool, drag a box on the first chart, expect Reset zoom to enable
  await p.locator('.icobtn').first().click();
  const svg = p.locator('.plot-grid .plot-tile .fchart-svg').first();
  const box = await svg.boundingBox();
  if (box) {
    await p.mouse.move(box.x + box.width*0.35, box.y + box.height*0.5);
    await p.mouse.down();
    await p.mouse.move(box.x + box.width*0.65, box.y + box.height*0.5, { steps: 10 });
    await p.mouse.up();
    await p.waitForTimeout(500);
  }
  const resetDisabled = await p.locator('button:has-text("Reset zoom")').isDisabled().catch(()=>true);
  console.log('after rect-drag — Reset zoom enabled:', !resetDisabled);

  await p.screenshot({ path: 'fast_features.png', fullPage: false });
  console.log('errors:', errs.length ? JSON.stringify(errs.slice(0,6)) : 'none');
  await b.close();
})().catch(e => { console.error(e); process.exit(1); });
