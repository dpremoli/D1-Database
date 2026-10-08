import { describe, expect, it, vi } from 'vitest';
import { CHECK_TIMEOUT_MS, LINGER_MS, notifiedMarker, runUpdateCheck, type UpdateCheckDeps } from './updateCheck';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

function deps(over: Partial<UpdateCheckDeps> = {}) {
  const timers: { fn: () => void; ms: number; cleared: boolean }[] = [];
  const d: UpdateCheckDeps & { timers: typeof timers } = {
    isPackaged: true,
    checkForUpdate: vi.fn(async () => '2.0.0'),
    lastNotified: () => null,
    markNotified: vi.fn(),
    notify: vi.fn(),
    launchApp: vi.fn(),
    quit: vi.fn(),
    setTimer: (fn, ms) => { const t = { fn, ms, cleared: false }; timers.push(t); return t; },
    clearTimer: (t) => { (t as { cleared: boolean }).cleared = true; },
    timers,
    ...over,
  };
  return d;
}

describe('runUpdateCheck', () => {
  it('notifies once for a newer version, marks it, and lingers instead of quitting', async () => {
    const d = deps();
    await runUpdateCheck(d);
    expect(d.notify).toHaveBeenCalledTimes(1);
    expect((d.notify as any).mock.calls[0][0].title).toBe('Force App 2.0.0 is available');
    expect(d.markNotified).toHaveBeenCalledWith('2.0.0');
    expect(d.quit).not.toHaveBeenCalled();
    expect(d.timers[0].cleared).toBe(true);                 // the give-up timer must not cut the linger short
    expect(d.timers[1].ms).toBe(LINGER_MS);
    d.timers[1].fn();
    expect(d.quit).toHaveBeenCalled();
  });

  it('the notification click launches the app', async () => {
    const d = deps();
    await runUpdateCheck(d);
    (d.notify as any).mock.calls[0][1]();
    expect(d.launchApp).toHaveBeenCalled();
  });

  it('is silent for a version it already told the operator about', async () => {
    const d = deps({ lastNotified: () => '2.0.0' });
    await runUpdateCheck(d);
    expect(d.notify).not.toHaveBeenCalled();
    expect(d.quit).toHaveBeenCalled();
  });

  it('quits quietly when there is no update, or the check fails (offline)', async () => {
    for (const checkForUpdate of [async () => null, async () => { throw new Error('offline'); }]) {
      const d = deps({ checkForUpdate });
      await runUpdateCheck(d);
      expect(d.notify).not.toHaveBeenCalled();
      expect(d.quit).toHaveBeenCalled();
    }
  });

  it('gives up after the check timeout if the feed never answers', async () => {
    const d = deps({ checkForUpdate: () => new Promise(() => {}) });
    void runUpdateCheck(d);
    expect(d.timers[0].ms).toBe(CHECK_TIMEOUT_MS);
    d.timers[0].fn();
    expect(d.quit).toHaveBeenCalled();
  });

  it('does nothing in a dev (unpackaged) run', async () => {
    const d = deps({ isPackaged: false });
    await runUpdateCheck(d);
    expect(d.checkForUpdate).not.toHaveBeenCalled();
    expect(d.quit).toHaveBeenCalled();
  });
});

describe('notifiedMarker', () => {
  it('round-trips the version and reads null when missing or corrupt', () => {
    const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'force-marker-'));
    const m = notifiedMarker(path.join(dir, 'sub'));
    expect(m.read()).toBeNull();
    m.write('2.0.0');
    expect(m.read()).toBe('2.0.0');
    fs.writeFileSync(path.join(dir, 'sub', 'update-notified.json'), '{nope');
    expect(m.read()).toBeNull();
  });
});
