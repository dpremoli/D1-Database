// Verifies the reshaped FAST detail panel: recipe card + provenance-tagged stats.
// Follows the convention of the other tests/ui/verify_*.mjs scripts (D1_* env, direct
// ?operation= navigation, generous settle time rather than strict selector waits).
import { chromium } from '@playwright/test';

const BASE = process.env.D1_BASE_URL || 'http://localhost:8055';
const EMAIL = process.env.D1_ADMIN_EMAIL || process.env.DIRECTUS_ADMIN_EMAIL;
const PASS = process.env.D1_ADMIN_PASSWORD || process.env.DIRECTUS_ADMIN_PASSWORD || '';
// A FAST 250 run with a done trace, a populated summary, and a linked recipe.
const OP = process.env.D1_FAST_OP || '725e8266-4688-5cb5-a5df-0d86033a56c9';

(async () => {
  const b = await chromium.launch();
  const c = await b.newContext({ ignoreHTTPSErrors: true, viewport: { width: 1700, height: 1000 } });
  const p = await c.newPage();

  await p.goto(`${BASE}/admin/login`);
  await p.fill('input[type="email"]', EMAIL);
  await p.fill('input[type="password"]', PASS);
  await p.click('button[type="submit"]');
  await p.waitForTimeout(2500);

  await p.goto(`${BASE}/admin/d1-fast-dashboard?operation=${OP}`, { waitUntil: 'networkidle' });
  await p.waitForTimeout(4000);

  const detail = await p.locator('.col-stack').innerText();
  const stats = await p.locator('.statgrid .stat').count();
  const measured = await p.locator('.s-src', { hasText: /measured/i }).count();
  const recipeCard = /Recipe/.test(detail);
  const hasTargets = /Targets|Program/.test(detail);
  // No stat tile should render an empty value (we omit unsourced tiles entirely).
  const emptyVals = await p.locator('.statgrid .s-val').evaluateAll(
    els => els.filter(e => !e.textContent.trim() || e.textContent.trim() === '—').length);

  const dwell = await p.locator('.stat', { hasText: /DWELL/i }).innerText().catch(() => '');
  const firstCodes = await p.locator('.rowcard .mono').evaluateAll(els => els.slice(0, 4).map(e => e.textContent.trim()));
  console.log('dwell tile:', dwell.replace(/\n/g, ' '));
  console.log('first list codes:', JSON.stringify(firstCodes));
  console.log('stat tiles:', stats);
  console.log('tiles tagged "measured":', measured);
  console.log('recipe card present:', recipeCard);
  console.log('recipe program/targets shown:', hasTargets);
  console.log('empty stat tiles (expect 0):', emptyVals);

  await p.screenshot({ path: 'tests/ui/fast_recipe_panel.png', fullPage: true });
  await b.close();

  const ok = stats > 0 && measured > 0 && recipeCard && emptyVals === 0;
  console.log(ok ? 'PASS' : 'FAIL');
  process.exit(ok ? 0 : 1);
})();
