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
    console.error('autoUpdater error', err);
  });
  autoUpdater.checkForUpdates().catch((err) => console.error('checkForUpdates failed', err));
}
