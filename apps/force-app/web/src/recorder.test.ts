import { describe, expect, it, vi } from 'vitest';

const state = vi.hoisted(() => ({ user: null as any, offline: false, accessToken: null as string | null, refreshToken: null as string | null }));
vi.mock('./authStore', () => ({ authStore: { state } }));

import {
  currentRecorder, hasServerSession, ownerPersonId, preservedRecorderKeys, recorderFields, recorderFromExtra, syncerFields,
} from './recorder';

describe('recorder stamp', () => {
  it('round-trips through extra_metadata', () => {
    state.user = { id: 'u1', email: 'a@b.c', first_name: 'Ada', last_name: 'L', person_id: 'p1' };
    const r = currentRecorder();
    const extra = recorderFields(r, '2026-09-30T10:00:00.000Z');
    expect(recorderFromExtra(extra)).toEqual({ userId: 'u1', email: 'a@b.c', name: 'Ada L', personId: 'p1', offline: false });
    expect(extra.recorded_at).toBe('2026-09-30T10:00:00.000Z');
  });

  it('records that the user was signed in offline', () => {
    state.user = { id: 'u1' };
    state.offline = true;
    expect(recorderFromExtra(recorderFields(currentRecorder(), 't'))?.offline).toBe(true);
    state.offline = false;
  });

  it('owner is the recorder person, never the current user', () => {
    state.user = { id: 'someone-else', person_id: 'p-other' };
    expect(ownerPersonId({ recorded_by_user_id: 'u1', recorded_by_person_id: 'p1' })).toBe('p1');
    // No stamp (capture from before this existed) or no person: leave it to the server default.
    expect(ownerPersonId({})).toBeUndefined();
    expect(ownerPersonId({ recorded_by_user_id: 'u1' })).toBeUndefined();
  });

  it('an unidentified session stamps only the time', () => {
    state.user = null;
    expect(recorderFields(currentRecorder(), 't')).toEqual({ recorded_at: 't' });
    expect(recorderFromExtra({ recorded_at: 't' })).toBeNull();
  });

  it('editors can carry the recorder keys through a rewrite', () => {
    expect(preservedRecorderKeys({ notes: 'x', recorded_by_user_id: 'u1', recorded_at: 't', link_sample_id: 's' }))
      .toEqual({ recorded_by_user_id: 'u1', recorded_at: 't' });
  });

  it('syncer fields name whoever uploads', () => {
    state.user = { id: 'u2', email: 'u2@x' };
    expect(syncerFields(0)).toEqual({ synced_at: '1970-01-01T00:00:00.000Z', synced_by_user_id: 'u2', synced_by_email: 'u2@x' });
  });

  it('an offline session has no server session to write with', () => {
    state.offline = true; state.accessToken = null; state.refreshToken = null;
    expect(hasServerSession()).toBe(false);
    state.offline = false; state.refreshToken = 'r';
    expect(hasServerSession()).toBe(true);
  });
});
