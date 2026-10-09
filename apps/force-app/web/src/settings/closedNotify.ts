// Settings > About: "Notify me about updates when the app is closed" (#197). The desktop shell
// keeps a Windows scheduled task for it; the toggle only exists where the shell says it can
// (the installed Windows app), so browser and dev builds show nothing.

type Bridge = Pick<NonNullable<Window['forceApp']>, 'getUpdateNotifyWhenClosed' | 'setUpdateNotifyWhenClosed'>;

export function closedNotifyBridge(w: { forceApp?: Partial<Bridge> } | undefined = typeof window === 'undefined' ? undefined : window): Bridge | undefined {
	const b = w?.forceApp;
	return b && typeof b.getUpdateNotifyWhenClosed === 'function' && typeof b.setUpdateNotifyWhenClosed === 'function' ? (b as Bridge) : undefined;
}

export interface ClosedNotifyState {
	/** False outside the installed Windows app: the toggle is not shown. */
	supported: boolean;
	/** The preference (default on). */
	enabled: boolean;
	/** Whether the Windows scheduled task really exists: Group Policy or an endpoint-security tool
	 * can block it, leaving the preference on with nothing running. */
	active: boolean;
}

/** The warning to show under the toggle when it is on but the task is not there; else ''. */
export function closedNotifyWarning(supported: boolean, enabled: boolean, active: boolean): string {
	return supported && enabled && !active ? "Couldn't set up the scheduled check (Windows refused)." : '';
}

export async function loadClosedNotify(bridge: Bridge): Promise<ClosedNotifyState> {
	try {
		const r = await bridge.getUpdateNotifyWhenClosed();
		return { supported: !!r.supported, enabled: !!r.enabled, active: r.active !== false };   // an older shell that does not report it: assume it exists
	} catch {
		return { supported: false, enabled: false, active: false };
	}
}

export interface ClosedNotifyOutcome {
	/** What the toggle should show now: the wanted value if it took, else the previous one. */
	enabled: boolean;
	/** In words for the operator; empty when it worked. */
	error: string;
}

/** Applies the toggle. Never throws; a refusal leaves the toggle where it was. */
export async function setClosedNotify(bridge: Bridge, wanted: boolean, previous: boolean): Promise<ClosedNotifyOutcome> {
	try {
		const r = await bridge.setUpdateNotifyWhenClosed(wanted);
		if (r.ok) return { enabled: r.enabled, error: '' };
		return { enabled: previous, error: r.reason || 'Could not change the setting.' };
	} catch (e: unknown) {
		return { enabled: previous, error: e instanceof Error ? e.message : 'Could not change the setting.' };
	}
}

/**
 * `setClosedNotify` for a checkbox the operator just clicked. After a refused enable the bound
 * value does not change (it was false before and still is), so Vue never re-patches `:checked` and
 * the box would stay ticked with nothing behind it: put the box back to the real state here.
 */
export async function toggleClosedNotifyBox(
	bridge: Bridge, box: { checked: boolean }, previous: boolean,
): Promise<ClosedNotifyOutcome> {
	const wanted = box.checked;
	const outcome = await setClosedNotify(bridge, wanted, previous);
	box.checked = outcome.enabled;
	return outcome;
}
