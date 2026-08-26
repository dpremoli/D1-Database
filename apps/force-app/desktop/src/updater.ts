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
let getRecorderPort: (() => number | null) | null = null;

function push(next: UpdateStatus): void {
  status = next;
  getWindow?.()?.webContents.send('update:status', status);
}

// The main process has no visibility into the renderer's recording state — the workspace store
// that tracks it lives (and dies) with the Record page's component, not as a persistent main-side
// signal. Asking the backend directly via the same /record/status the UI itself polls sidesteps
// that entirely: it's authoritative regardless of which page is open or whether Record has ever
// been mounted this session.
async function isRecording(): Promise<boolean> {
  const port = getRecorderPort?.();
  if (!port) return false;
  try {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 3000);
    const res = await fetch(`http://127.0.0.1:${port}/record/status`, { signal: controller.signal });
    clearTimeout(timeout);
    if (!res.ok) return false;
    const data = (await res.json()) as { state?: string };
    return data.state === 'recording';
  } catch {
    return false;   // fail-open: a transient check failure must not wedge the prompt forever
  }
}

function showUpdateDialog(version: string): void {
  void dialog
    .showMessageBox({
      type: 'info',
      buttons: ['Update now', 'Not now'],
      defaultId: 0,
      title: 'Update ready',
      message: `Version ${version} has been downloaded and is ready to install.`,
      detail: 'Choose "Not now" to keep working on the current version — you can install it anytime from Settings > About.',
    })
    .then(({ response }) => {
      // (isSilent, isForceRunAfter). Both matter. The default is a NON-silent install, which
      // launches the full NSIS wizard — the operator answers "Update now" and is then made to
      // click through a setup wizard, which is not what that button promises. Silent skips it;
      // isForceRunAfter brings the app back up afterwards, since a silent NSIS run does not
      // relaunch on its own and the operator would otherwise be left staring at a closed app.
      // Safe here because the installer is perMachine: false — a per-user install needs no
      // elevation, so there is no UAC prompt hiding behind the silent flag.
      if (response === 0) autoUpdater.quitAndInstall(true, true);
    });
}

// Set once a downloaded update is deferred because a cut was running when it finished; re-checked
// on a slow poll rather than wired to a push event, since nothing pushes "recording just stopped"
// to the main process either.
let pendingVersion: string | null = null;
let recheckTimer: ReturnType<typeof setInterval> | null = null;

async function offerUpdate(version: string): Promise<void> {
  if (await isRecording()) {
    pendingVersion = version;
    if (!recheckTimer) {
      recheckTimer = setInterval(async () => {
        if (pendingVersion && !(await isRecording())) {
          if (recheckTimer) clearInterval(recheckTimer);
          recheckTimer = null;
          const v = pendingVersion;
          pendingVersion = null;
          showUpdateDialog(v);
        }
      }, 60_000);
    }
    return;
  }
  showUpdateDialog(version);
}

/** electron-updater needs a real packaged app with publish config to do anything meaningful —
 * calling it in dev throws on the missing dev-update-config.yml, so this is a no-op there. The
 * IPC handlers stay registered either way so the Settings UI can show "dev build" instead of
 * hanging on a renderer call that never resolves. */
export function initAutoUpdater(getMainWindow: () => BrowserWindow | null, getPort: () => number | null): void {
  getWindow = getMainWindow;
  getRecorderPort = getPort;

  ipcMain.handle('update:get-info', () => ({ version: app.getVersion(), packaged: app.isPackaged, status }));
  ipcMain.handle('update:check', () => {
    if (!app.isPackaged) return { ok: false, reason: 'not a packaged build' };
    autoUpdater.checkForUpdates().catch((err) => push({ state: 'error', message: err?.message || String(err) }));
    return { ok: true };
  });
  // Same guard as the automatic prompt — a manual click from Settings must not be able to force
  // a restart mid-cut either. Re-checks live rather than trusting offerUpdate()'s earlier read,
  // since recording could have started in between.
  ipcMain.handle('update:install', async () => {
    if (status.state !== 'downloaded') return { ok: false, reason: 'no update downloaded yet' };
    if (await isRecording()) return { ok: false, reason: 'a recording is in progress — try again once it finishes' };
    autoUpdater.quitAndInstall(true, true);
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
    void offerUpdate(info.version);
  });
  autoUpdater.on('error', (err) => {
    push({ state: 'error', message: err?.message || String(err) });
    console.error('autoUpdater error', err);
  });

  autoUpdater.checkForUpdates().catch((err) => push({ state: 'error', message: err?.message || String(err) }));
}
