import { describe, expect, it, vi } from 'vitest';
import { restartDecision, restartRecorder, type RestartDeps } from './restart';
import type { BusySession } from './quitGuard';

const recording: BusySession = { kind: 'recording', sample: 'S-1', elapsed: 30, samples: 100 };
const finalizing: BusySession = { kind: 'finalizing', sample: 'S-1', elapsed: 30, samples: 100 };

describe('restartDecision', () => {
  it('allows a restart when nothing is running (or the backend could not be asked)', () => {
    expect(restartDecision(null)).toEqual({ ok: true });
  });
  it('refuses while recording, naming the sample', () => {
    const r = restartDecision(recording);
    expect(r.ok).toBe(false);
    expect(r.reason).toContain('S-1');
    expect(r.reason).toContain('in progress');
  });
  it('refuses while finalizing', () => {
    const r = restartDecision(finalizing);
    expect(r.ok).toBe(false);
    expect(r.reason).toContain('being saved');
  });
});

function deps(over: Partial<RestartDeps> = {}): RestartDeps {
  return {
    getBusy: async () => null,
    restart: vi.fn(async () => {}),
    getState: () => 'ready',
    lastDetail: () => undefined,
    ...over,
  };
}

describe('restartRecorder', () => {
  it('restarts and reports ok once the supervisor is ready', async () => {
    const d = deps();
    expect(await restartRecorder(d)).toEqual({ ok: true });
    expect(d.restart).toHaveBeenCalledOnce();
  });
  it('does not restart while recording', async () => {
    const d = deps({ getBusy: async () => recording });
    const r = await restartRecorder(d);
    expect(r.ok).toBe(false);
    expect(d.restart).not.toHaveBeenCalled();
  });
  it('reports the supervisor detail when the backend does not come back', async () => {
    const r = await restartRecorder(deps({ getState: () => 'crashed', lastDetail: () => 'boom' }));
    expect(r).toEqual({ ok: false, reason: 'boom' });
  });
  it('reports a thrown error instead of throwing', async () => {
    const r = await restartRecorder(deps({ restart: async () => { throw new Error('nope'); } }));
    expect(r).toEqual({ ok: false, reason: 'nope' });
  });
  it('says so when there is no supervisor', async () => {
    const r = await restartRecorder(deps({ restart: null }));
    expect(r.ok).toBe(false);
  });
});
