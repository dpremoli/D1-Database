import { describe, it, expect, afterEach } from 'vitest';
import path from 'node:path';
import { SidecarSupervisor, type SidecarState } from './sidecar';

const FIXTURE = path.join(__dirname, '__fixtures__', 'fake-backend.js');

async function waitFor(cond: () => boolean, timeoutMs: number): Promise<void> {
  const deadline = Date.now() + timeoutMs;
  while (!cond() && Date.now() < deadline) await new Promise((r) => setTimeout(r, 50));
}

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

  it('stop() terminates the process so a later health request fails', async () => {
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

  it('keeps answering while the backend writes heavily to stdout (#106)', async () => {
    // Each request writes 2 KB to stdout synchronously, as uvicorn's access log does. 300 of
    // them is ~600 KB, far past a pipe's OS buffer — so this hangs at the first write that finds
    // the pipe full unless the supervisor drains stdout.
    const port = freePort();
    sup = new SidecarSupervisor({
      exePath: process.execPath,
      args: [FIXTURE, String(port), '--chatty=2048'],
      port,
      healthUrl: `http://127.0.0.1:${port}/health`,
      readyTimeoutMs: 5000,
    });
    await sup.start();
    expect(sup.getState()).toBe('ready');
    for (let i = 0; i < 300; i++) {
      const res = await fetch(`http://127.0.0.1:${port}/health`, { signal: AbortSignal.timeout(2000) });
      expect(res.ok).toBe(true);
      await res.text();
    }
  }, 30000);

  it('restarts a backend that stays up but stops answering /health (#106)', async () => {
    const port = freePort();
    const states: SidecarState[] = [];
    sup = new SidecarSupervisor({
      exePath: process.execPath,
      // Wedges its event loop 1 s after starting: the process is alive, so no exit ever fires.
      args: [FIXTURE, String(port), '--hang-after=1000'],
      port,
      healthUrl: `http://127.0.0.1:${port}/health`,
      readyTimeoutMs: 5000,
      livenessIntervalMs: 200,
      livenessTimeoutMs: 200,
      livenessFailures: 2,
      onStateChange: (s) => states.push(s),
    });
    await sup.start();
    const firstPid = sup.getPid();
    await waitFor(() => sup!.getRestartCount() === 1 && sup!.getState() === 'ready', 10000);
    expect(sup.getRestartCount()).toBe(1);
    expect(sup.getState()).toBe('ready');
    expect(sup.getPid()).not.toBe(firstPid);
    expect(states).toContain('restarting');
  }, 15000);

  it('does not restart a healthy backend', async () => {
    const port = freePort();
    sup = new SidecarSupervisor({
      exePath: process.execPath,
      args: [FIXTURE, String(port)],
      port,
      healthUrl: `http://127.0.0.1:${port}/health`,
      readyTimeoutMs: 5000,
      livenessIntervalMs: 100,
      livenessTimeoutMs: 500,
      livenessFailures: 2,
    });
    await sup.start();
    await new Promise((r) => setTimeout(r, 1500));
    expect(sup.getState()).toBe('ready');
    expect(sup.getRestartCount()).toBe(0);
  });
});
