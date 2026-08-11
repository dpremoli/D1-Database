import { execFile } from 'node:child_process';
import { dialog } from 'electron';

const TASK_NAME = 'ForceAppRecorderBackend';

export interface ScheduledTaskDeps {
  taskExists: () => Promise<boolean>;
  removeTask: () => Promise<void>;
  confirm: () => Promise<boolean>;
}

export function makeDefaultDeps(): ScheduledTaskDeps {
  return {
    taskExists: () =>
      new Promise((resolve) => {
        execFile('schtasks', ['/query', '/tn', TASK_NAME], (error) => resolve(!error));
      }),
    removeTask: () =>
      new Promise((resolve) => {
        execFile('schtasks', ['/delete', '/tn', TASK_NAME, '/f'], () => resolve());
      }),
    confirm: async () => {
      const { response } = await dialog.showMessageBox({
        type: 'question',
        buttons: ['Remove it', 'Leave it for now'],
        defaultId: 0,
        title: 'Old auto-start task found',
        message:
          `The scheduled task "${TASK_NAME}" starts the old recorder backend automatically. ` +
          'This app now manages the backend itself — leaving the old task running would let ' +
          'both compete for the same port. Remove it?',
      });
      return response === 0;
    },
  };
}

/** Offers to remove the pre-Electron auto-start task the first time it's found running. See
 * apps/force-app/backend/scripts/install_autostart.ps1 for what it does. */
export async function offerScheduledTaskCleanup(deps: ScheduledTaskDeps = makeDefaultDeps()): Promise<void> {
  if (!(await deps.taskExists())) return;
  if (await deps.confirm()) await deps.removeTask();
}
