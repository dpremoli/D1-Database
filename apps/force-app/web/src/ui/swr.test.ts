import { describe, expect, it } from 'vitest';
import { createSwr } from './swr';

function deferred<T>() {
	let resolve!: (v: T) => void, reject!: (e: unknown) => void;
	const promise = new Promise<T>((res, rej) => { resolve = res; reject = rej; });
	return { promise, resolve, reject };
}

describe('createSwr', () => {
	it('keeps the last-known data visible while a refresh runs', async () => {
		let n = 0;
		const gate = deferred<void>();
		const s = createSwr(async () => { n++; if (n > 1) await gate.promise; return n; });
		await s.revalidate();
		expect(s.data.value).toBe(1);
		const p = s.revalidate();
		expect(s.loading.value).toBe(true);
		expect(s.data.value).toBe(1);   // stale, not cleared
		gate.resolve();
		await p;
		expect(s.data.value).toBe(2);
		expect(s.loading.value).toBe(false);
	});

	it('shares one in-flight request between concurrent callers', async () => {
		let calls = 0;
		const gate = deferred<number>();
		const s = createSwr(() => { calls++; return gate.promise; });
		const a = s.revalidate(), b = s.revalidate();
		gate.resolve(7);
		await Promise.all([a, b]);
		expect(calls).toBe(1);
		expect(s.data.value).toBe(7);
	});

	it('keeps the data and reports the error when a refresh fails', async () => {
		let fail = false;
		const s = createSwr(async () => { if (fail) throw new Error('offline'); return 'ok'; });
		await s.revalidate();
		fail = true;
		await s.revalidate();
		expect(s.data.value).toBe('ok');
		expect(s.error.value).toBe('offline');
		fail = false;
		await s.revalidate();
		expect(s.error.value).toBeNull();
	});

	it('drops a refresh that was in flight across a local mutate', async () => {
		const gate = deferred<string>();
		const s = createSwr(() => gate.promise);
		const p = s.revalidate();
		s.mutate('saved locally');
		gate.resolve('stale from before the save');
		await p;
		expect(s.data.value).toBe('saved locally');
	});

	it('mutate can derive from the current data', async () => {
		const s = createSwr(async () => ({ mode: 'RESET', n: 1 }));
		await s.revalidate();
		s.mutate((cur) => ({ ...cur!, mode: 'MEASURE' }));
		expect(s.data.value).toEqual({ mode: 'MEASURE', n: 1 });
	});
});
