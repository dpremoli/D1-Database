import { chromium } from '@playwright/test';
const BASE = process.env.D1_BASE_URL || 'http://localhost:8055';
const EMAIL = process.env.D1_ADMIN_EMAIL || 'admin@example.com';
const PASS = process.env.D1_ADMIN_PASSWORD || '';
const OP = '9fa1f0e9-373c-5de6-af48-57f1b4df87bb'; // 98-AA-MF, has live cache (feed 0.1)
(async () => {
  const b = await chromium.launch();
  const c = await b.newContext({ ignoreHTTPSErrors: true, viewport: { width: 1700, height: 1000 } });
  const p = await c.newPage();
  const errs = [];
  p.on('console', m => { if (m.type()==='error' && !/auth\/refresh|status of 400/.test(m.text())) errs.push(m.text()); });
  await p.goto(`${BASE}/admin/login`);
  await p.fill('input[type="email"]', EMAIL); await p.fill('input[type="password"]', PASS);
  await p.click('button[type="submit"]'); await p.waitForTimeout(2500);

  await p.goto(`${BASE}/admin/d1-force-dashboard?operation=${OP}`, { waitUntil: 'networkidle' });
  await p.waitForTimeout(3500);
  // enable Live
  await p.locator('button.tbtn', { hasText: 'Live' }).first().click();
  await p.waitForTimeout(4000);

  // feed input should be clean (0.1), not float32 noise
  const feedVal = await p.locator('.edit-grid label:has-text("Feed") input').first().inputValue().catch(()=>'?');
  console.log('feed input value:', JSON.stringify(feedVal), '| clean:', /^0?\.?\d{1,4}$/.test(feedVal) && !/0000000|9999999/.test(feedVal));
  // FRM cloud present in Live
  const liveCloud1 = await p.locator('.frm-cloud canvas').count();
  console.log('live cloud canvas present:', liveCloud1 > 0);

  // navigate away then back — Live should persist (not drop to the PNG <img>)
  await p.goto(`${BASE}/admin/content`, { waitUntil: 'domcontentloaded' });
  await p.waitForTimeout(1500);
  await p.goto(`${BASE}/admin/d1-force-dashboard?operation=${OP}`, { waitUntil: 'networkidle' });
  await p.waitForTimeout(4500);
  const liveBtnOn = await p.locator('button.tbtn:has-text("Live")').evaluate(el => el.classList.contains('on') || getComputedStyle(el).backgroundColor).catch(()=>null);
  const cloudAfter = await p.locator('.frm-cloud canvas').count();
  const pngAfter = await p.locator('.frm-img img').count();
  console.log('after return — live cloud canvas:', cloudAfter, '| static PNG img:', pngAfter, '| Live btn style:', liveBtnOn);
  console.log('PERSISTED (cloud shown, not PNG):', cloudAfter > 0 && pngAfter === 0);

  console.log('errors:', errs.length ? JSON.stringify(errs.slice(0,6)) : 'none');
  await b.close();
})().catch(e => { console.error(e); process.exit(1); });
