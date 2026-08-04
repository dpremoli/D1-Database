import { chromium } from '@playwright/test';
const BASE = process.env.D1_BASE_URL || 'http://localhost';   // Caddy origin (serves /octrees)
const EMAIL = process.env.D1_ADMIN_EMAIL || 'admin@example.com';
const PASS = process.env.D1_ADMIN_PASSWORD || '';
const OP = '9fa1f0e9-373c-5de6-af48-57f1b4df87bb';   // has a done octree (1.93M pts)
(async () => {
  const b = await chromium.launch({ args: ['--use-gl=swiftshader'] });
  const c = await b.newContext({ ignoreHTTPSErrors: true, viewport: { width: 1700, height: 1000 } });
  const p = await c.newPage();
  const errs = [];
  p.on('console', m => { if (m.type()==='error' && !/auth\/refresh|status of 400/.test(m.text())) errs.push(m.text()); });
  p.on('pageerror', e => errs.push('PAGEERROR: ' + e.message));
  await p.goto(`${BASE}/admin/login`);
  await p.fill('input[type="email"]', EMAIL); await p.fill('input[type="password"]', PASS);
  await p.click('button[type="submit"]'); await p.waitForTimeout(2500);

  await p.goto(`${BASE}/admin/d1-force-dashboard?operation=${OP}`, { waitUntil: 'networkidle' });
  await p.waitForTimeout(3500);

  const btn = p.locator('button.tbtn:has-text("Full-res")');
  console.log('Full-res button present:', await btn.count());
  await btn.first().click();                 // octree available -> toggles octree view
  await p.waitForTimeout(6000);              // stream the octree

  const canvas = await p.locator('.frm-octree canvas').count();
  const pts = (await p.locator('.frm-octree .fc-count').first().textContent().catch(()=>'')).trim();
  console.log('octree canvas present:', canvas, '| points label:', pts);

  const stats = await p.evaluate(() => {
    const cv = document.querySelector('.frm-octree canvas'); if (!cv) return null;
    const off = document.createElement('canvas'); off.width=cv.width; off.height=cv.height;
    const ctx = off.getContext('2d'); ctx.drawImage(cv,0,0);
    const {data}=ctx.getImageData(0,0,off.width,off.height); let nonBg=0;
    for (let i=0;i<data.length;i+=4){ if(data[i+3]>20 && !(Math.abs(data[i]-11)<10&&Math.abs(data[i+1]-16)<10&&Math.abs(data[i+2]-32)<12)) nonBg++; }
    return { nonBg };
  });
  console.log('canvas non-bg pixels:', JSON.stringify(stats));
  await p.screenshot({ path: 'force_octree.png', fullPage: false });
  console.log('errors:', errs.length ? JSON.stringify(errs.slice(0,6)) : 'none');
  await b.close();
})().catch(e => { console.error(e); process.exit(1); });
