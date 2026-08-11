import { test, expect, _electron as electron, type ElectronApplication } from '@playwright/test';
import fs from 'node:fs';
import path from 'node:path';

const MAIN_JS = path.join(__dirname, '..', 'dist', 'main.js');

async function launch(): Promise<ElectronApplication> {
  // ELECTRON_RUN_AS_NODE forces any Electron binary that inherits it into plain-Node mode
  // (app.whenReady is undefined, immediate crash). This test runner's own environment may have
  // it set (e.g. an interactive dev session); strip it before spreading into the launched
  // process's env so the child always boots as real Electron regardless of the parent's state.
  const { ELECTRON_RUN_AS_NODE, ...cleanEnv } = process.env;
  return electron.launch({
    args: [MAIN_JS],
    env: { ...cleanEnv, FORCE_APP_TEST_HOOKS: '1' },
    timeout: 30_000,
  });
}

async function recorderUrl(app: ElectronApplication): Promise<string> {
  // Neither require() (the brief's original approach) nor dynamic import() is available inside
  // Playwright's app.evaluate() sandbox on this Electron version (both throw). Only ask the
  // Electron process for the plain-data userData path via a bare method call, then read the
  // config file from the test runner's own Node process, which has full fs/path access.
  const userDataDir = await app.evaluate(({ app: electronApp }) => electronApp.getPath('userData'));
  const cfgPath = path.join(userDataDir, 'config.json');
  const raw = fs.readFileSync(cfgPath, 'utf-8');
  return (JSON.parse(raw) as { recorderUrl: string }).recorderUrl;
}

test('the bundle boots: sidecar reaches healthy and the renderer loads on app://force', async () => {
  const app = await launch();
  try {
    const window = await app.firstWindow();
    await window.waitForURL((url) => url.href.startsWith('app://force/'), { timeout: 30_000 });

    const url = await recorderUrl(app);
    const health = await fetch(`${url}/health`);
    expect(health.ok).toBe(true);
  } finally {
    await app.close();
  }
});

test('a killed backend is restarted and stays reachable', async () => {
  const app = await launch();
  try {
    const window = await app.firstWindow();
    await window.waitForURL((url) => url.href.startsWith('app://force/'), { timeout: 30_000 });

    const pid = await app.evaluate(() => {
      const hooks = (global as unknown as { __forceAppTestHooks: { getSupervisor: () => { getPid(): number | null } } })
        .__forceAppTestHooks;
      const currentPid = hooks.getSupervisor().getPid();
      if (currentPid) process.kill(currentPid);
      return currentPid;
    });
    expect(pid).toBeGreaterThan(0);

    const url = await recorderUrl(app);
    await expect
      .poll(
        async () => {
          try {
            const res = await fetch(`${url}/health`, { signal: AbortSignal.timeout(1000) });
            return res.ok;
          } catch {
            return false;
          }
        },
        { timeout: 20_000, intervals: [500] },
      )
      .toBe(true);
  } finally {
    await app.close();
  }
});
