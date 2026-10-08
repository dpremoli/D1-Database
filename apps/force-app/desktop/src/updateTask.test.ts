import { describe, expect, it, vi } from 'vitest';
import {
  UPDATE_TASK_NAME, applyUpdateTask, buildDailyCreateArgs, buildDeleteArgs, buildTaskXml, buildXmlCreateArgs,
  encodeTaskXml, type UpdateTaskDeps,
} from './updateTask';

const EXE = 'C:\\Users\\Lab Tech\\AppData\\Local\\Programs\\Force App\\Force App.exe';

describe('schtasks arguments', () => {
  it('the task name differs from the old auto-start task that scheduledTask.ts removes', () => {
    expect(UPDATE_TASK_NAME).not.toBe('ForceAppRecorderBackend');
  });

  it('daily fallback quotes an exe path containing spaces and passes the flag', () => {
    const args = buildDailyCreateArgs(EXE);
    expect(args[args.indexOf('/tr') + 1]).toBe(`"${EXE}" --update-check`);
    expect(args).toEqual(expect.arrayContaining(['/create', '/tn', UPDATE_TASK_NAME, '/sc', 'DAILY', '/f']));
  });

  it('delete is forced and by name; XML create points at the file', () => {
    expect(buildDeleteArgs()).toEqual(['/delete', '/tn', UPDATE_TASK_NAME, '/f']);
    expect(buildXmlCreateArgs('C:\\t\\x.xml')).toEqual(['/create', '/tn', UPDATE_TASK_NAME, '/xml', 'C:\\t\\x.xml', '/f']);
  });
});

describe('task XML', () => {
  const xml = buildTaskXml(EXE, 'LAB\\op&co');
  it('has a logon and a daily trigger, the exe unquoted in Command and the flag in Arguments', () => {
    expect(xml).toContain('<LogonTrigger>');
    expect(xml).toContain('<ScheduleByDay>');
    expect(xml).toContain(`<Command>${EXE}</Command>`);
    expect(xml).toContain('<Arguments>--update-check</Arguments>');
  });
  it('runs as the current user, unelevated, and escapes XML characters in the user', () => {
    expect(xml).toContain('<RunLevel>LeastPrivilege</RunLevel>');
    expect(xml).toContain('<UserId>LAB\\op&amp;co</UserId>');
  });
  it('is encoded as UTF-16LE with a byte-order mark, as schtasks requires', () => {
    const buf = encodeTaskXml('<a/>');
    expect([...buf.subarray(0, 2)]).toEqual([0xff, 0xfe]);
    expect(buf.subarray(2).toString('utf16le')).toBe('<a/>');
  });
});

function deps(over: Partial<UpdateTaskDeps> = {}, execImpl?: (args: string[]) => { ok: boolean; stdout?: string }) {
  const calls: string[][] = [];
  const cleanup = vi.fn();
  const d: UpdateTaskDeps = {
    supported: true,
    exePath: EXE,
    userId: 'LAB\\op',
    exec: async (args) => {
      calls.push(args);
      const r = execImpl?.(args) ?? { ok: true };
      return { ok: r.ok, stdout: r.stdout ?? '' };
    },
    writeXml: () => ({ file: 'C:\\tmp\\t.xml', cleanup }),
    ...over,
  };
  return { d, calls, cleanup };
}

describe('applyUpdateTask', () => {
  it('enabling a missing task creates it from the XML and removes the temp file', async () => {
    const { d, calls, cleanup } = deps({}, (a) => (a[0] === '/query' ? { ok: false } : { ok: true }));
    expect(await applyUpdateTask(true, d)).toEqual({ ok: true });
    expect(calls.map((c) => c[0])).toEqual(['/query', '/create']);
    expect(calls[1]).toContain('/xml');
    expect(cleanup).toHaveBeenCalled();
  });

  it('enabling when the task already points at this exe does nothing', async () => {
    const { d, calls } = deps({}, () => ({ ok: true, stdout: `<Command>${EXE}</Command>` }));
    expect(await applyUpdateTask(true, d)).toEqual({ ok: true });
    expect(calls).toHaveLength(1);
  });

  it('a task pointing at a moved exe is re-created', async () => {
    const { d, calls } = deps({}, (a) => (a[0] === '/query' ? { ok: true, stdout: '<Command>D:\\old\\Force App.exe</Command>' } : { ok: true }));
    await applyUpdateTask(true, d);
    expect(calls[1][0]).toBe('/create');
  });

  it('falls back to the daily-only task when the XML is refused, and reports failure if that fails too', async () => {
    const { d, calls } = deps({}, (a) => ({ ok: a[0] === '/create' && !a.includes('/xml') }));
    expect(await applyUpdateTask(true, d)).toEqual({ ok: true });
    expect(calls.at(-1)).toContain('DAILY');
    const bad = deps({}, (a) => ({ ok: a[0] !== '/create' && a[0] !== '/query' }));
    expect(await applyUpdateTask(true, bad.d)).toMatchObject({ ok: false, reason: expect.any(String) });
  });

  it('disabling deletes the task (even if it is already gone)', async () => {
    const { d, calls } = deps({}, () => ({ ok: false }));
    expect(await applyUpdateTask(false, d)).toEqual({ ok: true });
    expect(calls).toEqual([buildDeleteArgs()]);
  });

  it('is a no-op where unsupported (dev, non-Windows)', async () => {
    const { d, calls } = deps({ supported: false });
    expect(await applyUpdateTask(true, d)).toMatchObject({ ok: false });
    expect(await applyUpdateTask(false, d)).toMatchObject({ ok: false });
    expect(calls).toHaveLength(0);
  });
});
