import { shell } from 'electron';

export function classifyWindowOpen(
  details: Electron.HandlerDetails,
): Electron.WindowOpenHandlerResponse {
  let url: URL;
  try {
    url = new URL(details.url);
  } catch {
    return { action: 'deny' };
  }
  if (url.protocol === 'app:' && url.hostname === 'force') {
    return {
      action: 'allow',
      overrideBrowserWindowOptions: {
        webPreferences: { contextIsolation: true, nodeIntegration: false },
      },
    };
  }
  if (url.protocol === 'http:' || url.protocol === 'https:') {
    void shell.openExternal(details.url);
  }
  return { action: 'deny' };
}
