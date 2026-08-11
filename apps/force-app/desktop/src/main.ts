import { app, BrowserWindow, dialog, Menu } from 'electron';
import path from 'node:path';
import { ConfigStore } from './config';
import { buildMenu } from './menu';
import { findAvailablePort } from './port';
import { registerAppScheme, handleAppProtocol } from './protocol';
import { offerScheduledTaskCleanup } from './scheduledTask';
import { SidecarSupervisor, type SidecarState } from './sidecar';
import { initAutoUpdater } from './updater';
import { classifyWindowOpen } from './windowOpen';

const PREFERRED_PORT = 8200;
const HEALTH_PATH = '/health';

registerAppScheme();

let mainWindow: BrowserWindow | null = null;
let supervisor: SidecarSupervisor | null = null;
Menu.setApplicationMenu(buildMenu(() => mainWindow));

function webDistDir(): string {
  return app.isPackaged
    ? path.join(process.resourcesPath, 'web')
    : path.join(__dirname, '..', '..', 'web', 'dist');
}

function backendCommand(port: number): { exePath: string; args: string[]; cwd?: string } {
  if (app.isPackaged) {
    return {
      exePath: path.join(process.resourcesPath, 'backend', 'force-app-backend.exe'),
      args: ['--port', String(port)],
    };
  }
  // Dev mode: the same venv + uvicorn invocation apps/force-app/backend/scripts/start_recorder.ps1
  // uses, but bound to loopback only — the sidecar is reached solely by this app, on this machine.
  const backendDir = path.join(__dirname, '..', '..', 'backend');
  return {
    exePath: path.join(backendDir, '.venv', 'Scripts', 'python.exe'),
    args: ['-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', String(port)],
    cwd: backendDir,
  };
}

function onSidecarStateChange(state: SidecarState, detail?: string): void {
  if (state === 'crashed') {
    dialog.showErrorBox('Recorder backend stopped responding', detail ?? 'See logs for details.');
  }
  // A restart (not the initial start) means the backend crashed mid-session — route the
  // operator back to Record, where the existing recovery banner (RecordPage.vue) picks up any
  // incomplete session via GET /recovery/check on mount.
  if (state === 'ready' && supervisor && supervisor.getRestartCount() > 0) {
    mainWindow?.webContents.send('navigate', '/record');
  }
}

async function createWindow(): Promise<void> {
  const configStore = new ConfigStore(app.getPath('userData'));
  configStore.seedIfMissing();

  mainWindow = new BrowserWindow({
    width: 1500,
    height: 950,
    show: false,
    webPreferences: {
      contextIsolation: true,
      nodeIntegration: false,
      preload: path.join(__dirname, 'preload.js'),
    },
  });
  mainWindow.once('ready-to-show', () => mainWindow?.show());
  mainWindow.webContents.setWindowOpenHandler(classifyWindowOpen);

  handleAppProtocol(webDistDir(), configStore.path);
  await mainWindow.loadFile(path.join(__dirname, '..', 'static', 'loading.html'));

  const port = await findAvailablePort(PREFERRED_PORT);
  configStore.setRecorderPort(port);
  const cmd = backendCommand(port);

  supervisor = new SidecarSupervisor({
    exePath: cmd.exePath,
    args: cmd.args,
    cwd: cmd.cwd,
    port,
    healthUrl: `http://127.0.0.1:${port}${HEALTH_PATH}`,
    onStateChange: onSidecarStateChange,
  });
  await supervisor.start();

  if (supervisor.getState() !== 'ready') {
    dialog.showErrorBox(
      'Recorder backend failed to start',
      supervisor.lastDetail() ?? 'The backend did not become healthy in time.',
    );
    return;
  }

  await mainWindow.loadURL('app://force/');
  void offerScheduledTaskCleanup();
  initAutoUpdater();
}

export function getSupervisor(): SidecarSupervisor | null {
  return supervisor;
}

// Test-only: lets the Playwright smoke suite (tests/smoke.spec.ts) reach the supervisor through
// app.evaluate(), which has no access to this module's exports otherwise. Inert unless the test
// runner explicitly opts in via the env var.
if (process.env.FORCE_APP_TEST_HOOKS === '1') {
  (global as unknown as { __forceAppTestHooks: unknown }).__forceAppTestHooks = { getSupervisor };
}

app.whenReady().then(() => {
  void createWindow();
});

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') app.quit();
});

app.on('before-quit', (event) => {
  if (!supervisor || supervisor.getState() === 'stopped') return;
  event.preventDefault();
  void supervisor.stop().then(() => app.quit());
});
