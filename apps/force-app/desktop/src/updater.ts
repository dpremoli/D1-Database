import { app, dialog } from 'electron';
import { autoUpdater } from 'electron-updater';

/** electron-updater needs a real packaged app with publish config to do anything meaningful —
 * calling it in dev throws on the missing dev-update-config.yml, so this is a no-op there. */
export function initAutoUpdater(): void {
  if (!app.isPackaged) return;

  autoUpdater.autoDownload = true;
  autoUpdater.on('update-downloaded', () => {
    void dialog
      .showMessageBox({
        type: 'info',
        buttons: ['Restart now', 'Later'],
        defaultId: 0,
        title: 'Update ready',
        message: 'An update has been downloaded. Restart to apply it?',
      })
      .then(({ response }) => {
        if (response === 0) autoUpdater.quitAndInstall();
      });
  });
  autoUpdater.on('error', (err) => {
    console.error('autoUpdater error', err);
  });
  autoUpdater.checkForUpdates().catch((err) => console.error('checkForUpdates failed', err));
}
