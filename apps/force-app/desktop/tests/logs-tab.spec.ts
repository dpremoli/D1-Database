import { test, expect, _electron as electron, type ElectronApplication, type Page } from '@playwright/test';
import fs from 'node:fs';
import path from 'node:path';

// Settings > Logs, driven in the real app against the real backend log file. Covers the whole
// chain the feature depends on: FORCE_APP_LOG_DIR threading, the /logs endpoint, and the pane.

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
  await window.waitForURL((u) => u.href.startsWith('app://force/'), { timeout: 30_000 });
  const userDataDir = await app.evaluate(({ app: a }) => a.getPath('userData'));
  const cfg = JSON.parse(fs.readFileSync(path.join(userDataDir, 'config.json'), 'utf-8'));
  await window.route(`${new URL(cfg.directusUrl).origin}/**`, (route) =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ data: [] }) }),
  );
  await window.evaluate(() => {
    localStorage.setItem('force-app.auth', JSON.stringify({
      accessToken: 't', refreshToken: 't', expiresAt: Date.now() + 3_600_000, user: { id: 'test', role: null },
    }));
  });
}

test('Settings > Logs shows real backend log records and filters them', async () => {
  const app = await launch();
  try {
    const window = await app.firstWindow();
    await bypassLogin(window, app);

    // Guarantee at least one log line exists rather than assuming one does. On a long-lived dev
    // profile the backend has always logged *something* by now, which is exactly what made this
    // assumption invisible here — but dev-mode Electron launches share one userData dir, so that
    // history is really just every earlier test run in this session, not anything this test
    // produced. A genuinely fresh install (a real first run, or CI) starts with an empty log, and
    // nothing up to this point in the test has hit an endpoint that logs. recovery_discard logs
    // unconditionally in a `finally`, succeeds or not, so a 404 against a nonexistent id is a safe,
    // side-effect-free way to manufacture one deterministically.
    const userDataDir = await app.evaluate(({ app: a }) => a.getPath('userData'));
    const cfg = JSON.parse(fs.readFileSync(path.join(userDataDir, 'config.json'), 'utf-8'));
    await fetch(`${cfg.recorderUrl}/recovery/discard/e2e-logs-tab-sentinel`, { method: 'POST' });

    // Deep-link straight to the tab, the same route the Help > View Logs menu item sends.
    await window.goto('app://force/settings?tab=logs');
    await expect(window.locator('.loglist')).toBeVisible({ timeout: 15_000 });

    const rows = window.locator('.loglist .row');
    await expect.poll(async () => rows.count(), { timeout: 15_000 }).toBeGreaterThan(0);
    const total = await rows.count();
    console.log(`[logs-tab] ${total} records rendered`);

    // Every row should carry a module and a message; a parse regression would blank these.
    await expect(rows.first().locator('.msg')).not.toBeEmpty();

    // Narrowing to WARNING+ must never widen the list.
    await window.locator('.tb-field select').first().selectOption('WARNING');
    await expect.poll(async () => rows.count(), { timeout: 10_000 }).toBeLessThanOrEqual(total);
    for (const lvl of await rows.locator('.lvl').allInnerTexts()) {
      expect(['WARNING', 'ERROR', 'CRITICAL']).toContain(lvl.trim());
    }

    // A search that cannot match anything should empty the list (server-side filtering).
    await window.locator('.tb-field select').first().selectOption('');
    await window.locator('.tb-field.grow input').fill('zzz-no-such-token-zzz');
    await expect(window.locator('.loglist .empty')).toBeVisible({ timeout: 10_000 });

    // ...and clearing it brings them back.
    await window.locator('.tb-field.grow input').fill('');
    await expect.poll(async () => rows.count(), { timeout: 10_000 }).toBeGreaterThan(0);
  } finally {
    try {
      const window = await app.firstWindow();
      await window.evaluate(() => localStorage.removeItem('force-app.auth'));
    } catch { /* best effort */ }
    await app.close();
  }
});
