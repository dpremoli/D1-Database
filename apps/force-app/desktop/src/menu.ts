import { Menu } from 'electron';

/** What the Help menu does beyond navigating the renderer. Supplied by main.ts, which owns the
 * updater and the backend; passed in so this stays testable without either. */
export interface MenuActions {
  /** Help > Check for updates. */
  checkForUpdates?: () => void;
  /** Help > Open captures folder. */
  openCapturesFolder?: () => void;
}

export function buildMenu(getWindow: () => Electron.BrowserWindow | null, actions: MenuActions = {}): Electron.Menu {
  const navigate = (route: string) => () => {
    getWindow()?.webContents.send('navigate', route);
  };
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
          click: navigate('/settings?tab=connectivity'),
        },
        {
          // The sidecar crash dialog tells the operator to "see logs for details"; this is how
          // they get there without hunting through AppData.
          label: 'View Logs',
          accelerator: 'CmdOrCtrl+Shift+L',
          click: navigate('/settings?tab=logs'),
        },
        { type: 'separator' },
        {
          label: 'Report a Bug…',
          accelerator: 'CmdOrCtrl+Shift+B',
          click: navigate('/settings?tab=report-bug'),
        },
        {
          label: 'Open Captures Folder',
          accelerator: 'CmdOrCtrl+Shift+O',
          click: () => actions.openCapturesFolder?.(),
        },
        { type: 'separator' },
        {
          // Shows the About tab too, where the check's progress and result are displayed.
          label: 'Check for Updates…',
          click: () => {
            navigate('/settings?tab=about')();
            actions.checkForUpdates?.();
          },
        },
        {
          label: 'About Force App',
          click: navigate('/settings?tab=about'),
        },
      ],
    },
  ]);
}
