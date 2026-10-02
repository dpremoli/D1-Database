import { shell } from 'electron';
import type { WindowStateStore } from './windowState';

/** Stable key for remembering a pop-out's size/position: the pathname only, so every "Live Force"
 * pop-out (any mode/axes) shares one remembered geometry rather than one per query-string variant. */
export function popoutKey(url: string): string {
  return new URL(url).pathname;
}

/** Is this one of the app's own pages (app://force/...)? Used to vet window.open() targets, which
 * renderer an IPC request came from, and which saved pop-out URLs may be reopened at startup. */
export function isAppUrl(raw: string): boolean {
  try {
    const url = new URL(raw);
    return url.protocol === 'app:' && url.hostname === 'force';
  } catch {
    return false;
  }
}

export function classifyWindowOpen(
  details: Electron.HandlerDetails,
  windowState?: WindowStateStore,
): Electron.WindowOpenHandlerResponse {
  let url: URL;
  try {
    url = new URL(details.url);
  } catch {
    return { action: 'deny' };
  }
  if (isAppUrl(details.url)) {
    const saved = windowState?.get(popoutKey(details.url));
    return {
      action: 'allow',
      overrideBrowserWindowOptions: {
        // Omitted (not just undefined) when nothing is saved yet — Electron then falls back to
        // whatever width/height the window.open() features string requested, its own existing
        // default. Setting these keys to undefined would still override that fallback with NaN.
        ...(saved ? { x: saved.x, y: saved.y, width: saved.width, height: saved.height } : {}),
        webPreferences: { contextIsolation: true, nodeIntegration: false },
      },
    };
  }
  if (url.protocol === 'http:' || url.protocol === 'https:') {
    void shell.openExternal(details.url);
  }
  return { action: 'deny' };
}
