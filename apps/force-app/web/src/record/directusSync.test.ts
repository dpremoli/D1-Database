import { beforeEach, describe, expect, it, vi } from 'vitest';

// The offline queue persists to localStorage and posts over the network, so both are stubbed.
// `api.post` is controllable per-test, which is what lets the concurrency test hold a write open.
const post = vi.fn();
vi.mock('../directusClient', () => ({ api: { post: (...a: unknown[]) => post(...a) } }));

const store = new Map<string, string>();
vi.stubGlobal('localStorage', {
  getItem: (k: string) => store.get(k) ?? null,
  setItem: (k: string, v: string) => void store.set(k, v),
  removeItem: (k: string) => void store.delete(k),
});

const LS_KEY = 'force-app.sync.queue';

import { discardQueued, flush, listQueue, logRun, retryQueued } from './directusSync';

function seed(items: Array<{ id: string; sample: string }>) {
  store.set(LS_KEY, JSON.stringify(items.map((i) => ({
    id: i.id,
    collection: 'manufacturing_operations',
    payload: { recorded_metadata: { sample_name: i.sample } },
    createdAt: Date.now(),
    attempts: 0,
  }))));
}
const idsInQueue = () => listQueue().map((q) => q.id);

beforeEach(() => {
  store.clear();
  post.mockReset();
});

describe('flush', () => {
  it('drops each item as it succeeds', async () => {
    seed([{ id: 'a', sample: 'S1' }, { id: 'b', sample: 'S2' }]);
    post.mockResolvedValue({ data: { data: {} } });

    await flush();

    expect(idsInQueue()).toEqual([]);
    expect(post).toHaveBeenCalledTimes(2);
  });

  it('stops at a permanent 4xx and keeps the item for manual retry', async () => {
    seed([{ id: 'a', sample: 'S1' }, { id: 'b', sample: 'S2' }]);
    post.mockRejectedValue({ response: { status: 403, data: { errors: [{ message: 'forbidden' }] } } });

    await flush();

    // Both remain: the head failed permanently, and everything behind it is blocked by design.
    expect(idsInQueue()).toEqual(['a', 'b']);
    expect(listQueue()[0].attempts).toBe(1);
    expect(listQueue()[0].lastError).toBeTruthy();
  });

  it('a discard while a write is in flight is not undone', async () => {
    // The regression this guards: flush() used to hold one array across its awaits and write it
    // back at the end. A discard landing during an in-flight POST was therefore clobbered — the
    // item the user deleted reappeared in the queue.
    seed([{ id: 'a', sample: 'S1' }, { id: 'b', sample: 'S2' }]);

    let releaseFirst!: () => void;
    post.mockImplementationOnce(
      () => new Promise((resolve) => { releaseFirst = () => resolve({ data: { data: {} } }); }),
    );
    post.mockResolvedValue({ data: { data: {} } });

    const running = flush();
    await vi.waitFor(() => expect(post).toHaveBeenCalledTimes(1));

    discardQueued('b');            // user deletes the queued item behind the one being written
    expect(idsInQueue()).toEqual(['a']);

    releaseFirst();
    await running;

    expect(idsInQueue()).toEqual([]);       // 'a' posted and dropped
    expect(post).toHaveBeenCalledTimes(1);  // 'b' was never sent — it was discarded first
  });

  it('an item enqueued while a write is in flight is not lost', async () => {
    seed([{ id: 'a', sample: 'S1' }]);

    let releaseFirst!: () => void;
    post.mockImplementationOnce(
      () => new Promise((resolve) => { releaseFirst = () => resolve({ data: { data: {} } }); }),
    );
    // The run continues past the first success, so the newly-added item is attempted too. Fail it
    // transiently to keep it queued and observable — the point is that it still EXISTS, rather
    // than having been erased by a stale write-back.
    post.mockRejectedValue({ message: 'Network Error' });

    const running = flush();
    await vi.waitFor(() => expect(post).toHaveBeenCalledTimes(1));

    // logRun() calls flush() itself, but the in-progress run holds the `flushing` guard, so this
    // only enqueues — exactly the interleaving a cut finishing mid-sync produces.
    await logRun({ recorded_metadata: { sample_name: 'S-NEW' } });

    releaseFirst();
    await running;

    const names = listQueue().map((q) => q.payload.recorded_metadata.sample_name);
    expect(names).toEqual(['S-NEW']);
  });
});

describe('queue management', () => {
  it('discardQueued removes only the named item', () => {
    seed([{ id: 'a', sample: 'S1' }, { id: 'b', sample: 'S2' }, { id: 'c', sample: 'S3' }]);
    discardQueued('b');
    expect(idsInQueue()).toEqual(['a', 'c']);
  });

  it('retryQueued promotes the item to the head so it is attempted first', async () => {
    // flush() stops at the first permanent failure, so a poisoned head blocks everything behind
    // it. Promoting is what makes a targeted retry reach the network at all.
    seed([{ id: 'a', sample: 'STUCK' }, { id: 'b', sample: 'WANTED' }]);
    post.mockRejectedValue({ response: { status: 400, data: { errors: [{ message: 'bad' }] } } });
    await flush();                       // 'a' fails permanently and parks at the head
    expect(listQueue()[0].id).toBe('a');

    post.mockReset();
    // Only the promoted item succeeds; the stuck one keeps failing, as it would in reality.
    post.mockResolvedValueOnce({ data: { data: {} } });
    post.mockRejectedValue({ response: { status: 400, data: { errors: [{ message: 'bad' }] } } });
    await retryQueued('b');

    // The promoted item is written FIRST — that is the whole point, since flush() would otherwise
    // stop on the stuck head and never reach it.
    expect(post.mock.calls[0][1]).toMatchObject({ recorded_metadata: { sample_name: 'WANTED' } });
    expect(idsInQueue()).toEqual(['a']);   // 'b' went through; the stuck one is still queued
  });

  it('retryQueued keeps the previous error visible until the retry actually resolves it', async () => {
    // The diagnosis must not be wiped optimistically: flush() is a no-op while another run holds
    // the guard, so clearing it up front repainted the row as a healthy "queued" item with no
    // error and nothing retried. It goes away when the write succeeds (the item disappears) or is
    // replaced by the next failure.
    seed([{ id: 'a', sample: 'S1' }]);
    post.mockRejectedValue({ response: { status: 400, data: { errors: [{ message: 'bad' }] } } });
    await flush();
    expect(listQueue()[0].lastError).toBeTruthy();

    post.mockReset();
    // Held open so the state can be inspected mid-retry, then released — `flushing` is module
    // state, so leaving a write pending would wedge the guard for every later test.
    let release!: () => void;
    post.mockImplementation(
      () => new Promise((_res, rej) => { release = () => rej({ message: 'Network Error' }); }),
    );
    const retrying = retryQueued('a');
    await vi.waitFor(() => expect(post).toHaveBeenCalled());

    expect(listQueue()[0].lastError).toBeTruthy();

    release();
    await retrying;
  });

  it('retryQueued reports that nothing was attempted when a sync is already running', async () => {
    seed([{ id: 'a', sample: 'S1' }, { id: 'b', sample: 'S2' }]);
    let release!: () => void;
    post.mockImplementationOnce(
      () => new Promise((resolve) => { release = () => resolve({ data: { data: {} } }); }),
    );
    post.mockRejectedValue({ message: 'Network Error' });

    const running = flush();
    await vi.waitFor(() => expect(post).toHaveBeenCalledTimes(1));

    // flush() is guarded, so this cannot send anything right now — say so rather than letting the
    // caller report a retry that never happened.
    expect(await retryQueued('b')).toBe(false);
    expect(idsInQueue()[0]).toBe('b');   // still promoted, so the running flush reaches it next

    release();
    await running;
  });

  it('retryQueued on an unknown id is a no-op', async () => {
    seed([{ id: 'a', sample: 'S1' }]);
    post.mockResolvedValue({ data: { data: {} } });
    await retryQueued('nope');
    expect(post).not.toHaveBeenCalled();
    expect(idsInQueue()).toEqual(['a']);
  });
});
