// App-wide confirmation dialog — the replacement for window.confirm() on every gate that guards a
// crucial action (disabling a safety alarm, silencing a tripped one, discarding a capture, quitting
// mid-recording).
//
// Why not window.confirm(): under Electron it opens a NATIVE OS dialog, which
//   - blocks the renderer's event loop, so the live force stream and alarm tone stall while it is up;
//   - cannot be styled, so a destructive action looks identical to a benign one;
//   - is invisible to Playwright's CDP dialog interception, so every gate built on it had to be
//     bypassed in tests rather than covered (see commit d0b075c, which had to add a
//     FORCE_APP_TEST_HOOKS escape hatch to stop checkAlarmsBeforeStart() hanging the e2e suite for
//     the full 120s timeout).
// A plain DOM dialog fixes all three: it is non-blocking, themeable, and a real button Playwright
// can click — so these gates get tested instead of skipped.
import { reactive, readonly } from 'vue';

export type ConfirmTone = 'default' | 'warning' | 'danger';

export interface ConfirmStat {
	label: string;
	value: string;
}

export interface ConfirmOptions {
	title: string;
	/** The question. Keep it specific about consequence — "you will not be warned if…" beats "are you sure?". */
	message: string;
	/** Optional supporting detail rendered smaller under the message. */
	detail?: string;
	/** Readouts shown as a table — e.g. the measured values of the alarms being silenced, so the
	 *  operator confirms against real numbers rather than a generic prompt. */
	stats?: ConfirmStat[];
	confirmLabel?: string;
	cancelLabel?: string;
	tone?: ConfirmTone;
}

interface PendingRequest extends ConfirmOptions {
	resolve: (ok: boolean) => void;
}

const state = reactive({
	current: null as ConfirmOptions | null,
});

// Requests that arrived while another dialog was open. Stacking two dialogs would hide one behind
// the other and strand its promise unresolved (a caller awaiting it would hang forever), so they
// are shown strictly one at a time, in order.
const queue: PendingRequest[] = [];
let active: PendingRequest | null = null;

function showNext(): void {
	active = queue.shift() ?? null;
	state.current = active;
}

/**
 * Ask the operator to confirm an action. Resolves true only on explicit confirmation — Escape,
 * backdrop click, and Cancel all resolve false, so the safe outcome is the default on every path.
 */
export function confirmAction(opts: ConfirmOptions): Promise<boolean> {
	return new Promise<boolean>((resolve) => {
		queue.push({ ...opts, resolve });
		if (!active) showNext();
	});
}

/** Called by ConfirmDialog.vue only. */
export function resolveActive(ok: boolean): void {
	const req = active;
	active = null;
	state.current = null;
	req?.resolve(ok);
	// Let the closing dialog unmount before the next one mounts, so a queued prompt doesn't appear
	// to be the same dialog abruptly changing its text under the operator's cursor.
	if (queue.length) setTimeout(showNext, 0);
}

export const confirmState = readonly(state);
