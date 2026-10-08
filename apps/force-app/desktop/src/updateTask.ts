// The Windows scheduled task that checks for updates while the app is closed (#197). It runs the
// installed exe with --update-check at logon and daily; main.ts handles that mode without a
// window, a recorder backend or the single-instance lock (see updateCheck.ts).
//
// Not the old auto-start task (scheduledTask.ts removes "ForceAppRecorderBackend"): that one
// started a second recorder backend that fought the app for port 8200. This one never starts a
// backend and never downloads anything; it only tells the operator an update exists.
import { execFile } from 'node:child_process';
import { UPDATE_CHECK_FLAG } from './updateNotify';

export const UPDATE_TASK_NAME = 'ForceAppUpdateCheck';

export interface ExecResult { ok: boolean; stdout: string }
export type Exec = (args: string[]) => Promise<ExecResult>;

/** Runs schtasks with no console window; never rejects. */
export const runSchtasks: Exec = (args) =>
  new Promise((resolve) => {
    execFile('schtasks', args, { windowsHide: true }, (error, stdout) => resolve({ ok: !error, stdout: String(stdout ?? '') }));
  });

function xmlEscape(s: string): string {
  return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&apos;');
}

/** Task definition with both triggers (logon and daily). schtasks' plain /create takes one
 * schedule only, and /sc ONLOGON needs elevation; a logon trigger scoped to the current user in
 * an XML definition does not. Runs as that user, unelevated, only when the network is up, and
 * catches up a missed daily run (StartWhenAvailable). */
export function buildTaskXml(exePath: string, userId: string): string {
  const user = xmlEscape(userId);
  return `<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo><Description>Tells you when a new Force App version is available while the app is closed. Turn off in Settings &gt; About.</Description></RegistrationInfo>
  <Triggers>
    <LogonTrigger><Enabled>true</Enabled><UserId>${user}</UserId><Delay>PT2M</Delay></LogonTrigger>
    <CalendarTrigger><StartBoundary>2000-01-01T12:00:00</StartBoundary><Enabled>true</Enabled><ScheduleByDay><DaysInterval>1</DaysInterval></ScheduleByDay></CalendarTrigger>
  </Triggers>
  <Principals><Principal id="Author"><UserId>${user}</UserId><LogonType>InteractiveToken</LogonType><RunLevel>LeastPrivilege</RunLevel></Principal></Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <StartWhenAvailable>true</StartWhenAvailable>
    <RunOnlyIfNetworkAvailable>true</RunOnlyIfNetworkAvailable>
    <ExecutionTimeLimit>PT15M</ExecutionTimeLimit>
    <Enabled>true</Enabled>
  </Settings>
  <Actions Context="Author"><Exec><Command>${xmlEscape(exePath)}</Command><Arguments>${UPDATE_CHECK_FLAG}</Arguments></Exec></Actions>
</Task>
`;
}

/** schtasks reads an XML file as UTF-16 with a byte-order mark. */
export function encodeTaskXml(xml: string): Buffer {
  return Buffer.concat([Buffer.from([0xff, 0xfe]), Buffer.from(xml, 'utf16le')]);
}

/** Fallback when the XML definition is refused: daily only. The exe path is quoted (Program Files
 * and per-user install folders contain spaces); Node adds the outer quoting and escapes these. */
export function buildDailyCreateArgs(exePath: string): string[] {
  return ['/create', '/tn', UPDATE_TASK_NAME, '/tr', `"${exePath}" ${UPDATE_CHECK_FLAG}`, '/sc', 'DAILY', '/st', '12:00', '/f'];
}
export function buildXmlCreateArgs(xmlFile: string): string[] {
  return ['/create', '/tn', UPDATE_TASK_NAME, '/xml', xmlFile, '/f'];
}
export const buildDeleteArgs = (): string[] => ['/delete', '/tn', UPDATE_TASK_NAME, '/f'];
export const buildQueryXmlArgs = (): string[] => ['/query', '/tn', UPDATE_TASK_NAME, '/xml'];

export interface UpdateTaskDeps {
  /** Only a packaged Windows install gets the task; dev runs and other platforms never do. */
  supported: boolean;
  exePath: string;
  userId: string;
  exec: Exec;
  /** Writes the XML where schtasks can read it; resolves to the path, and `cleanup` removes it. */
  writeXml: (data: Buffer) => { file: string; cleanup: () => void };
}

export interface TaskResult { ok: boolean; reason?: string }

/** Is the task registered and pointing at this exe? A moved install folder leaves a task that
 * launches nothing, so a mismatch counts as missing. */
async function taskIsCurrent(deps: UpdateTaskDeps): Promise<boolean> {
  const res = await deps.exec(buildQueryXmlArgs());
  return res.ok && (res.stdout.includes(xmlEscape(deps.exePath)) || res.stdout.includes(deps.exePath));
}

async function createTask(deps: UpdateTaskDeps): Promise<TaskResult> {
  const { file, cleanup } = deps.writeXml(encodeTaskXml(buildTaskXml(deps.exePath, deps.userId)));
  try {
    if ((await deps.exec(buildXmlCreateArgs(file))).ok) return { ok: true };
  } finally {
    cleanup();
  }
  if ((await deps.exec(buildDailyCreateArgs(deps.exePath))).ok) return { ok: true };
  return { ok: false, reason: 'Windows refused to create the scheduled task' };
}

/** Makes the task exist (enabled) or not (disabled). Idempotent: enabling re-creates only a
 * missing or stale task, disabling deletes whatever is there. */
export async function applyUpdateTask(enabled: boolean, deps: UpdateTaskDeps): Promise<TaskResult> {
  if (!deps.supported) return { ok: false, reason: 'only available in the installed Windows app' };
  if (enabled) return (await taskIsCurrent(deps)) ? { ok: true } : createTask(deps);
  await deps.exec(buildDeleteArgs()); // "not found" is as good as deleted
  return { ok: true };
}
