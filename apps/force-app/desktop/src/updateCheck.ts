// `--update-check` mode (#197): the scheduled task launches the installed exe with this flag while
// the app is closed. It checks the feed WITHOUT downloading, tells the operator if a newer version
// exists, and quits. No window, no recorder backend, nothing written but the "already told you
// about X" marker, so it can never interfere with a real launch.
import fs from 'node:fs';
import path from 'node:path';
import { availableNotification } from './updateNotify';

/** The check gives up after this long (offline, feed down). */
export const CHECK_TIMEOUT_MS = 60_000;
/** After a notification the process stays up this long, so clicking the toast can launch the app;
 * it is windowless and idle, and a real launch in the meantime takes over (see launchApp). */
export const LINGER_MS = 5 * 60_000;

export interface UpdateCheckDeps {
  isPackaged: boolean;
  /** Resolves to the newest version when it is newer than this one, else null. Never downloads. */
  checkForUpdate: () => Promise<string | null>;
  /** The version the operator was last told about (persisted between runs), or null. */
  lastNotified: () => string | null;
  markNotified: (version: string) => void;
  /** Shows the toast; `onClick` fires when it is clicked. Throws when it could not be shown (the
   * platform has no notifications, or creating it failed): the version is then not marked as told. */
  notify: (n: { title: string; body: string }, onClick: () => void) => void;
  /** Starts the app normally (no flag) and ends this process. */
  launchApp: () => void;
  quit: () => void;
  setTimer: (fn: () => void, ms: number) => unknown;
  clearTimer: (handle: unknown) => void;
}

export async function runUpdateCheck(d: UpdateCheckDeps): Promise<void> {
  if (!d.isPackaged) return d.quit();
  // Nothing may keep this windowless process alive for ever (a hung feed request).
  const giveUp = d.setTimer(() => d.quit(), CHECK_TIMEOUT_MS);
  let version: string | null = null;
  try {
    version = await d.checkForUpdate();
  } catch {
    version = null; // offline or feed down: try again at the next logon or tomorrow
  }
  // Told once per version, not at every logon and every day while it sits uninstalled.
  if (!version || d.lastNotified() === version) return d.quit();
  // The linger timer goes up BEFORE anything that can throw, and replaces the give-up timer: this
  // windowless process must end by itself whatever happens next (the /sc DAILY fallback task has no
  // execution time limit, schtasks /create has no flag for one, so it would otherwise live on
  // for the task's default 72 hours).
  d.clearTimer(giveUp);
  d.setTimer(() => d.quit(), LINGER_MS);
  try {
    d.notify(availableNotification(version), () => d.launchApp());
  } catch {
    // Could not tell the operator: leave the version unmarked so the next run tries again, and
    // there is nothing to wait for.
    return d.quit();
  }
  d.markNotified(version);
}

/** The "already told you about X" marker, in the app's userData folder. */
export function notifiedMarker(userDataDir: string): { read: () => string | null; write: (v: string) => void } {
  const file = path.join(userDataDir, 'update-notified.json');
  return {
    read: () => {
      try {
        const v = JSON.parse(fs.readFileSync(file, 'utf-8')).version;
        return typeof v === 'string' ? v : null;
      } catch {
        return null;
      }
    },
    write: (v) => {
      try {
        fs.mkdirSync(path.dirname(file), { recursive: true });
        fs.writeFileSync(file, JSON.stringify({ version: v }));
      } catch { /* worst case it tells the operator once more */ }
    },
  };
}
