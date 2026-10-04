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
import { clearUploadProgress } from './uploadResume';
import { alarmController } from './alarms';

type Reply = { ok?: boolean; status?: number; body?: unknown; text?: string };
let replies: Record<string, Reply | (() => Reply | Promise<Reply>)>;
const calls: string[] = [];

function memoryStorage() {
	const m = new Map<string, string>();
	return { getItem: (k: string) => m.get(k) ?? null, setItem: (k: string, v: string) => { m.set(k, String(v)); }, removeItem: (k: string) => { m.delete(k); } };
}

beforeEach(() => {
	clearUploadProgress();
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

// ---- 2.2: the save retry resumes instead of inserting a second operation row ----
const posts = (url: string) => dx.post.mock.calls.filter((c) => c[0] === url).length;
const netErr = () => Object.assign(new Error('Network Error'), { response: undefined });
const serverErr = () => Object.assign(new Error('Request failed'), { response: { status: 500, data: { errors: [{ message: 'boom' }] } } });

function okReplies() {
	replies['/captures/cap-up/capture.mat'] = { body: null };
	replies['/captures/cap-up/live_cache.bin'] = { body: null };
}
async function uploadable() {
	const w = await make();
	w.st.state = 'done'; w.st.captureId = 'cap-up'; w.st.summary = { mat_written: true, peaks: { Fx: 1, Fy: 2, Fz: 3 } };
	w.link.sampleId = 'sample-1';
	return w;
}
let fileN = 0;

describe('workspace.uploadCutToDatabase() resume (2.2)', () => {
	beforeEach(() => { okReplies(); fileN = 0; dx.get.mockResolvedValue({ data: { data: [] } }); });

	it('a failed analysis insert does not insert the operation or upload the files again', async () => {
		let analysisFails = true;
		dx.post.mockImplementation(async (url: string) => {
			if (url === '/items/manufacturing_operations') return { data: { data: { operation_id: 'op-1' } } };
			if (url === '/files') return { data: { data: { id: `file-${++fileN}` } } };
			if (url === '/items/machining_force_analysis') { if (analysisFails) throw serverErr(); return { data: { data: {} } }; }
			throw new Error(url);
		});
		const w = await uploadable();
		await expect(w.uploadCutToDatabase()).rejects.toThrow(/linking the capture failed/);
		analysisFails = false;
		await expect(w.uploadCutToDatabase()).resolves.toBe('op-1');
		expect(posts('/items/manufacturing_operations')).toBe(1);
		expect(posts('/files')).toBe(2);
		expect(posts('/items/machining_force_analysis')).toBe(2);
		// and a third call (a double click on Save) is a no-op returning the same row
		await expect(w.uploadCutToDatabase()).resolves.toBe('op-1');
		expect(posts('/items/machining_force_analysis')).toBe(2);
	});

	it('a failed file upload keeps the operation id and the file that did land', async () => {
		let cacheFails = true;
		dx.post.mockImplementation(async (url: string, body: any) => {
			if (url === '/items/manufacturing_operations') return { data: { data: { operation_id: 'op-2' } } };
			if (url === '/files') {
				const name = (body as FormData).get('file') as File;
				if (cacheFails && name.name.endsWith('live_cache.bin')) throw serverErr();
				return { data: { data: { id: `file-${++fileN}` } } };
			}
			return { data: { data: {} } };
		});
		const w = await uploadable();
		await expect(w.uploadCutToDatabase()).rejects.toThrow(/file upload/);
		cacheFails = false;
		await expect(w.uploadCutToDatabase()).resolves.toBe('op-2');
		expect(posts('/items/manufacturing_operations')).toBe(1);
		expect(posts('/files')).toBe(3);   // mat once, cache failed once then uploaded
		const analysis = dx.post.mock.calls.find((c) => c[0] === '/items/machining_force_analysis')![1];
		expect(analysis.operation_id).toBe('op-2');
		expect(analysis.directus_files_id).toBe('file-1');
	});

	it('finds the row a lost response committed (by capture id) instead of inserting again', async () => {
		let first = true;
		dx.post.mockImplementation(async (url: string) => {
			if (url === '/items/manufacturing_operations') {
				if (first) { first = false; throw netErr(); }   // the server committed, the reply was lost
				return { data: { data: { operation_id: 'op-dup' } } };
			}
			if (url === '/files') return { data: { data: { id: `file-${++fileN}` } } };
			return { data: { data: {} } };
		});
		dx.get.mockImplementation(async (url: string) => {
			if (url === '/items/manufacturing_operations') return { data: { data: [{ operation_id: 'op-lost', recorded_metadata: { capture_id: 'cap-up' } }] } };
			return { data: { data: [] } };   // no analysis row yet
		});
		const w = await uploadable();
		await expect(w.uploadCutToDatabase()).rejects.toThrow(/logging the run failed/);
		await expect(w.uploadCutToDatabase()).resolves.toBe('op-lost');
		expect(posts('/items/manufacturing_operations')).toBe(1);
		expect(dx.post.mock.calls.find((c) => c[0] === '/items/machining_force_analysis')![1].operation_id).toBe('op-lost');
	});

	it('does not post a second analysis row when the first attempt\'s reply was lost', async () => {
		let first = true;
		dx.post.mockImplementation(async (url: string) => {
			if (url === '/items/manufacturing_operations') return { data: { data: { operation_id: 'op-3' } } };
			if (url === '/files') return { data: { data: { id: `file-${++fileN}` } } };
			if (url === '/items/machining_force_analysis' && first) { first = false; throw netErr(); }
			return { data: { data: {} } };
		});
		dx.get.mockImplementation(async (url: string) => (url === '/items/machining_force_analysis' ? { data: { data: [{ id: 'a-1' }] } } : { data: { data: [] } }));
		const w = await uploadable();
		await expect(w.uploadCutToDatabase()).rejects.toThrow(/linking/);
		await expect(w.uploadCutToDatabase()).resolves.toBe('op-3');
		expect(posts('/items/machining_force_analysis')).toBe(1);
	});
});

// ---- 2.5: Start is one-shot from the first click, not from the request ----
describe('workspace.start() (2.5)', () => {
	beforeEach(() => { alarmController.testedSinceStart.value = false; });

	it('a double click during the pre-flight prompt runs one start, and busy is held until it finishes', async () => {
		let answer!: (v: boolean) => void;
		confirmMock.confirmAction.mockImplementationOnce(() => new Promise<boolean>((r) => { answer = r; }));
		replies['/record/start'] = { body: { id: 'cap-s' } };
		const w = await make();
		const first = w.start();
		await Promise.resolve();
		expect(w.busy.value).toBe(true);        // set before the alarm prompt resolves
		await w.start();                         // the second click is ignored
		expect(calls.filter((c) => c === 'POST /record/start')).toHaveLength(0);
		answer(false);                           // "Start without testing"
		await first;
		expect(calls.filter((c) => c === 'POST /record/start')).toHaveLength(1);
		expect(w.busy.value).toBe(false);
		expect(w.st.state).toBe('recording');
	});

	it('clears busy when the operator declines the pre-flight', async () => {
		confirmMock.confirmAction.mockResolvedValueOnce(true);   // "Test alarms now": start is aborted
		const w = await make();
		await w.start();
		expect(w.busy.value).toBe(false);
		expect(calls.filter((c) => c === 'POST /record/start')).toHaveLength(0);
	});
});

// ---- 2.7: late replies from superseded searches / picks are dropped ----
function deferred<T>() {
	let resolve!: (v: T) => void; let reject!: (e: unknown) => void;
	const promise = new Promise<T>((res, rej) => { resolve = res; reject = rej; });
	return { promise, resolve, reject };
}
const row = (id: string) => ({ id, live_cache_file: `cache-${id}`, operation_id: { operation_id: null, pass_code: `P-${id}` } });

describe('workspace.searchCuts() (2.7)', () => {
	it('a slow older search cannot overwrite the newer one\'s options', async () => {
		const slow = deferred<any>(); const fast = deferred<any>();
		dx.get.mockReturnValueOnce(slow.promise).mockReturnValueOnce(fast.promise);
		const w = await make();
		const a = w.searchCuts('old');
		const b = w.searchCuts('new');
		fast.resolve({ data: { data: [row('new')] } });
		await b;
		expect(w.replay.options.map((o) => o.opId)).toEqual(['new']);
		expect(w.replay.loading).toBe(false);
		slow.resolve({ data: { data: [row('old')] } });
		await a;
		expect(w.replay.options.map((o) => o.opId)).toEqual(['new']);
	});

	it('a failure of a superseded search does not clear the newer results or the spinner state', async () => {
		const slow = deferred<any>(); const fast = deferred<any>();
		dx.get.mockReturnValueOnce(slow.promise).mockReturnValueOnce(fast.promise);
		const w = await make();
		const a = w.searchCuts('old');
		const b = w.searchCuts('new');
		slow.reject(new Error('timeout'));
		await a;
		expect(w.replay.loading).toBe(true);   // the newer search is still out
		fast.resolve({ data: { data: [row('new')] } });
		await b;
		expect(w.replay.options.map((o) => o.opId)).toEqual(['new']);
	});
});

describe('workspace.pickReplayCut() (2.7)', () => {
	const opt = (id: string) => ({
		label: id, cacheId: `cache-${id}`, opId: id, operationId: null, ppr: null, outerDiam: null,
		innerDiam: null, sampleRate: null, cropStartSec: null,
	});

	it('a download that finishes after switching to Sim does not load into the playhead', async () => {
		const dl = deferred<any>();
		dx.get.mockReturnValueOnce(dl.promise);
		const w = await make();
		const load = vi.spyOn(w.playback, 'load').mockImplementation(() => {});
		w.setSource('replay');
		const p = w.pickReplayCut(opt('a'));
		expect(w.replay.downloading).toBe(true);
		w.setSource('sim');
		expect(w.replay.downloading).toBe(false);
		dl.resolve({ data: new ArrayBuffer(8) });
		await p;
		expect(load).not.toHaveBeenCalled();
		expect(w.replay.cacheId).toBe('');
	});

	it('of two picks, only the later one loads, whichever download finishes first', async () => {
		const first = deferred<any>(); const second = deferred<any>();
		dx.get.mockReturnValueOnce(first.promise).mockReturnValueOnce(second.promise);
		const w = await make();
		const load = vi.spyOn(w.playback, 'load').mockImplementation(() => {});
		w.setSource('replay');
		const a = w.pickReplayCut(opt('a'));
		const b = w.pickReplayCut(opt('b'));
		second.resolve({ data: new ArrayBuffer(8) });
		await b;
		first.resolve({ data: new ArrayBuffer(8) });
		await a;
		expect(load).toHaveBeenCalledTimes(1);
		expect(w.replay.cacheId).toBe('cache-b');
		expect(w.replay.downloading).toBe(false);
	});

	it('a superseded pick\'s error does not overwrite the current state', async () => {
		const first = deferred<any>();
		dx.get.mockReturnValueOnce(first.promise);
		const w = await make();
		vi.spyOn(w.playback, 'load').mockImplementation(() => {});
		w.setSource('replay');
		const a = w.pickReplayCut(opt('a'));
		w.setSource('sim');
		first.reject(new Error('network'));
		await a;
		expect(w.errMsg.value).toBeNull();
	});
});

// ---- the amp goes back to RESET once a long finalize ends, not while the recorder is busy ----
describe('workspace.stop() returns the amp to RESET after finalize', () => {
	beforeEach(() => { labampMock.setMode.mockClear(); localStorage.setItem('force-app.source', 'nidaq'); });
	const resets = () => labampMock.setMode.mock.calls.filter((c) => c[0] === 'RESET').length;

	async function stopping(state: string) {
		replies['/record/stop'] = { body: { state, id: 'cap-a' } };
		replies['/captures/cap-a/summary'] = { body: {} };
		const w = await make();
		w.setSource('nidaq');
		labampMock.setMode.mockClear();
		w.st.state = 'recording'; w.st.captureId = 'cap-a';
		await w.stop();
		return w;
	}

	it('while finalizing sends nothing yet, then one RESET when it reaches done', async () => {
		const w = await stopping('finalizing');
		expect(resets()).toBe(0);
		w.st.state = 'done';
		expect(resets()).toBe(1);
		w.st.state = 'idle'; w.st.state = 'done';
		expect(resets()).toBe(1);
	});

	it('also resets when the finalize ends in error', async () => {
		const w = await stopping('finalizing');
		w.st.state = 'error';
		expect(resets()).toBe(1);
	});

	it('does not reset if a new recording started meanwhile', async () => {
		const w = await stopping('finalizing');
		w.st.state = 'recording'; w.st.captureId = 'cap-b';
		w.st.state = 'done';
		expect(resets()).toBe(0);
	});

	it('an already-settled stop resets straight away', async () => {
		await stopping('done');
		expect(resets()).toBe(1);
	});
});
