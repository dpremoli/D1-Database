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
      ],
    },
  ]);
}
