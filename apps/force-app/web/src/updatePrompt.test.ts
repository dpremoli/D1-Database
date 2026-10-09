import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';
import { nextPromptStatus, shouldShowUpdatePrompt, type UpdatePromptInput } from './updatePrompt';

const base: UpdatePromptInput = {
	status: { state: 'downloaded', version: '2.0.0', notes: '- Fixed flat forces' },
	dismissedVersion: null,
	recording: false,
	routePath: '/record',
};
const show = (over: Partial<UpdatePromptInput> = {}) => shouldShowUpdatePrompt({ ...base, ...over });

describe('shouldShowUpdatePrompt', () => {
	it('shows for a downloaded update inside the app', () => {
		expect(show()).toBe(true);
		expect(show({ routePath: '/settings' })).toBe(true);
	});

	it('never shows on the login page (#197)', () => {
		expect(show({ routePath: '/login' })).toBe(false);
		expect(show({ routePath: '/login/' })).toBe(false);
		expect(show({ status: { state: 'installing', version: '2.0.0' }, routePath: '/login' })).toBe(false);
	});

	it('does not show for any state other than downloaded or installing', () => {
		for (const status of [
			{ state: 'idle' }, { state: 'checking' }, { state: 'available', version: '2.0.0' }, { state: 'not-available' },
			{ state: 'downloading', percent: 40 }, { state: 'error', message: 'x' },
		] as const) expect(show({ status })).toBe(false);
	});

	it('"Not now" hides it for that version only', () => {
		expect(show({ dismissedVersion: '2.0.0' })).toBe(false);
		expect(show({ dismissedVersion: '1.9.0' })).toBe(true);
		expect(show({ dismissedVersion: '2.0.0', status: { state: 'downloaded', version: '2.0.1', notes: '' } })).toBe(true);
	});

	it('waits while a recording is running or being saved', () => {
		expect(show({ recording: true })).toBe(false);
	});

	it('keeps showing the installing state, even after "Not now" or during a recording', () => {
		const status = { state: 'installing', version: '2.0.0' } as const;
		expect(show({ status, dismissedVersion: '2.0.0', recording: true })).toBe(true);
	});
});

describe('nextPromptStatus', () => {
	const dl = { state: 'downloaded', version: '2.0.0', notes: '' } as const;
	it('keeps a downloaded update through a later checking, not-available or error push', () => {
		expect(nextPromptStatus(dl, { state: 'checking' })).toBe(dl);
		expect(nextPromptStatus(dl, { state: 'not-available' })).toBe(dl);
		expect(nextPromptStatus(dl, { state: 'error', message: 'offline' })).toBe(dl);
	});
	it('still moves on to installing, or to a newer download', () => {
		expect(nextPromptStatus(dl, { state: 'installing', version: '2.0.0' })).toEqual({ state: 'installing', version: '2.0.0' });
		const newer = { state: 'downloaded', version: '2.1.0', notes: 'x' } as const;
		expect(nextPromptStatus(dl, newer)).toBe(newer);
	});
	it('passes everything through when nothing is downloaded', () => {
		expect(nextPromptStatus({ state: 'idle' }, { state: 'checking' })).toEqual({ state: 'checking' });
	});
});

// The Record panel (Start/Stop) can be docked at either edge and the layout buttons sit bottom-right,
// so on /record the card must not use the bottom-right corner. Scoped CSS has no layout in jsdom, so
// this pins the source: the on-record variant frees `right` and is centred.
describe('UpdatePrompt on the Record page', () => {
	const src = readFileSync(fileURLToPath(new URL('./UpdatePrompt.vue', import.meta.url)), 'utf8');
	it('is switched to a bottom-centre position on /record', () => {
		expect(src).toMatch(/route\.path === '\/record'/);
		expect(src).toMatch(/\.upd\.on-record\s*\{[^}]*right:\s*auto;[^}]*left:\s*50%;[^}]*translateX\(-50%\)/);
	});
});
