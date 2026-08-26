import { contextBridge, ipcRenderer } from 'electron';
import type { UpdateStatus } from './updater';

contextBridge.exposeInMainWorld('forceApp', {
  onNavigate: (callback: (path: string) => void) => {
    ipcRenderer.on('navigate', (_event, targetPath: string) => callback(targetPath));
  },
  getUpdateInfo: (): Promise<{ version: string; packaged: boolean; status: UpdateStatus }> =>
    ipcRenderer.invoke('update:get-info'),
  checkForUpdates: (): Promise<{ ok: boolean; reason?: string }> => ipcRenderer.invoke('update:check'),
  onUpdateStatus: (callback: (status: UpdateStatus) => void) => {
    ipcRenderer.on('update:status', (_event, status: UpdateStatus) => callback(status));
  },
});
