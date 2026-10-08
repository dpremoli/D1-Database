import { describe, expect, it } from 'vitest';
import { shouldShowUpdatePrompt, type UpdatePromptInput } from './updatePrompt';

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
