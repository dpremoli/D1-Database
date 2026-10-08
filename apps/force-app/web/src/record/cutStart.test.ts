import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { RecordClient } from './liveClient';
import { cutStartRefusal, frmWaitingForCut } from './cutStart';

describe('frmWaitingForCut', () => {
	it('waits only while recording with cut detection on and no cut start yet', () => {
		expect(frmWaitingForCut('recording', true, null)).toBe(true);
		expect(frmWaitingForCut('recording', true, 1.2)).toBe(false);   // detected (auto or manual)
		expect(frmWaitingForCut('recording', false, null)).toBe(false); // FRM already runs from sample 0
		expect(frmWaitingForCut('idle', true, null)).toBe(false);
		expect(frmWaitingForCut('done', true, null)).toBe(false);
	});
});

describe('cutStartRefusal', () => {
	it('shows the backend reason, or a plain fallback', () => {
		expect(cutStartRefusal(409, '{"detail":"the cut start is already set (auto, t=1.20 s)"}'))
			.toBe('the cut start is already set (auto, t=1.20 s)');
		expect(cutStartRefusal(502, 'Bad Gateway')).toBe('The recorder refused (502): Bad Gateway');
	});
});

describe('RecordClient.startCutNow', () => {
	const calls: string[] = [];
	let reply: { ok: boolean; status: number; body: string };
	beforeEach(() => {
		calls.length = 0;
		vi.stubGlobal('fetch', vi.fn(async (url: string, init?: { method?: string }) => {
			calls.push(`${init?.method ?? 'GET'} ${new URL(url, 'http://x').pathname}`);
			return { ok: reply.ok, status: reply.status, json: async () => JSON.parse(reply.body), text: async () => reply.body };
		}));
	});
	afterEach(() => { vi.unstubAllGlobals(); });

	it('POSTs /record/cut-start and adopts the origin as an auto detection would', async () => {
		reply = { ok: true, status: 200, body: '{"id":"c1","t":2.5,"sample":4999,"source":"manual"}' };
		const c = new RecordClient();
		c.status.state = 'recording';
		await c.startCutNow();
		expect(calls).toEqual(['POST /record/cut-start']);
		expect(c.status.cutStartSec).toBe(2.5);
	});

	it('throws the refusal reason on a 409 and leaves the status alone', async () => {
		reply = { ok: false, status: 409, body: '{"detail":"no recording in progress"}' };
		const c = new RecordClient();
		await expect(c.startCutNow()).rejects.toThrow('no recording in progress');
		expect(c.status.cutStartSec).toBeNull();
	});

	it('adopts a cut start the recorder already has when the page mounts mid-cut', async () => {
		reply = { ok: true, status: 200, body: '{"state":"recording","id":"c2","n_total":9,"elapsed_sec":1,"cut_start_sec":0.75}' };
		const c = new RecordClient();
		await c.reconcile();
		expect(c.status.cutStartSec).toBe(0.75);
	});
});
