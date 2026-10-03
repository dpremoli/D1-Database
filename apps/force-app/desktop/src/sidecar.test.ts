import { describe, it, expect, afterEach } from 'vitest';
import path from 'node:path';
import { SidecarSupervisor, type SidecarState } from './sidecar';

const FIXTURE = path.join(__dirname, '__fixtures__', 'fake-backend.js');

function freePort(): number {
  // Test-only: a high random port. Real probing is covered by port.test.ts.
  return 39000 + Math.floor(Math.random() * 5000);
}

describe('SidecarSupervisor', () => {
  let sup: SidecarSupervisor | undefined;

  afterEach(async () => {
    await sup?.stop();
  });

  it('reaches ready once the fixture backend answers /health', async () => {
    const port = freePort();
    const states: SidecarState[] = [];
    sup = new SidecarSupervisor({
      exePath: process.execPath,
      args: [FIXTURE, String(port)],
      port,
      healthUrl: `http://127.0.0.1:${port}/health`,
      readyTimeoutMs: 5000,
      onStateChange: (s) => states.push(s),
    });
    await sup.start();
    expect(sup.getState()).toBe('ready');
    expect(states).toContain('starting');
    expect(states).toContain('ready');
  });

  it('reports crashed if the process never becomes healthy in time', async () => {
    const port = freePort();
    sup = new SidecarSupervisor({
      exePath: process.execPath,
      args: [FIXTURE, String(port), '--delay=999999'],
      port,
      healthUrl: `http://127.0.0.1:${port}/health`,
      readyTimeoutMs: 1000,
      maxRestarts: 0,
    });
    await sup.start();
    expect(sup.getState()).toBe('crashed');
  });

  it('restarts with backoff after the process dies, then gives up after maxRestarts', async () => {
    const port = freePort();
    const states: SidecarState[] = [];
    sup = new SidecarSupervisor({
      exePath: process.execPath,
      args: [FIXTURE, String(port)],
      port,
      healthUrl: `http://127.0.0.1:${port}/health`,
      readyTimeoutMs: 5000,
      maxRestarts: 1,
      onStateChange: (s) => states.push(s),
    });
    await sup.start();
    expect(sup.getState()).toBe('ready');

    // Simulate a crash: kill the process out from under the supervisor.
    process.kill(sup.getPid()!);
    await new Promise((r) => setTimeout(r, 3000));
    expect(sup.getState()).toBe('ready');
    expect(states).toContain('restarting');
    expect(sup.getRestartCount()).toBe(1);

    // A second crash exceeds maxRestarts=1 — the supervisor must give up rather than loop forever.
    process.kill(sup.getPid()!);
    await new Promise((r) => setTimeout(r, 4000));
    expect(sup.getState()).toBe('crashed');
  }, 15000);

  // stop() kills the tree with Windows `taskkill` (killTree), so this only means anything on
  // Windows. It runs in force-app-release.yml (windows-latest); the Linux CI job skips it.
  it.skipIf(process.platform !== 'win32')('stop() terminates the process so a later health request fails', async () => {
    const port = freePort();
    sup = new SidecarSupervisor({
      exePath: process.execPath,
      args: [FIXTURE, String(port)],
      port,
      healthUrl: `http://127.0.0.1:${port}/health`,
      readyTimeoutMs: 5000,
    });
    await sup.start();
    expect(sup.getState()).toBe('ready');
    await sup.stop();
    await expect(
      fetch(`http://127.0.0.1:${port}/health`, { signal: AbortSignal.timeout(500) }),
    ).rejects.toThrow();
  });
});
