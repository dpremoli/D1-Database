// Pure decisions behind the OS notifications about updates (#197). No Electron here, so they are
// unit-tested without a window.

/** Must equal electron-builder.yml `appId`: Windows only shows a toast for an app whose
 * AppUserModelID matches its Start-menu shortcut, and electron-builder stamps the shortcut with
 * the appId. updateNotify.test.ts checks the two stay equal. */
export const APP_USER_MODEL_ID = 'net.tailscale.d1-server.force-app';

/** Flag the scheduled task passes: check for an update, tell the operator, and quit. */
export const UPDATE_CHECK_FLAG = '--update-check';

export function isUpdateCheckArgv(argv: readonly string[]): boolean {
  return argv.includes(UPDATE_CHECK_FLAG);
}

export interface ReadyNotifyInput {
  version: string;
  /** The last version a notification was shown for in this run of the app. */
  notifiedVersion: string | null;
  /** There is a main window at all. Without one the native dialog is the fallback. */
  hasWindow: boolean;
  /** The window has focus. False also covers minimised, hidden and behind another window. */
  focused: boolean;
}

/** Should "update ready" be shown as an OS notification now? Only when the operator is not
 * looking at the in-app card (window not focused), once per version. */
export function shouldNotifyReady(i: ReadyNotifyInput): boolean {
  return i.hasWindow && !i.focused && i.notifiedVersion !== i.version;
}

export function readyNotification(version: string): { title: string; body: string } {
  return {
    title: `Force App ${version} is ready to install`,
    body: 'Open the app and choose Restart and install when you are not recording.',
  };
}

export function availableNotification(version: string): { title: string; body: string } {
  return {
    title: `Force App ${version} is available`,
    body: 'Open the app to update.',
  };
}
