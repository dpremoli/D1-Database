import { test, expect, _electron as electron, type ElectronApplication, type Page } from '@playwright/test';
import fs from 'node:fs';
import path from 'node:path';

// Verifies the Record page's modular panel grid actually fills the window at several window sizes,
// which a fixed :row-height could never do (it pinned the grid to 28*(30+12)+12 = 1188px regardless
// of viewport). Measures real DOM geometry rather than asserting on the computed row height, so it
// tests the user-visible outcome: the bottom-most panel's bottom edge sits near the window bottom.

const MAIN_JS = path.join(__dirname, '..', 'dist', 'main.js');

async function launch(): Promise<ElectronApplication> {
  const { ELECTRON_RUN_AS_NODE, ...cleanEnv } = process.env;
  return electron.launch({
    args: [MAIN_JS],
    env: { ...cleanEnv, FORCE_APP_TEST_HOOKS: '1' },
    timeout: 30_000,
  });
}

async function bypassLogin(window: Page, app: ElectronApplication): Promise<void> {
  // Must wait for the app:// origin first — the window starts on a file:// loading screen, and
  // localStorage written there lands on a different origin and is invisible to the SPA.
  await window.waitForURL((u) => u.href.startsWith('app://force/'), { timeout: 30_000 });
  const userDataDir = await app.evaluate(({ app: a }) => a.getPath('userData'));
  const cfg = JSON.parse(fs.readFileSync(path.join(userDataDir, 'config.json'), 'utf-8'));
  const origin = new URL(cfg.directusUrl).origin;
  await window.route(`${origin}/**`, (route) =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ data: [] }) }),
  );
  await window.evaluate(() => {
    localStorage.setItem('force-app.auth', JSON.stringify({
      accessToken: 't', refreshToken: 't', expiresAt: Date.now() + 3_600_000, user: { id: 'test', role: null },
    }));
    // Start from the stock layout so the assertion isn't at the mercy of a previously-saved one.
    localStorage.removeItem('force-app.record.layout.v7');
  });
  await window.goto('app://force/');
  await window.waitForURL((u) => u.href.includes('/record'), { timeout: 15_000 });
}

/** Gap in px between the lowest panel's bottom edge and the window's inner bottom. */
async function bottomGap(window: Page): Promise<number> {
  return window.evaluate(() => {
    const items = [...document.querySelectorAll('.vgl-item')];
    const lowest = Math.max(...items.map((el) => el.getBoundingClientRect().bottom));
    return window.innerHeight - lowest;
  });
}

test('record panels fill the window at multiple sizes', async () => {
  const app = await launch();
  try {
    const window = await app.firstWindow();
    await bypassLogin(window, app);
    await expect(window.locator('.vgl-item').first()).toBeVisible({ timeout: 15_000 });

    // `exactFit: false` = the stock 28-row layout cannot fit this viewport without rows dropping
    // below MIN_ROW_H, so the design deliberately clamps and lets the page scroll rather than
    // squashing every panel into an unreadable sliver. Overflow there is correct, not a failure.
    const sizes = [
      { width: 1500, height: 950, exactFit: true },   // the app's own default window size
      { width: 1400, height: 1400, exactFit: true },  // tall: the old fixed 30px row height left
                                                      // ~164px of dead space below the last panel
                                                      // here, which is the reported bug
      { width: 1280, height: 720, exactFit: false },  // small: expected to clamp and scroll
    ];

    for (const size of sizes) {
      await app.evaluate(async ({ BrowserWindow }, s) => {
        BrowserWindow.getAllWindows()[0].setContentSize(s.width, s.height);
      }, size);
      // ResizeObserver + the row-height recompute need a frame or two to settle.
      await window.waitForTimeout(600);

      const gap = await bottomGap(window);
      const innerH = await window.evaluate(() => window.innerHeight);
      console.log(`[panel-fit] ${size.width}x${size.height} -> innerHeight=${innerH}, bottom gap=${gap.toFixed(0)}px${size.exactFit ? '' : ' (clamped, scrolls)'}`);

      // The regression under test: a fixed row height left the grid the same pixel height at every
      // window size, so a tall window showed a large dead strip below the last panel. That must
      // never happen now, at any size.
      expect(gap).toBeLessThan(90);
      // Where there is room to fit exactly, the panels should also not spill past the fold.
      if (size.exactFit) expect(gap).toBeGreaterThan(-40);
    }
  } finally {
    try {
      const window = await app.firstWindow();
      await window.evaluate(() => localStorage.removeItem('force-app.auth'));
    } catch { /* best effort */ }
    await app.close();
  }
});
