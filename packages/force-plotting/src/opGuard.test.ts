import { describe, expect, it } from 'vitest';
import { createOpGuard } from './opGuard';

describe('createOpGuard', () => {
	it('is live while the same op stays open', () => {
		let open: string | null = 'A';
		const g = createOpGuard(() => open);
		expect(g.begin('A')()).toBe(true);
	});
	it('goes stale when another op is opened, even with no cancelAll()', () => {
		let open: string | null = 'A';
		const g = createOpGuard(() => open);
		const live = g.begin('A');
		open = 'B';
		expect(live()).toBe(false);
	});
	it('cancelAll() stales every guard, including for the same op, and new ones start live', () => {
		const g = createOpGuard(() => 'A');
		const a = g.begin('A'), b = g.begin('A');
		g.cancelAll();
		expect(a()).toBe(false);
		expect(b()).toBe(false);
		expect(g.begin('A')()).toBe(true);
	});
	it('a missing op id is never live', () => {
		const g = createOpGuard(() => null);
		expect(g.begin(null)()).toBe(false);
	});

	// The review scenario: bake on op A, open op B, the bake's poll lands.
	it('a poll started for op A never writes into op B', async () => {
		let open = 'A';
		const detail: Record<string, string> = { A: 'raw', B: 'raw' };
		const g = createOpGuard(() => open);
		let release!: () => void;
		const poll = (async () => {
			const live = g.begin(open);
			await new Promise<void>((r) => { release = r; });
			if (!live()) return;
			detail[open] = 'A-baked';
		})();
		open = 'B'; g.cancelAll();
		release(); await poll;
		expect(detail).toEqual({ A: 'raw', B: 'raw' });
	});
});
