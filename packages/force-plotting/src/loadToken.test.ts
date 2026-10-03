import { describe, expect, it } from 'vitest';
import { createLoadToken } from './loadToken';

describe('createLoadToken', () => {
	it('only the newest load is current', () => {
		const t = createLoadToken();
		const a = t.next(), b = t.next();
		expect(t.isCurrent(a)).toBe(false);
		expect(t.isCurrent(b)).toBe(true);
	});
	it('cancel makes every in-flight load stale', () => {
		const t = createLoadToken();
		const a = t.next();
		t.cancel();
		expect(t.isCurrent(a)).toBe(false);
	});

	// The scenario from the review: op A downloads slowly, op B finishes first, then A lands.
	it('a slow older load that lands last applies nothing', async () => {
		const t = createLoadToken();
		const applied: string[] = [];
		const gates: Record<string, () => void> = {};
		const load = async (id: string) => {
			const mine = t.next();
			await new Promise<void>((r) => { gates[id] = r; });
			if (!t.isCurrent(mine)) return;
			applied.push(id);
		};
		const a = load('A'), b = load('B');
		gates.B(); await b;
		gates.A(); await a;
		expect(applied).toEqual(['B']);
	});
});
