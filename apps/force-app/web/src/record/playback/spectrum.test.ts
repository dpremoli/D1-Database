import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest';
import { createSpectrumClient } from './spectrum';

const REPLY = { fs: 1000, f: [0, 10, 20], spectra: { Fz: [1, 2, 3] } };

function okFetch() {
	return vi.fn(async (_url?: any, _init?: any) => ({ ok: true, status: 200, json: async () => REPLY }) as any);
}

beforeEach(() => { vi.useFakeTimers(); });
afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals(); });

const req = (n = 4) => ({ fs: 1000, names: ['Fz'], samples: new Float32Array(n) });

describe('spectrum client', () => {
	it('sends the window as float32 to /dsp/spectrum with names and fs in the query', async () => {
		const f = okFetch();
		vi.stubGlobal('fetch', f);
		const c = createSpectrumClient('http://localhost:8200');
		const replies: any[] = [];
		c.onReply = (r) => replies.push(r);
		c.request({ fs: 1000, names: ['Fx', 'Fz'], samples: new Float32Array([1, 2, 3, 4]) });
		await c.flush();

		expect(f).toHaveBeenCalledTimes(1);
		const [url, init] = f.mock.calls[0];
		expect(String(url)).toContain('/dsp/spectrum');
		expect(String(url)).toContain('fs=1000');
		expect(String(url)).toContain('names=Fx%2CFz');
		expect(init.method).toBe('POST');
		expect(new Float32Array(init.body)).toEqual(new Float32Array([1, 2, 3, 4]));
		expect(replies).toEqual([REPLY]);
	});

	it('throttles to minIntervalMs', async () => {
		const f = okFetch();
		vi.stubGlobal('fetch', f);
		const c = createSpectrumClient('http://x', { minIntervalMs: 300 });
		c.request(req());
		await c.flush();
		expect(f).toHaveBeenCalledTimes(1);

		c.request(req());          // immediately after — inside the throttle window
		await c.flush();
		expect(f).toHaveBeenCalledTimes(1);

		vi.advanceTimersByTime(301);
		c.request(req());
		await c.flush();
		expect(f).toHaveBeenCalledTimes(2);
	});

	it('force bypasses the throttle', async () => {
		const f = okFetch();
		vi.stubGlobal('fetch', f);
		const c = createSpectrumClient('http://x', { minIntervalMs: 300 });
		c.request(req());
		await c.flush();
		c.request({ ...req(), force: true });
		await c.flush();
		expect(f).toHaveBeenCalledTimes(2);
	});

	it('coalesces: a request made while one is in flight replaces any earlier pending one', async () => {
		let release!: (v: any) => void;
		const gate = new Promise((r) => { release = r; });
		const f = vi.fn(async (_u: any, init: any) => {
			const n = new Float32Array(init.body)[0];
			if (n === 1) await gate;
			return { ok: true, status: 200, json: async () => ({ ...REPLY, fs: n }) } as any;
		});
		vi.stubGlobal('fetch', f);
		const c = createSpectrumClient('http://x', { minIntervalMs: 0 });
		const replies: any[] = [];
		c.onReply = (r) => replies.push(r);

		c.request({ fs: 1, names: ['Fz'], samples: new Float32Array([1]) });   // in flight, gated
		c.request({ fs: 2, names: ['Fz'], samples: new Float32Array([2]) });   // pending
		c.request({ fs: 3, names: ['Fz'], samples: new Float32Array([3]) });   // replaces #2
		release(null);
		await c.flush();

		expect(f).toHaveBeenCalledTimes(2);
		expect(replies.map((r) => r.fs)).toEqual([1, 3]);   // #2 was dropped, never sent
	});

	it('surfaces an error without stalling later requests', async () => {
		const f = vi.fn()
			.mockResolvedValueOnce({ ok: false, status: 503, text: async () => 'down' } as any)
			.mockResolvedValue({ ok: true, status: 200, json: async () => REPLY } as any);
		vi.stubGlobal('fetch', f);
		const c = createSpectrumClient('http://x', { minIntervalMs: 0 });
		const errs: Error[] = []; const replies: any[] = [];
		c.onError = (e) => errs.push(e);
		c.onReply = (r) => replies.push(r);

		c.request(req());
		await c.flush();
		expect(errs).toHaveLength(1);

		c.request(req());
		await c.flush();
		expect(replies).toEqual([REPLY]);
	});
});
