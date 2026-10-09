// Decides whether the in-app "update ready" prompt (UpdatePrompt.vue) is on screen. Kept apart from
// the component so the rules are testable: #197 was the update dialog appearing while the operator
// typed their password at login, so "never on /login" is a rule here, not an accident of layout.

import { ref } from 'vue';
import type { UpdateStatus } from './electronBridge';

/** The version the operator chose "Not now" for. Module state, not component state: it lasts until
 * the next launch even if the shell remounts (sign out and back in), as the old native dialog's
 * "Not now" did. Settings > About still offers the install. */
export const dismissedUpdateVersion = ref<string | null>(null);

export interface UpdatePromptInput {
	status: UpdateStatus;
	/** The version the operator chose "Not now" for, this launch. */
	dismissedVersion: string | null;
	/** A recording is running or being saved: not the moment to ask (install would refuse anyway). */
	recording: boolean;
	routePath: string;
}

export function shouldShowUpdatePrompt(i: UpdatePromptInput): boolean {
	// Never on the login page, however the shell got mounted.
	if (i.routePath === '/login' || i.routePath.startsWith('/login/')) return false;
	// Once "Restart and update" was clicked, show the progress whatever else is going on.
	if (i.status.state === 'installing') return true;
	if (i.status.state !== 'downloaded') return false;
	if (i.recording) return false;
	return i.dismissedVersion !== i.status.version;
}

/** The status the prompt keeps after a push. Once an update is downloaded, a later checking /
 * not-available / error push (Help > Check for updates while offline) must not hide it: the
 * installer is still on disk. Only a newer download or the install starting replaces it. */
export function nextPromptStatus(current: UpdateStatus, pushed: UpdateStatus): UpdateStatus {
	if (current.state === 'downloaded' && pushed.state !== 'downloaded' && pushed.state !== 'installing') return current;
	return pushed;
}
