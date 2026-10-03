import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

// createWorkspace() start/stop/upload paths (stream-2 review 2.1, 2.2, 2.5, 2.7). Everything the
// workspace talks to (Directus, the recorder, dialogs) is faked at the module boundary.

const dx = vi.hoisted(() => ({ post: vi.fn(), get: vi.fn() }));
vi.mock('../directusClient', () => ({
	api: { post: (...a: unknown[]) => dx.post(...a), get: (...a: unknown[]) => dx.get(...a) },
	authHeaders: () => ({}),
}));
const auth = vi.hoisted(() => ({
	state: { user: { id: 'u1', email: 'a@b.c' } as any, offline: false, accessToken: 'at' as string | null, refreshToken: 'rt' as string | null },
}));
vi.mock('../authStore', () => ({ authStore: auth }));
vi.mock('@d1/force-plotting', () => ({
	buildSeriesEnvelope: vi.fn(() => ({ series: true })),
	debouncePublish: () => ({ push: () => {}, flush: () => {} }),
	parseCache: vi.fn(() => ({ csSec: 0, ceSec: 1 })),
}));
vi.mock('./directusLookups', () => ({
	searchSamples: vi.fn(), searchOperators: vi.fn(), searchEquipment: vi.fn(), searchTools: vi.fn(),
	searchInserts: vi.fn(), searchEdges: vi.fn(),
	getMethods: vi.fn().mockResolvedValue([]),
	resolveMachiningMethodId: vi.fn().mockResolvedValue('method-1'),
}));
vi.mock('./directusSync', () => ({ logRun: vi.fn(), syncStatus: {} }));
const labampMock = vi.hoisted(() => ({ setMode: vi.fn().mockResolvedValue(undefined), converge: vi.fn() }));
vi.mock('./labampApi', () => ({ labamp: labampMock }));
const confirmMock = vi.hoisted(() => ({ confirmAction: vi.fn().mockResolvedValue(true) }));
vi.mock('../ui/confirm', () => confirmMock);
vi.mock('../ui/spotlight', () => ({ spotlight: vi.fn() }));

import { createWorkspace } from './workspace';

type Reply = { ok?: boolean; status?: number; body?: unknown; text?: string };
let replies: Record<string, Reply | (() => Reply | Promise<Reply>)>;
const calls: string[] = [];

function memoryStorage() {
	const m = new Map<string, string>();
	return { getItem: (k: string) => m.get(k) ?? null, setItem: (k: string, v: string) => { m.set(k, String(v)); }, removeItem: (k: string) => { m.delete(k); } };
}

beforeEach(() => {
	replies = {};
	calls.length = 0;
	dx.post.mockReset(); dx.get.mockReset();
	auth.state.offline = false; auth.state.accessToken = 'at';
	vi.stubGlobal('localStorage', memoryStorage());
	vi.stubGlobal('window', { addEventListener: () => {}, removeEventListener: () => {} });
	vi.stubGlobal('fetch', vi.fn(async (url: string, init?: { method?: string }) => {
		const path = new URL(url, 'http://x').pathname;
		calls.push(`${init?.method ?? 'GET'} ${path}`);
		const r0 = replies[path];
		const r = (typeof r0 === 'function' ? await r0() : r0) ?? { ok: false, status: 404 };
		return { ok: r.ok ?? true, status: r.status ?? 200, json: async () => r.body, text: async () => r.text ?? '', blob: async () => new Blob(['x']), arrayBuffer: async () => new ArrayBuffer(8) };
	}));
});
afterEach(() => { vi.unstubAllGlobals(); });

async function make() {
	const w = createWorkspace();
	await Promise.resolve();
	return w;
}

describe('workspace.stop() (2.1)', () => {
	it('when the recorder refuses the stop and is still recording: closes the dialog and says so', async () => {
		replies['/record/stop'] = { ok: false, status: 500, text: 'boom' };
		replies['/record/status'] = { body: { state: 'recording', id: 'cap-1' } };
		const w = await make();
		w.st.state = 'recording'; w.st.captureId = 'cap-1';
		await w.stop();
		expect(w.saveOpen.value).toBe(false);
		expect(w.errMsg.value).toMatch(/could not stop the recording.*500/);
		expect(w.busy.value).toBe(false);
	});

	it('409 because the cut already ended on its own: adopts the recorder state and keeps the save dialog', async () => {
		replies['/record/stop'] = { ok: false, status: 409, text: 'not recording' };
		replies['/record/status'] = { body: { state: 'done', id: 'cap-2' } };
		replies['/captures/cap-2/summary'] = { body: { duration_sec: 3 } };
		replies['/captures/cap-2/live_cache.bin'] = { body: null };
		const w = await make();
		w.st.state = 'recording'; w.st.captureId = 'cap-2';
		await w.stop();
		expect(w.st.state).toBe('done');
		expect(w.saveOpen.value).toBe(true);
		expect(w.errMsg.value).toBeNull();
		expect(w.finishedCache.value).not.toBeNull();
	});

	it('an unreachable recorder does not leave the dialog spinning on "recording"', async () => {
		vi.stubGlobal('fetch', vi.fn(async () => { throw new TypeError('Failed to fetch'); }));
		const w = await make();
		w.st.state = 'recording'; w.st.captureId = 'cap-3';
		await w.stop();
		expect(w.saveOpen.value).toBe(false);
		expect(w.errMsg.value).toMatch(/could not stop/);
	});
});
