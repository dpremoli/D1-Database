// Decides whether the in-app "update ready" prompt (UpdatePrompt.vue) is on screen. Kept apart from
// the component so the rules are testable: #197 was the update dialog appearing while the operator
// typed their password at login, so "never on /login" is a rule here, not an accident of layout.

import { ref } from 'vue';

/** The version the operator chose "Not now" for. Module state, not component state: it lasts until
 * the next launch even if the shell remounts (sign out and back in), as the old native dialog's
 * "Not now" did. Settings > About still offers the install. */
export const dismissedUpdateVersion = ref<string | null>(null);

export type UpdatePromptStatus =
	| { state: 'idle' }
	| { state: 'checking' }
	| { state: 'available'; version: string }
	| { state: 'not-available' }
	| { state: 'downloading'; percent: number }
	| { state: 'downloaded'; version: string; notes: string }
	| { state: 'installing'; version: string }
	| { state: 'error'; message: string };

export interface UpdatePromptInput {
	status: UpdatePromptStatus;
	/** The version the operator chose "Not now" for, this launch. */
	dismissedVersion: string | null;
	/** A recording is running or being saved: not the moment to ask (install would refuse anyway). */
	recording: boolean;
	routePath: string;
}

/** Pages where the prompt must never appear, however the shell got mounted. */
export function isPromptFreeRoute(path: string): boolean {
	return path === '/login' || path.startsWith('/login/');
}

export function shouldShowUpdatePrompt(i: UpdatePromptInput): boolean {
	if (isPromptFreeRoute(i.routePath)) return false;
	// Once "Restart and update" was clicked, show the progress whatever else is going on.
	if (i.status.state === 'installing') return true;
	if (i.status.state !== 'downloaded') return false;
	if (i.recording) return false;
	return i.dismissedVersion !== i.status.version;
}
