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

const APP = { senderFrame: { url: 'app://force/settings/about' } };
const FOREIGN = { senderFrame: { url: 'https://evil.example/' } };

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
    expect(await install(APP)).toMatchObject({ ok: false });
    busy = false;
    expect(await install(APP)).toEqual({ ok: true });
  });

  // Review 2.11: the update:* handlers check the sender like dialog:pickFolder / shell:reveal.
  it('update:* handlers refuse a page that is not app://force', async () => {
    await boot(async () => false);
    h.showMessageBox.mockResolvedValue({ response: 1 });
    await downloaded();
    expect(await h.handlers.get('update:install')!(FOREIGN)).toEqual({ ok: false, reason: 'not allowed from this page' });
    expect(await h.handlers.get('update:check')!(FOREIGN)).toEqual({ ok: false, reason: 'not allowed from this page' });
    expect(await h.handlers.get('update:get-info')!(FOREIGN)).toMatchObject({ version: '', packaged: false });
    await vi.advanceTimersByTimeAsync(1000);
    expect(h.quitAndInstall).not.toHaveBeenCalled();
  });

  it('update:* handlers serve the app\'s own pages', async () => {
    await boot(async () => false);
    expect(await h.handlers.get('update:get-info')!(APP)).toMatchObject({ version: '1.0.0', packaged: true });
    expect(await h.handlers.get('update:check')!(APP)).toEqual({ ok: true });
    expect(await h.handlers.get('update:install')!(APP)).toMatchObject({ ok: false, reason: 'no update downloaded yet' });
  });
});
