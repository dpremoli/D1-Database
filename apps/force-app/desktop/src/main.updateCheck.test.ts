import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

// #197: `Force App.exe --update-check` (the scheduled task) must create no window and no recorder
// backend, must not behave like a second instance of a running app, and must quit.

const h = vi.hoisted(() => ({
  lockFree: true,
  appHandlers: new Map<string, (...a: any[]) => void>(),
  ready: null as null | (() => void),
  windows: 0,
  sidecars: 0,
  quit: vi.fn(), exit: vi.fn(), relaunch: vi.fn(), releaseLock: vi.fn(),
  requestLock: vi.fn(),
  checkResult: { isUpdateAvailable: true, updateInfo: { version: '2.0.0' } } as any,
  toasts: [] as any[],
  notificationsSupported: true,
  userData: '',
}));

vi.mock('electron', () => {
  class BrowserWindow { constructor() { h.windows++; } static getAllWindows() { return []; } }
  const app = {
    isPackaged: true,
    getPath: () => h.userData,
    getVersion: () => '1.0.0',
    setAppUserModelId: vi.fn(),
    requestSingleInstanceLock: (...a: unknown[]) => h.requestLock(...a),
    releaseSingleInstanceLock: () => h.releaseLock(),
    on: (ev: string, fn: (...a: any[]) => void) => { h.appHandlers.set(ev, fn); },
    whenReady: () => new Promise<void>((r) => { h.ready = r; }),
    quit: () => h.quit(), exit: (c: number) => h.exit(c), relaunch: (o: unknown) => h.relaunch(o),
  };
  class Notification {
    static isSupported() { return h.notificationsSupported; }
    handlers = new Map<string, () => void>();
    constructor(public opts: any) { h.toasts.push(this); }
    on(ev: string, fn: () => void) { this.handlers.set(ev, fn); }
    show() {}
  }
  return {
    app, BrowserWindow, Notification,
    dialog: {}, ipcMain: { handle: vi.fn() }, Menu: { setApplicationMenu: vi.fn(), buildFromTemplate: vi.fn() },
    screen: { getAllDisplays: () => [] }, shell: {},
    protocol: { registerSchemesAsPrivileged: vi.fn(), handle: vi.fn() }, net: {},
  };
});
vi.mock('electron-updater', () => ({
  autoUpdater: { checkForUpdates: async () => h.checkResult, autoDownload: true, autoInstallOnAppQuit: true, on: vi.fn() },
}));
vi.mock('./sidecar', () => ({ SidecarSupervisor: class { constructor() { h.sidecars++; } } }));
vi.mock('./menu', () => ({ buildMenu: () => ({}), applyMenuBarMode: vi.fn() }));

async function boot(argv: string[]) {
  vi.resetModules();
  h.appHandlers.clear();
  h.ready = null;
  process.argv = ['Force App.exe', ...argv];
  await import('./main');
}

beforeEach(async () => {
  const fs = await import('node:fs');
  const os = await import('node:os');
  const path = await import('node:path');
  h.userData = fs.mkdtempSync(path.join(os.tmpdir(), 'force-uc-'));
  h.windows = 0; h.sidecars = 0; h.toasts = []; h.notificationsSupported = true;
  for (const f of [h.quit, h.exit, h.relaunch, h.releaseLock]) f.mockReset();
  h.requestLock.mockReset().mockReturnValue(true);
  h.checkResult = { isUpdateAvailable: true, updateInfo: { version: '2.0.0' } };
  vi.useFakeTimers();
});
afterEach(() => { vi.useRealTimers(); });

describe('main.ts in --update-check mode', () => {
  it('creates no window and no recorder backend, notifies, and quits after the linger', async () => {
    await boot(['--update-check']);
    expect(h.appHandlers.has('window-all-closed')).toBe(false); // the normal startup block was skipped
    h.ready!();
    await vi.advanceTimersByTimeAsync(0);
    expect(h.windows).toBe(0);
    expect(h.sidecars).toBe(0);
    expect(h.toasts).toHaveLength(1);
    expect(h.toasts[0].opts.title).toBe('Force App 2.0.0 is available');
    expect(h.quit).not.toHaveBeenCalled(); // lingers so the toast can be clicked
    await vi.advanceTimersByTimeAsync(5 * 60_000);
    expect(h.quit).toHaveBeenCalled();
    expect(h.windows).toBe(0);
    expect(h.sidecars).toBe(0);
  });

  it('quits at once when there is no newer version, without a notification', async () => {
    h.checkResult = { isUpdateAvailable: false, updateInfo: { version: '1.0.0' } };
    await boot(['--update-check']);
    h.ready!();
    await vi.advanceTimersByTimeAsync(0);
    expect(h.toasts).toHaveLength(0);
    expect(h.quit).toHaveBeenCalled();
  });

  it('without notification support it quits and does not mark the version as told', async () => {
    h.notificationsSupported = false;
    await boot(['--update-check']);
    h.ready!();
    await vi.advanceTimersByTimeAsync(0);
    expect(h.toasts).toHaveLength(0);
    expect(h.quit).toHaveBeenCalled();
    const fs = await import('node:fs');
    const path = await import('node:path');
    expect(fs.existsSync(path.join(h.userData, 'update-notified.json'))).toBe(false);
  });

  it('exits immediately when the real app already holds the single-instance lock', async () => {
    h.requestLock.mockReturnValue(false);
    await boot(['--update-check']);
    expect(h.quit).toHaveBeenCalled();
    expect(h.ready).toBeNull();
    expect(h.windows).toBe(0);
  });

  it('clicking the notification starts the app normally, without the flag', async () => {
    await boot(['--update-check']);
    h.ready!();
    await vi.advanceTimersByTimeAsync(0);
    h.toasts[0].handlers.get('click')!();
    expect(h.releaseLock).toHaveBeenCalled();
    expect(h.relaunch).toHaveBeenCalledWith({ args: [] });
    expect(h.exit).toHaveBeenCalledWith(0);
  });

  it('a real launch while the check holds the lock hands over instead of silently doing nothing', async () => {
    await boot(['--update-check']);
    h.appHandlers.get('second-instance')!({}, ['Force App.exe']);
    expect(h.relaunch).toHaveBeenCalledWith({ args: [] });
  });

  it('does not take the lock like a real instance would: a normal launch still does', async () => {
    await boot([]);
    expect(h.requestLock).toHaveBeenCalledTimes(1);
    expect(h.appHandlers.has('window-all-closed')).toBe(true);
  });
});
