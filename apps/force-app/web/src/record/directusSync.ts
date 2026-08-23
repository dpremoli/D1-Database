// Offline-resilient write queue for run records. Writes go through the Directus `api` (bearer);
// if the DB is unreachable (offline or network error) the record is persisted to localStorage and
// retried on the `online` event + a periodic timer. A 4xx (validation/permission) surfaces the
// error but keeps the item for manual retry. This gives the recording flow offline resilience:
// capture locally now, sync the run record when the network returns.
import { reactive } from 'vue';
import { api } from '../directusClient';

const LS_KEY = 'force-app.sync.queue';

export interface QueuedRun {
	id: string;
	collection: string;
	payload: Record<string, any>;
	createdAt: number;
	attempts: number;
	lastError?: string;
}

export const syncStatus = reactive<{ pending: number; syncing: boolean; lastError: string | null; lastSyncedAt: number | null }>(
	{ pending: 0, syncing: false, lastError: null, lastSyncedAt: null },
);

function load(): QueuedRun[] {
	try { return JSON.parse(localStorage.getItem(LS_KEY) || '[]'); } catch { return []; }
}
function save(q: QueuedRun[]) { localStorage.setItem(LS_KEY, JSON.stringify(q)); syncStatus.pending = q.length; }

// Enqueue a run record and attempt to flush immediately.
export async function logRun(payload: Record<string, any>, collection = 'manufacturing_operations'): Promise<void> {
	const q = load();
	q.push({ id: crypto.randomUUID(), collection, payload, createdAt: Date.now(), attempts: 0 });
	save(q);
	await flush();
}

let flushing = false;
export async function flush(): Promise<void> {
	if (flushing) return;
	if (typeof navigator !== 'undefined' && navigator.onLine === false) return;
	flushing = true;
	syncStatus.syncing = true;
	try {
		// Re-read the queue on every iteration, and again after each await, rather than holding one
		// array for the whole run. The POST is an await point, so the user can discard or reorder an
		// item (Settings > Local Captures) while it is in flight — writing back a copy captured
		// before that would undo their edit, resurrecting an item they had just deleted.
		for (;;) {
			const q = load();
			if (!q.length) break;
			const item = q[0];
			try {
				await api.post(`/items/${item.collection}`, item.payload);
				save(load().filter((x) => x.id !== item.id));   // success — drop just this one
				syncStatus.lastSyncedAt = Date.now();
				syncStatus.lastError = null;
			} catch (e: any) {
				const status = e?.response?.status;
				const cur = load();
				const live = cur.find((x) => x.id === item.id);
				if (!live) break;   // discarded mid-flight — nothing to record against
				live.attempts++;
				live.lastError = e?.message || 'write failed';
				if (status && status >= 400 && status < 500 && status !== 429) {
					// permanent (validation/permission): keep for manual retry but stop the run and surface it
					// live.lastError! : assigned a non-empty string three lines up, but the
					// JSON.stringify() call in this same expression invalidates TS's narrowing
					// of the property (the call could in principle mutate `live`).
					syncStatus.lastError = `${status}: ${(JSON.stringify(e?.response?.data?.errors?.[0]?.message ?? '') || live.lastError!).slice(0, 160)}`;
				}
				// Either way stop: a permanent failure needs attention, and a transient one is
				// retried by the timer / online event.
				save(cur);
				break;
			}
		}
	} finally {
		flushing = false;
		syncStatus.syncing = false;
	}
}

// ---- Queue inspection (Settings > Local Captures) ----
// The topbar only ever showed a count, so a run stuck behind a validation error was invisible:
// no way to see which one, why, or to clear it. These expose the queue for that UI.
export function listQueue(): QueuedRun[] {
	return load();
}

/** Drop one item permanently. Its capture stays on disk; only the pending DB write is abandoned. */
export function discardQueued(id: string): void {
	save(load().filter((x) => x.id !== id));
}

/**
 * Move an item to the front and flush, so a fixed permanent failure can be retried on demand.
 * Returns false if a sync was already running, in which case nothing was attempted here — the
 * item is still promoted, so the in-progress run reaches it next.
 */
export async function retryQueued(id: string): Promise<boolean> {
	const q = load();
	const i = q.findIndex((x) => x.id === id);
	if (i < 0) return false;
	// flush() stops at the first permanent failure, so a poisoned head would block everything
	// behind it — promoting the requested item is what makes a targeted retry possible at all.
	const [item] = q.splice(i, 1);
	q.unshift(item);
	save(q);
	// Deliberately NOT clearing lastError up front. flush() is a no-op while another run holds the
	// guard, so wiping the diagnosis here would repaint the row as a healthy "queued" item with no
	// error and nothing actually retried. The error is cleared by a successful write (the item
	// disappears) or replaced by the next failure.
	if (flushing) return false;
	syncStatus.lastError = null;
	await flush();
	return true;
}

// Wire background retries once.
let started = false;
export function startSync(): void {
	if (started) return;
	started = true;
	syncStatus.pending = load().length;
	window.addEventListener('online', () => { void flush(); });
	setInterval(() => { if (syncStatus.pending > 0) void flush(); }, 15000);
	void flush();
}
