import { describe, expect, it } from 'vitest';
import {
	describeMissing, missingBindings, missingFromChassis, noForceBound, reassignConfirmText, type BoundChannel,
} from './channelBindings';

const CORE = ['Fx1', 'Fx2', 'Fy1', 'Fy2', 'Fz1', 'Fz2', 'Fz3', 'Fz4', 'Tacho'];
const role = (n: string) => (n === 'Tacho' ? 'Tacho' : n.slice(0, 2));
const bound = (): BoundChannel[] => CORE.map((name, i) => ({
	name, role: role(name), physical: `cDAQ1Mod${1 + Math.floor(i / 4)}/ai${i % 4}`, source: 'hardware',
}));
const scanOf = (b: BoundChannel[]) => b.map((c) => c.physical as string);

describe('missingBindings (#195)', () => {
	it('is empty when every bound port is in the scan, whatever the case', () => {
		const b = bound();
		expect(missingBindings(b, scanOf(b))).toEqual([]);
		expect(missingBindings(b, scanOf(b).map((p) => p.toLowerCase()))).toEqual([]);
	});

	it('lists the ports a swapped module took away, with the roles that used them', () => {
		const b = bound();
		// Module 2 (Fz1..Fz4) is unplugged: its four ports are gone from the scan.
		const scan = scanOf(b).filter((p) => !p.startsWith('cDAQ1Mod2/'));
		const missing = missingBindings(b, scan);
		expect(missing.map((m) => m.name)).toEqual(['Fz1', 'Fz2', 'Fz3', 'Fz4']);
		expect(missing.map((m) => m.physical)).toEqual(['cDAQ1Mod2/ai0', 'cDAQ1Mod2/ai1', 'cDAQ1Mod2/ai2', 'cDAQ1Mod2/ai3']);
		expect(missing.every((m) => m.role === 'Fz')).toBe(true);
	});

	it('says nothing without a real scan (none connected, or the simulated tree)', () => {
		const b = bound();
		expect(missingBindings(b, null)).toEqual([]);
		expect(missingBindings(b, undefined)).toEqual([]);
		expect(missingBindings(b, [])).toEqual([]);
	});

	it('ignores virtual channels and channels with no port', () => {
		const b: BoundChannel[] = [
			{ name: 'Fx', role: 'Virtual', physical: 'gone/ai0', source: 'virtual' },
			{ name: 'Aux1', role: 'Aux', physical: null },
		];
		expect(missingBindings(b, ['x/ai0'])).toEqual([]);
	});

	it('describeMissing groups channels that share a port', () => {
		expect(describeMissing([
			{ name: 'Fx1', role: 'Fx', physical: 'a/ai0' },
			{ name: 'Fx2', role: 'Fx', physical: 'a/ai0' },
			{ name: 'Tacho', role: 'Tacho', physical: 'b/ai0' },
		])).toEqual(['a/ai0 (Fx1, Fx2)', 'b/ai0 (Tacho)']);
	});
});

describe('noForceBound (#195)', () => {
	it('warns for empty bindings only when the scan has ports to give', () => {
		const empty: BoundChannel[] = CORE.map((name) => ({ name, role: role(name), physical: null }));
		expect(noForceBound(empty, ['cDAQ1Mod1/ai0'])).toBe(true);
		expect(noForceBound([], ['cDAQ1Mod1/ai0'])).toBe(true);
		expect(noForceBound(empty, [])).toBe(false);
		expect(noForceBound(empty, null)).toBe(false);
	});

	it('one bound force channel is not "no force channels"', () => {
		const b = bound().map((c, i) => (i === 0 ? c : { ...c, physical: null }));
		expect(noForceBound(b, scanOf(bound()))).toBe(false);
	});
});

describe('reassignConfirmText', () => {
	it('names the missing ports and warns that the whole list is replaced', () => {
		const b = bound();
		const t = reassignConfirmText(b, scanOf(b).slice(0, 4));
		expect(t).toContain('cDAQ1Mod2/ai0 (Fz1)');
		expect(t).toContain('cDAQ1Mod3/ai0 (Tacho)');
		expect(t).toContain('replaces the whole saved channel list');
		expect(t).toContain('4 inputs');
		expect(t).toContain('kept as a backup file');
	});
	it('says so when nothing is bound', () => {
		expect(reassignConfirmText([], ['a/ai0'])).toContain('No force channel has an input assigned');
	});
});

describe('missingFromChassis (moved here from preflight)', () => {
	it('lists unknown inputs once', () => {
		expect(missingFromChassis(['a/ai0', 'x/ai0', 'x/ai0'], ['a/ai0'])).toEqual(['x/ai0']);
	});
});
