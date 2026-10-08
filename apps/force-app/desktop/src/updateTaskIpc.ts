// Settings > About's "Notify me about updates when the app is closed" (#197): the preference, the
// IPC the renderer toggles it through, and the startup sync that creates the scheduled task.
import { execFile } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { applyUpdateTask, type UpdateTaskDeps } from './updateTask';

/** `<userData>/desktop-prefs.json`. Absent or unreadable means the default: on. (Not config.json:
 * that file is served to the renderer as the runtime config.) */
export function updateNotifyPref(userDataDir: string): { read: () => boolean; write: (enabled: boolean) => void } {
  const file = path.join(userDataDir, 'desktop-prefs.json');
  const readAll = (): Record<string, unknown> => {
    try {
      const v = JSON.parse(fs.readFileSync(file, 'utf-8'));
      return v && typeof v === 'object' ? v : {};
    } catch {
      return {};
    }
  };
  return {
    read: () => readAll().notifyUpdatesWhenClosed !== false,
    write: (enabled) => {
      fs.mkdirSync(path.dirname(file), { recursive: true });
      fs.writeFileSync(file, JSON.stringify({ ...readAll(), notifyUpdatesWhenClosed: enabled }, null, 2));
    },
  };
}

/** The real schtasks / file plumbing. Only a packaged Windows install is `supported`. */
export function makeUpdateTaskDeps(opts: { packaged: boolean; exePath: string }): UpdateTaskDeps {
  const user = process.env.USERNAME ?? os.userInfo().username;
  return {
    supported: process.platform === 'win32' && opts.packaged,
    exePath: opts.exePath,
    userId: process.env.USERDOMAIN ? `${process.env.USERDOMAIN}\\${user}` : user,
    exec: (args) =>
      new Promise((resolve) => {
        execFile('schtasks', args, { windowsHide: true }, (error, stdout) => resolve({ ok: !error, stdout: String(stdout ?? '') }));
      }),
    writeXml: (data) => {
      const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'force-app-task-'));
      const file = path.join(dir, 'update-check.xml');
      fs.writeFileSync(file, data);
      return { file, cleanup: () => fs.rmSync(dir, { recursive: true, force: true }) };
    },
  };
}

interface IpcLike { handle: (channel: string, fn: (event: any, ...args: any[]) => unknown) => void }

/** `updateNotify:get` -> { supported, enabled }; `updateNotify:set` (enabled) -> { ok, enabled, reason? }.
 * Same sender check as the other shell IPC: only the app's own pages. Turning it on is only
 * remembered if the task could really be created; turning it off always is. */
export function registerUpdateTaskIpc(
  ipc: IpcLike,
  isApp: (event: unknown) => boolean,
  pref: ReturnType<typeof updateNotifyPref>,
  deps: UpdateTaskDeps,
): void {
  ipc.handle('updateNotify:get', (event) =>
    isApp(event) ? { supported: deps.supported, enabled: pref.read() } : { supported: false, enabled: false });
  ipc.handle('updateNotify:set', async (event, enabled: unknown) => {
    if (!isApp(event)) return { ok: false, enabled: pref.read(), reason: 'not allowed from this page' };
    if (typeof enabled !== 'boolean') return { ok: false, enabled: pref.read(), reason: 'invalid value' };
    const res = await applyUpdateTask(enabled, deps);
    if (enabled && !res.ok) return { ok: false, enabled: pref.read(), reason: res.reason };
    pref.write(enabled);
    return { ok: true, enabled };
  });
}

/** At startup: enabled (the default) and the task missing or stale -> create it. Never throws. */
export async function syncUpdateTaskOnStartup(pref: ReturnType<typeof updateNotifyPref>, deps: UpdateTaskDeps): Promise<void> {
  if (!deps.supported || !pref.read()) return;
  try {
    await applyUpdateTask(true, deps);
  } catch (err) {
    console.error('could not sync the update-check task', err);
  }
}
