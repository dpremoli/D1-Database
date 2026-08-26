import { app, dialog, ipcMain, type BrowserWindow } from 'electron';
import { autoUpdater } from 'electron-updater';

export type UpdateStatus =
  | { state: 'idle' }
  | { state: 'checking' }
  | { state: 'available'; version: string }
  | { state: 'not-available' }
  | { state: 'downloading'; percent: number }
  | { state: 'downloaded'; version: string }
  | { state: 'error'; message: string };

let status: UpdateStatus = { state: 'idle' };
let getWindow: (() => BrowserWindow | null) | null = null;

function push(next: UpdateStatus): void {
  status = next;
  getWindow?.()?.webContents.send('update:status', status);
}

/** electron-updater needs a real packaged app with publish config to do anything meaningful —
 * calling it in dev throws on the missing dev-update-config.yml, so this is a no-op there. The
 * IPC handlers stay registered either way so the Settings UI can show "dev build" instead of
 * hanging on a renderer call that never resolves. */
export function initAutoUpdater(getMainWindow: () => BrowserWindow | null): void {
  getWindow = getMainWindow;

  ipcMain.handle('update:get-info', () => ({ version: app.getVersion(), packaged: app.isPackaged, status }));
  ipcMain.handle('update:check', () => {
    if (!app.isPackaged) return { ok: false, reason: 'not a packaged build' };
    autoUpdater.checkForUpdates().catch((err) => push({ state: 'error', message: err?.message || String(err) }));
    return { ok: true };
  });

  if (!app.isPackaged) return;

  autoUpdater.autoDownload = true;
  autoUpdater.on('checking-for-update', () => push({ state: 'checking' }));
  autoUpdater.on('update-available', (info) => push({ state: 'available', version: info.version }));
  autoUpdater.on('update-not-available', () => push({ state: 'not-available' }));
  autoUpdater.on('download-progress', (p) => push({ state: 'downloading', percent: Math.round(p.percent) }));
  autoUpdater.on('update-downloaded', (info) => {
    push({ state: 'downloaded', version: info.version });
    void dialog
      .showMessageBox({
        type: 'info',
        buttons: ['Restart now', 'Later'],
        defaultId: 0,
        title: 'Update ready',
        message: 'An update has been downloaded. Restart to apply it?',
      })
      .then(({ response }) => {
        // (isSilent, isForceRunAfter). Both matter. The default is a NON-silent install, which
        // launches the full NSIS wizard — the operator answers "Restart now" and is then made to
        // click through a setup wizard, which is not what that button promises. Silent skips it;
        // isForceRunAfter brings the app back up afterwards, since a silent NSIS run does not
        // relaunch on its own and the operator would otherwise be left staring at a closed app.
        // Safe here because the installer is perMachine: false — a per-user install needs no
        // elevation, so there is no UAC prompt hiding behind the silent flag.
        if (response === 0) autoUpdater.quitAndInstall(true, true);
      });
  });
  autoUpdater.on('error', (err) => {
    push({ state: 'error', message: err?.message || String(err) });
    console.error('autoUpdater error', err);
  });

  autoUpdater.checkForUpdates().catch((err) => push({ state: 'error', message: err?.message || String(err) }));
}
