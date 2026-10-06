// "Restart recorder" (R11): the decision and the sequence, kept out of main.ts (which needs a
// running Electron) so they can be unit tested.
import type { BusySession } from './quitGuard';
import type { SidecarState } from './sidecar';

export interface RestartResult {
  ok: boolean;
  reason?: string;
}

/** May the backend be restarted given what it last reported? A recording, or a stopped one still
 * being written, blocks it: a restart kills the process and leaves the cut's files unwritten.
 * `busy` is null when nothing is running OR the backend could not be asked; the second is allowed
 * on purpose, because an unreachable backend is exactly the case the button exists for. */
export function restartDecision(busy: BusySession | null): RestartResult {
  if (!busy) return { ok: true };
  return {
    ok: false,
    reason:
      busy.kind === 'finalizing'
        ? `A recording of ${busy.sample} is still being saved. Wait for it to finish, then restart.`
        : `A recording of ${busy.sample} is in progress. Stop it first; restarting the recorder would end it.`,
  };
}

export interface RestartDeps {
  /** GET /record/status, as the quit guard reads it. */
  getBusy: () => Promise<BusySession | null>;
  /** supervisor.restart(), or null when there is no supervisor yet. */
  restart: (() => Promise<void>) | null;
  getState: () => SidecarState | undefined;
  lastDetail: () => string | undefined;
}

/** Checks, restarts, and reports whether the backend came back. Never throws. */
export async function restartRecorder(deps: RestartDeps): Promise<RestartResult> {
  if (!deps.restart) return { ok: false, reason: 'The recorder has not been started yet.' };
  const decision = restartDecision(await deps.getBusy());
  if (!decision.ok) return decision;
  try {
    await deps.restart();
  } catch (err) {
    return { ok: false, reason: err instanceof Error ? err.message : String(err) };
  }
  if (deps.getState() === 'ready') return { ok: true };
  return { ok: false, reason: deps.lastDetail() ?? 'The recorder did not start. See Settings > Logs.' };
}
