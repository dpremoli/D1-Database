import { contextBridge, ipcRenderer } from 'electron';
import type { UpdateStatus } from './updater';

contextBridge.exposeInMainWorld('forceApp', {
  // Electron's window.confirm() opens a native OS dialog that Playwright's CDP-based dialog
  // interception cannot see or dismiss (unlike a plain Chromium page) — any confirm() gate in the
  // renderer hangs an automated test forever. Renderer code that gates on confirm() should check
  // this first and skip straight to the non-blocking outcome when true.
  testHooks: process.env.FORCE_APP_TEST_HOOKS === '1',
  onNavigate: (callback: (path: string) => void) => {
    ipcRenderer.on('navigate', (_event, targetPath: string) => callback(targetPath));
  },
  getUpdateInfo: (): Promise<{ version: string; packaged: boolean; status: UpdateStatus }> =>
    ipcRenderer.invoke('update:get-info'),
  checkForUpdates: (): Promise<{ ok: boolean; reason?: string }> => ipcRenderer.invoke('update:check'),
  installUpdate: (): Promise<{ ok: boolean; reason?: string }> => ipcRenderer.invoke('update:install'),
  onUpdateStatus: (callback: (status: UpdateStatus) => void) => {
    ipcRenderer.on('update:status', (_event, status: UpdateStatus) => callback(status));
  },
  /** Native folder picker; resolves to the chosen folder, or null if cancelled. */
  pickFolder: (defaultPath?: string): Promise<string | null> => ipcRenderer.invoke('dialog:pickFolder', defaultPath),
});
