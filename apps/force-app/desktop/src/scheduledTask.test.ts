import { describe, it, expect, vi } from 'vitest';
import { offerScheduledTaskCleanup, type ScheduledTaskDeps } from './scheduledTask';

describe('offerScheduledTaskCleanup', () => {
  it('does nothing when the old task is not present', async () => {
    const deps: ScheduledTaskDeps = {
      taskExists: vi.fn().mockResolvedValue(false),
      removeTask: vi.fn().mockResolvedValue(undefined),
      confirm: vi.fn().mockResolvedValue(true),
    };
    await offerScheduledTaskCleanup(deps);
    expect(deps.confirm).not.toHaveBeenCalled();
    expect(deps.removeTask).not.toHaveBeenCalled();
  });

  it('removes the task when the user confirms', async () => {
    const deps: ScheduledTaskDeps = {
      taskExists: vi.fn().mockResolvedValue(true),
      removeTask: vi.fn().mockResolvedValue(undefined),
      confirm: vi.fn().mockResolvedValue(true),
    };
    await offerScheduledTaskCleanup(deps);
    expect(deps.removeTask).toHaveBeenCalledOnce();
  });

  it('leaves the task in place when the user declines', async () => {
    const deps: ScheduledTaskDeps = {
      taskExists: vi.fn().mockResolvedValue(true),
      removeTask: vi.fn().mockResolvedValue(undefined),
      confirm: vi.fn().mockResolvedValue(false),
    };
    await offerScheduledTaskCleanup(deps);
    expect(deps.removeTask).not.toHaveBeenCalled();
  });
});
