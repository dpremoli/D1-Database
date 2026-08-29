import { describe, expect, it } from 'vitest';
import { confirmAction, confirmState, resolveActive } from './confirm';

/** Drain the microtask queue so a pending confirmAction() has actually reached `confirmState`. */
const settle = () => new Promise((r) => setTimeout(r, 0));

describe('confirmAction', () => {
	it('resolves true only on an explicit accept', async () => {
		const p = confirmAction({ title: 'T', message: 'M' });
		await settle();
		expect(confirmState.current?.title).toBe('T');
		resolveActive(true);
		expect(await p).toBe(true);
		expect(confirmState.current).toBeNull();
	});

	it('resolves false on cancel', async () => {
		const p = confirmAction({ title: 'T', message: 'M' });
		await settle();
		resolveActive(false);
		expect(await p).toBe(false);
	});

	it('queues a second request instead of stranding its promise', async () => {
		// Two dialogs at once would stack, hiding one behind the other; whichever lost would never
		// be resolved and its caller would await forever. They must run strictly in order.
		const first = confirmAction({ title: 'first', message: 'M' });
		const second = confirmAction({ title: 'second', message: 'M' });
		await settle();

		expect(confirmState.current?.title).toBe('first');
		resolveActive(true);
		expect(await first).toBe(true);

		await settle(); // the next one is shown on a fresh task, not synchronously
		expect(confirmState.current?.title).toBe('second');
		resolveActive(false);
		expect(await second).toBe(false);
		expect(confirmState.current).toBeNull();
	});

	it('carries stats and labels through to the dialog', async () => {
		const p = confirmAction({
			title: 'Silence this alarm?',
			message: 'M',
			stats: [{ label: 'Fz force', value: '412.0 N (limit 400.0 N)' }],
			confirmLabel: 'Silence',
			tone: 'danger',
		});
		await settle();
		expect(confirmState.current?.stats?.[0].value).toBe('412.0 N (limit 400.0 N)');
		expect(confirmState.current?.confirmLabel).toBe('Silence');
		expect(confirmState.current?.tone).toBe('danger');
		resolveActive(false);
		await p;
	});
});
