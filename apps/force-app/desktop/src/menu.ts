import { Menu } from 'electron';

export function buildMenu(getWindow: () => Electron.BrowserWindow | null): Electron.Menu {
  return Menu.buildFromTemplate([
    {
      label: 'View',
      submenu: [{ role: 'reload' }, { role: 'toggleDevTools' }],
    },
    {
      label: 'Help',
      submenu: [
        {
          label: 'Connectivity Doctor',
          click: () => {
            getWindow()?.webContents.send('navigate', '/settings?tab=connectivity');
          },
        },
        {
          // The sidecar crash dialog tells the operator to "see logs for details"; this is how
          // they get there without hunting through AppData.
          label: 'View Logs',
          click: () => {
            getWindow()?.webContents.send('navigate', '/settings?tab=logs');
          },
        },
      ],
    },
  ]);
}
