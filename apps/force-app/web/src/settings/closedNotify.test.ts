import { describe, expect, it, vi } from 'vitest';
import { closedNotifyBridge, closedNotifyWarning, loadClosedNotify, setClosedNotify, toggleClosedNotifyBox } from './closedNotify';

const bridge = (over: Record<string, unknown> = {}) => ({
	getUpdateNotifyWhenClosed: vi.fn(async () => ({ supported: true, enabled: true, active: true })),
	setUpdateNotifyWhenClosed: vi.fn(async (e: boolean) => ({ ok: true, enabled: e })),
	...over,
}) as never;

describe('closedNotifyBridge', () => {
	it('is undefined in the browser build and in an older shell without the methods', () => {
		expect(closedNotifyBridge(undefined)).toBeUndefined();
		expect(closedNotifyBridge({ forceApp: {} })).toBeUndefined();
	});
	it('is the bridge when both methods exist', () => {
		const b = bridge();
		expect(closedNotifyBridge({ forceApp: b })).toBe(b);
	});
});

describe('loadClosedNotify', () => {
	it('passes the shell state through', async () => {
		expect(await loadClosedNotify(bridge())).toEqual({ supported: true, enabled: true, active: true });
	});
	it('reports a preference that is on with no scheduled task behind it', async () => {
		const b = bridge({ getUpdateNotifyWhenClosed: async () => ({ supported: true, enabled: true, active: false }) });
		expect(await loadClosedNotify(b)).toEqual({ supported: true, enabled: true, active: false });
	});
	it('assumes the task exists when an older shell does not say', async () => {
		const b = bridge({ getUpdateNotifyWhenClosed: async () => ({ supported: true, enabled: true }) });
		expect((await loadClosedNotify(b)).active).toBe(true);
	});
	it('reports unsupported when the call fails', async () => {
		const b = bridge({ getUpdateNotifyWhenClosed: async () => { throw new Error('x'); } });
		expect(await loadClosedNotify(b)).toEqual({ supported: false, enabled: false, active: false });
	});
});

describe('setClosedNotify', () => {
	it('turns it off', async () => {
		const b = bridge();
		expect(await setClosedNotify(b, false, true)).toEqual({ enabled: false, error: '' });
		expect((b as any).setUpdateNotifyWhenClosed).toHaveBeenCalledWith(false);
	});
	it('keeps the previous value and says why when the shell refuses', async () => {
		const b = bridge({ setUpdateNotifyWhenClosed: async () => ({ ok: false, enabled: false, reason: 'Windows refused' }) });
		expect(await setClosedNotify(b, true, false)).toEqual({ enabled: false, error: 'Windows refused' });
	});
	it('does not throw when the call rejects', async () => {
		const b = bridge({ setUpdateNotifyWhenClosed: async () => { throw new Error('ipc gone'); } });
		expect(await setClosedNotify(b, true, false)).toEqual({ enabled: false, error: 'ipc gone' });
	});
});

describe('closedNotifyWarning', () => {
	it('warns only when it is on, supported and the task is missing', () => {
		expect(closedNotifyWarning(true, true, false)).toMatch(/Couldn't set up the scheduled check \(Windows refused\)/);
		expect(closedNotifyWarning(true, true, true)).toBe('');
		expect(closedNotifyWarning(true, false, false)).toBe('');   // off: nothing is expected to exist
		expect(closedNotifyWarning(false, true, false)).toBe('');   // browser build: no toggle at all
	});
});

describe('toggleClosedNotifyBox', () => {
	it('unticks the box again when Windows refuses the enable', async () => {
		const b = bridge({ setUpdateNotifyWhenClosed: async () => ({ ok: false, enabled: false, reason: 'Windows refused' }) });
		const box = { checked: true };   // the click ticked it
		const r = await toggleClosedNotifyBox(b, box, false);
		expect(r.error).toBe('Windows refused');
		expect(box.checked).toBe(false);
	});
	it('re-ticks the box when a refused disable leaves it on', async () => {
		const b = bridge({ setUpdateNotifyWhenClosed: async () => { throw new Error('ipc gone'); } });
		const box = { checked: false };
		await toggleClosedNotifyBox(b, box, true);
		expect(box.checked).toBe(true);
	});
	it('leaves the box as clicked when the change took', async () => {
		const box = { checked: false };
		const r = await toggleClosedNotifyBox(bridge(), box, true);
		expect(r).toEqual({ enabled: false, error: '' });
		expect(box.checked).toBe(false);
	});
});
