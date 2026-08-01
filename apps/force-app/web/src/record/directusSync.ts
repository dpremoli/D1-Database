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
		let q = load();
		while (q.length) {
			const item = q[0];
			try {
				await api.post(`/items/${item.collection}`, item.payload);
				q.shift();                       // success — drop it
				save(q);
				syncStatus.lastSyncedAt = Date.now();
				syncStatus.lastError = null;
			} catch (e: any) {
				const status = e?.response?.status;
				item.attempts++;
				item.lastError = e?.message || 'write failed';
				if (status && status >= 400 && status < 500 && status !== 429) {
					// permanent (validation/permission): keep for manual retry but stop the run and surface it
					syncStatus.lastError = `${status}: ${(JSON.stringify(e?.response?.data?.errors?.[0]?.message ?? '') || item.lastError).slice(0, 160)}`;
					save(q);
					break;
				}
				// transient (offline/5xx/429): stop; the timer / online event retries later
				save(q);
				break;
			}
		}
	} finally {
		flushing = false;
		syncStatus.syncing = false;
	}
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
