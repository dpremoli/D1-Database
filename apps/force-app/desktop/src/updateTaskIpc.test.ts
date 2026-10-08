import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { describe, expect, it, vi } from 'vitest';
import type { UpdateTaskDeps } from './updateTask';
import { registerUpdateTaskIpc, syncUpdateTaskOnStartup, updateNotifyPref } from './updateTaskIpc';

const APP = { senderFrame: { url: 'app://force/settings/about' } };
const FOREIGN = { senderFrame: { url: 'https://evil.example/' } };
const isApp = (e: any) => String(e.senderFrame?.url).startsWith('app://force/');

function setup(taskExists = false, create = true) {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'force-prefs-'));
  const pref = updateNotifyPref(dir);
  const calls: string[][] = [];
  const deps: UpdateTaskDeps = {
    supported: true, exePath: 'C:\\A B\\Force App.exe', userId: 'u',
    exec: async (a) => {
      calls.push(a);
      if (a[0] === '/query') return { ok: taskExists, stdout: taskExists ? 'C:\\A B\\Force App.exe' : '' };
      if (a[0] === '/create') return { ok: create, stdout: '' };
      return { ok: true, stdout: '' };
    },
    writeXml: () => ({ file: 'f.xml', cleanup: () => {} }),
  };
  const handlers = new Map<string, (...a: any[]) => any>();
  registerUpdateTaskIpc({ handle: (c, f) => { handlers.set(c, f); } }, isApp, pref, deps);
  return { pref, deps, calls, handlers, dir };
}

describe('update-notify preference', () => {
  it('defaults to on, persists off, and survives a corrupt file', () => {
    const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'force-prefs-'));
    const p = updateNotifyPref(dir);
    expect(p.read()).toBe(true);
    p.write(false);
    expect(updateNotifyPref(dir).read()).toBe(false);
    fs.writeFileSync(path.join(dir, 'desktop-prefs.json'), '{nope');
    expect(p.read()).toBe(true);
  });
});

describe('updateNotify IPC', () => {
  it('get reports supported and the stored default (on)', async () => {
    const { handlers } = setup();
    expect(await handlers.get('updateNotify:get')!(APP)).toEqual({ supported: true, enabled: true });
  });

  it('set(false) removes the task and remembers off', async () => {
    const { handlers, calls, pref } = setup();
    expect(await handlers.get('updateNotify:set')!(APP, false)).toEqual({ ok: true, enabled: false });
    expect(calls[0][0]).toBe('/delete');
    expect(pref.read()).toBe(false);
  });

  it('set(true) creates the task and remembers on', async () => {
    const { handlers, calls, pref } = setup();
    pref.write(false);
    expect(await handlers.get('updateNotify:set')!(APP, true)).toEqual({ ok: true, enabled: true });
    expect(calls.some((c) => c[0] === '/create')).toBe(true);
    expect(pref.read()).toBe(true);
  });

  it('set(true) that Windows refuses is not remembered', async () => {
    const { handlers, pref } = setup(false, false);
    pref.write(false);
    const res = await handlers.get('updateNotify:set')!(APP, true);
    expect(res).toMatchObject({ ok: false, enabled: false });
    expect(pref.read()).toBe(false);
  });

  it('refuses other pages and non-boolean values', async () => {
    const { handlers, calls } = setup();
    expect(await handlers.get('updateNotify:set')!(FOREIGN, false)).toMatchObject({ ok: false });
    expect(await handlers.get('updateNotify:set')!(APP, 'yes')).toMatchObject({ ok: false });
    expect(await handlers.get('updateNotify:get')!(FOREIGN)).toEqual({ supported: false, enabled: false });
    expect(calls).toHaveLength(0);
  });
});

describe('syncUpdateTaskOnStartup', () => {
  it('creates a missing task when enabled', async () => {
    const { pref, deps, calls } = setup(false);
    await syncUpdateTaskOnStartup(pref, deps);
    expect(calls.map((c) => c[0])).toEqual(['/query', '/create']);
  });
  it('leaves an existing task alone', async () => {
    const { pref, deps, calls } = setup(true);
    await syncUpdateTaskOnStartup(pref, deps);
    expect(calls.map((c) => c[0])).toEqual(['/query']);
  });
  it('does nothing when the operator turned it off, or where unsupported', async () => {
    const off = setup(false);
    off.pref.write(false);
    await syncUpdateTaskOnStartup(off.pref, off.deps);
    expect(off.calls).toHaveLength(0);
    const dev = setup(false);
    await syncUpdateTaskOnStartup(dev.pref, { ...dev.deps, supported: false });
    expect(dev.calls).toHaveLength(0);
  });
  it('never throws', async () => {
    const { pref, deps } = setup();
    vi.spyOn(console, 'error').mockImplementation(() => {});
    await expect(syncUpdateTaskOnStartup(pref, { ...deps, exec: async () => { throw new Error('boom'); } })).resolves.toBeUndefined();
  });
});
