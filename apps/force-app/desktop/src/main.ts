import { app, BrowserWindow } from 'electron';
import path from 'node:path';

function createWindow(): void {
  const win = new BrowserWindow({
    width: 1500,
    height: 950,
    webPreferences: { contextIsolation: true, nodeIntegration: false },
  });
  void win.loadFile(path.join(__dirname, '..', 'static', 'loading.html'));
}

app.whenReady().then(createWindow);

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') app.quit();
});
