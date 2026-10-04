import { EventEmitter } from 'node:events';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

// Review 2.4: "Update now" must re-check for a running/finalizing recording at the click.

const h = vi.hoisted(() => ({
  handlers: new Map<string, (...a: unknown[]) => unknown>(),
  showMessageBox: vi.fn(),
  quitAndInstall: vi.fn(),
  updater: null as any,
}));

vi.mock('electron', () => ({
  app: { isPackaged: true, getVersion: () => '1.0.0' },
  dialog: { showMessageBox: (...a: unknown[]) => h.showMessageBox(...a) },
  ipcMain: { handle: (ch: string, fn: (...a: unknown[]) => unknown) => { h.handlers.set(ch, fn); } },
  Notification: class { static isSupported() { return false; } show() {} },
}));
vi.mock('electron-updater', () => {
  const u: any = new EventEmitter();
  u.checkForUpdates = vi.fn(async () => undefined);
  u.quitAndInstall = (...a: unknown[]) => h.quitAndInstall(...a);
  h.updater = u;
  return { autoUpdater: u };
});

async function boot(isRecording: () => Promise<boolean>) {
  vi.resetModules();
  h.handlers.clear();
  const { initAutoUpdater } = await import('./updater');
  initAutoUpdater(() => null, isRecording);
}

async function downloaded() {
  h.updater.emit('update-downloaded', { version: '2.0.0' });
  await vi.advanceTimersByTimeAsync(0);
}

beforeEach(() => {
  vi.useFakeTimers();
  h.showMessageBox.mockReset();
  h.quitAndInstall.mockReset();
  h.updater?.removeAllListeners();
});
afterEach(() => { vi.useRealTimers(); });

describe('updater recording gate', () => {
  it('installs when "Update now" is clicked and nothing is recording', async () => {
    await boot(async () => false);
    h.showMessageBox.mockResolvedValue({ response: 0 });
    await downloaded();
    await vi.advanceTimersByTimeAsync(1000);
    expect(h.quitAndInstall).toHaveBeenCalledWith(true, true);
  });

  it('does not install when a recording (or finalize) started while the dialog was open', async () => {
    let busy = false;
    await boot(async () => busy);
    h.showMessageBox.mockImplementationOnce(async () => { busy = true; return { response: 0 }; });
    h.showMessageBox.mockResolvedValue({ response: 0 });   // the "postponed" notice
    await downloaded();
    await vi.advanceTimersByTimeAsync(1000);
    expect(h.quitAndInstall).not.toHaveBeenCalled();
    // and it is offered again once the cut is over
    h.showMessageBox.mockClear();
    h.showMessageBox.mockResolvedValue({ response: 1 });
    busy = false;
    await vi.advanceTimersByTimeAsync(60_000);
    expect(h.showMessageBox.mock.calls[0][0].title).toBe('Update ready');
  });

  it('defers the first prompt while busy', async () => {
    await boot(async () => true);
    await downloaded();
    expect(h.showMessageBox).not.toHaveBeenCalled();
  });

  it('update:install refuses while busy', async () => {
    let busy = true;
    await boot(async () => busy);
    h.showMessageBox.mockResolvedValue({ response: 1 });
    await downloaded();   // status becomes "downloaded" (prompt deferred)
    const install = h.handlers.get('update:install')!;
    expect(await install()).toMatchObject({ ok: false });
    busy = false;
    expect(await install()).toEqual({ ok: true });
  });
});
