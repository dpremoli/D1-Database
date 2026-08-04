import { chromium } from '@playwright/test';
const BASE = process.env.D1_BASE_URL || 'http://localhost:8055';
const EMAIL = process.env.D1_ADMIN_EMAIL || 'admin@example.com';
const PASS = process.env.D1_ADMIN_PASSWORD || '';
const OP = process.env.OP || '9fa1f0e9-373c-5de6-af48-57f1b4df87bb'; // 98-AA-MF ... has live cache
(async () => {
  const b = await chromium.launch();
  const c = await b.newContext({ ignoreHTTPSErrors: true, viewport: { width: 1700, height: 1000 } });
  const p = await c.newPage();
  const errs = [];
  p.on('console', m => { if (m.type()==='error' && !m.text().includes('auth/refresh') && !m.text().includes('status of 400')) errs.push(m.text()); });
  p.on('pageerror', e => errs.push('PAGEERROR: ' + e.message));
  await p.goto(`${BASE}/admin/login`);
  await p.fill('input[type="email"]', EMAIL);
  await p.fill('input[type="password"]', PASS);
  await p.click('button[type="submit"]');
  await p.waitForTimeout(2500);

  await p.goto(`${BASE}/admin/d1-force-dashboard?operation=${OP}`, { waitUntil: 'networkidle' });
  await p.waitForTimeout(3500);

  // enable Live mode
  const liveBtn = p.locator('button.tbtn', { hasText: 'Live' });
  console.log('Live button count:', await liveBtn.count());
  await liveBtn.first().click();
  await p.waitForTimeout(4000); // cache download + first rebuild

  const canvas = p.locator('.frm-cloud canvas');
  console.log('frm canvas present:', await canvas.count());
  const ptsTxt = (await p.locator('.fc-count').first().textContent().catch(()=>'')).trim();
  console.log('point count label:', ptsTxt);
  const cbar = await p.locator('.fc-cbar').count();
  const cmax = (await p.locator('.fc-cbar .fc-cval').first().textContent().catch(()=>'')).trim();
  const cmin = (await p.locator('.fc-cbar .fc-cval').last().textContent().catch(()=>'')).trim();
  console.log('colorbar present:', cbar, '| cmax:', cmax, '| cmin:', cmin, '| unit:', (await p.locator('.fc-cunit').first().textContent().catch(()=>'')).trim());

  // sample rendered webgl pixels: copy canvas to a 2d canvas and inspect colours
  const colorStats = await p.evaluate(() => {
    const cv = document.querySelector('.frm-cloud canvas');
    if (!cv) return null;
    const off = document.createElement('canvas'); off.width = cv.width; off.height = cv.height;
    const ctx = off.getContext('2d'); ctx.drawImage(cv, 0, 0);
    const { data } = ctx.getImageData(0, 0, off.width, off.height);
    let nonEmpty = 0, yellowish = 0, greenish = 0, purplish = 0;
    const samples = [];
    for (let i = 0; i < data.length; i += 4) {
      const r = data[i], g = data[i+1], bl = data[i+2], a = data[i+3];
      if (a < 20) continue;
      nonEmpty++;
      if (r > 180 && g > 180 && bl < 130) yellowish++;       // viridis high end
      else if (g > 120 && g > r && g > bl) greenish++;        // viridis mid
      else if (bl > 90 && bl >= g && r < 120) purplish++;     // viridis low end
      if (samples.length < 8 && Math.random() < 0.02) samples.push([r,g,bl]);
    }
    return { w: off.width, h: off.height, nonEmpty, yellowish, greenish, purplish, samples };
  });
  console.log('canvas colour stats:', JSON.stringify(colorStats));

  await p.screenshot({ path: 'force_live.png', fullPage: false });
  // tighter shot of just the FRM cloud
  await p.locator('.frm-cloud').first().screenshot({ path: 'force_live_frm.png' }).catch(()=>{});

  // pan the canvas: should stay interactive with no errors, point count unchanged
  const box = await canvas.first().boundingBox();
  if (box) {
    await p.mouse.move(box.x + box.width*0.5, box.y + box.height*0.5);
    await p.mouse.down();
    await p.mouse.move(box.x + box.width*0.65, box.y + box.height*0.6, { steps: 12 });
    await p.mouse.up();
    await p.waitForTimeout(500);
  }
  const ptsAfter = (await p.locator('.fc-count').first().textContent().catch(()=>'')).trim();
  console.log('point count after pan:', ptsAfter, '(unchanged =', ptsAfter === ptsTxt, ')');

  console.log('errors:', errs.length ? JSON.stringify(errs.slice(0,6)) : 'none');
  await b.close();
})().catch(e => { console.error(e); process.exit(1); });
