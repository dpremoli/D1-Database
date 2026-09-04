// Keeping a popped-out Diagnostics panel current with the main workbench.
//
// DiagPanelWindow was built as a read-only viewer: it read the row once in onMounted, took
// diag_recipe as baked, and then never heard anything again — so editing the recipe, picking
// a channel or isolating a cluster in the main window left the detached view silently stale.
// The Record tab's LivePanelWindow has no equivalent problem because the live socket pushes
// to every window, so there was no pattern here to copy.
//
// BroadcastChannel is the right transport: same-origin, no server round trip, and it reaches
// every window of the app without either side holding a reference to the other (a
// window.opener handle would break the moment the analyst reloaded either window). Messages
// are keyed per analysis so two cuts open at once never cross-talk.
//
// The pop-out stays a VIEWER. It applies what it receives; its own controls do not publish
// back. One writer keeps "who wins" trivial and stops an edit loop between windows.

export type DiagSyncMsg =
	| { t: 'recipe'; recipe: unknown }
	| { t: 'channel'; panelId: string; channel: string }
	| { t: 'isolate'; clusterId: number | null }
	| { t: 'layers'; layers: unknown[] }
	| { t: 'viewport'; bbox: [number, number, number, number] }
	/** A pop-out announcing itself, so the main window can answer with current state. */
	| { t: 'hello' };

export interface DiagSyncChannel {
	post(msg: DiagSyncMsg): void;
	close(): void;
}

/** Channel name for one analysis. Per-cut so two open cuts never cross-talk. */
export function diagSyncName(analysisId: string): string {
	return `d1.diag.${analysisId}`;
}

/**
 * Open a sync channel for `analysisId`, invoking `onMessage` for every message published by
 * another window.
 *
 * Returns a no-op channel where BroadcastChannel is unavailable (older WebViews, and the
 * jsdom-less test environment), so callers never need to feature-detect: the pop-out simply
 * degrades to the read-once behaviour it had before.
 */
export function openDiagSync(
	analysisId: string,
	onMessage: (msg: DiagSyncMsg) => void,
): DiagSyncChannel {
	if (typeof BroadcastChannel === 'undefined') {
		return { post: () => {}, close: () => {} };
	}
	const bc = new BroadcastChannel(diagSyncName(analysisId));
	bc.onmessage = (ev: MessageEvent) => {
		const msg = ev.data as DiagSyncMsg;
		// Messages arrive from another window of this same app, but a malformed or
		// future-version payload must not take the handler down mid-render.
		if (!msg || typeof msg !== 'object' || typeof (msg as { t?: unknown }).t !== 'string') return;
		try {
			onMessage(msg);
		} catch {
			/* a stale pop-out must not break the publisher */
		}
	};
	return {
		post: (msg) => { try { bc.postMessage(msg); } catch { /* closed */ } },
		close: () => { try { bc.close(); } catch { /* already closed */ } },
	};
}

/**
 * Coalesce rapid publishes onto one message per `waitMs`.
 *
 * The recipe publishes on every keystroke; without this a pop-out would re-render (and, once
 * it recomputes, re-request) far faster than it can draw. Trailing-edge only, and the LAST
 * value wins — an intermediate recipe state is never worth delivering.
 */
export function debouncePublish<T>(
	publish: (value: T) => void,
	waitMs = 150,
): { push: (value: T) => void; flush: () => void; cancel: () => void } {
	let timer: ReturnType<typeof setTimeout> | null = null;
	let pending: { value: T } | null = null;

	const fire = () => {
		timer = null;
		if (!pending) return;
		const { value } = pending;
		pending = null;
		publish(value);
	};

	return {
		push(value: T) {
			pending = { value };
			if (timer) clearTimeout(timer);
			timer = setTimeout(fire, waitMs);
		},
		// `hello` needs the current state immediately, not on the next trailing edge.
		flush() {
			if (timer) clearTimeout(timer);
			fire();
		},
		cancel() {
			if (timer) clearTimeout(timer);
			timer = null;
			pending = null;
		},
	};
}
