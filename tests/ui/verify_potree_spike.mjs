import { chromium } from '@playwright/test';
const BASE = process.env.D1_BASE_URL || 'http://localhost:8055';
const EMAIL = process.env.D1_ADMIN_EMAIL || 'admin@example.com';
const PASS = process.env.D1_ADMIN_PASSWORD || '';
(async () => {
  const b = await chromium.launch({ args: ['--use-gl=swiftshader','--enable-webgl','--ignore-gpu-blocklist'] });
  const c = await b.newContext({ ignoreHTTPSErrors: true, viewport: { width: 1500, height: 950 } });
  const p = await c.newPage();
  const errs = [];
  p.on('console', m => { if (m.type()==='error' && !/auth\/refresh|status of 400/.test(m.text())) errs.push(m.text()); });
  p.on('pageerror', e => errs.push('PAGEERROR: ' + e.message));
  await p.goto(`${BASE}/admin/login`);
  await p.fill('input[type="email"]', EMAIL); await p.fill('input[type="password"]', PASS);
  await p.click('button[type="submit"]'); await p.waitForTimeout(2500);

  await p.goto(`${BASE}/admin/d1-potree-spike`, { waitUntil: 'networkidle' });
  await p.waitForTimeout(4000);

  const logs = await p.locator('.log li').allTextContents();
  console.log('spike log:'); logs.forEach(l => console.log('   ', l));
  const canvas = await p.locator('.stage canvas').count();
  console.log('canvas present:', canvas > 0);

  // sample rendered pixels: confirm a non-empty viridis-ish render
  const stats = await p.evaluate(() => {
    const cv = document.querySelector('.stage canvas'); if (!cv) return null;
    const off = document.createElement('canvas'); off.width = cv.width; off.height = cv.height;
    const ctx = off.getContext('2d'); ctx.drawImage(cv, 0, 0);
    const { data } = ctx.getImageData(0, 0, off.width, off.height);
    let nonBg = 0, green = 0, yellow = 0, purple = 0;
    for (let i = 0; i < data.length; i += 4) {
      const r = data[i], g = data[i+1], bl = data[i+2];
      // background is #0b1020 ≈ (11,16,32)
      if (Math.abs(r-11)<10 && Math.abs(g-16)<10 && Math.abs(bl-32)<12) continue;
      nonBg++;
      if (r>180&&g>180&&bl<130) yellow++;
      else if (g>110&&g>r&&g>bl) green++;
      else if (bl>90&&r<120) purple++;
    }
    return { w: off.width, h: off.height, nonBg, green, yellow, purple };
  });
  console.log('canvas colour stats:', JSON.stringify(stats));
  await p.screenshot({ path: 'potree_spike.png', fullPage: false });
  console.log('errors:', errs.length ? JSON.stringify(errs.slice(0,8)) : 'none');
  await b.close();
})().catch(e => { console.error(e); process.exit(1); });
