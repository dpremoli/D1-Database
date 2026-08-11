import { contextBridge, ipcRenderer } from 'electron';

contextBridge.exposeInMainWorld('forceApp', {
  onNavigate: (callback: (path: string) => void) => {
    ipcRenderer.on('navigate', (_event, targetPath: string) => callback(targetPath));
  },
});
