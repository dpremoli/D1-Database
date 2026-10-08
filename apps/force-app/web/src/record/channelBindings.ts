// Saved NI-DAQ channel bindings against what the NI-DAQ scan actually has (#195). Pure, so the
// rules are unit-tested; the Record page's pre-flight (preflight.ts) uses it and offers a one-click
// "Re-assign channels" that runs the backend's own auto-assign. The layout rules stay in the
// backend (channels.autoassign); nothing here decides which port gets which channel.

import { SUB_NAMES } from './liveClient';

/** A saved channel as these rules need it (a subset of nidaqApi.Channel). */
export interface BoundChannel { name: string; role?: string; physical: string | null; source?: string }

/** A saved binding whose port the scan does not have. */
export interface MissingBinding { name: string; role: string; physical: string }

/** Inputs in `physical` that the scan does not have (#213). Nothing is missing when there is no
 *  real device list to compare with: an absent chassis is the NI-DAQ source button's business, and
 *  a simulated tree has no real inputs to miss. */
export function missingFromChassis(physical: readonly string[], scan: readonly string[] | null | undefined): string[] {
	if (!scan || !scan.length) return [];
	// DAQmx takes "force1_mod1/ai0" for "Force1_Mod1/ai0": names differ only if they differ in more than case.
	const have = new Set(scan.map((p) => p.toLowerCase()));
	return [...new Set(physical)].filter((p) => !have.has(p.toLowerCase()));
}

/** The hardware channels of a saved model that name a port the scan does not have, in model order,
 *  each with the role it plays. Virtual channels have no port. Empty when there is no scan. */
export function missingBindings(bindings: readonly BoundChannel[], scan: readonly string[] | null | undefined): MissingBinding[] {
	if (!scan || !scan.length) return [];
	const have = new Set(scan.map((p) => p.toLowerCase()));
	return bindings
		.filter((c) => c.physical && c.source !== 'virtual' && !have.has(String(c.physical).trim().toLowerCase()))
		.map((c) => ({ name: c.name, role: c.role || c.name, physical: String(c.physical).trim() }));
}

/** No force channel (Fx1..Fz4) has a port, although the scan has ports to give. Without a scan
 *  there is nothing to assign from. */
export function noForceBound(bindings: readonly BoundChannel[], scan: readonly string[] | null | undefined): boolean {
	if (!scan || !scan.length) return false;
	return SUB_NAMES.every((n) => !bindings.find((c) => c.name === n)?.physical);
}

/** The missing ports with the channels that use them, one entry per port. */
export function groupMissing(missing: readonly MissingBinding[]): { physical: string; names: string[] }[] {
	const byPort = new Map<string, string[]>();
	for (const m of missing) byPort.set(m.physical, [...(byPort.get(m.physical) ?? []), m.name]);
	return [...byPort].map(([physical, names]) => ({ physical, names }));
}

/** The missing ports with the channels that use them: "Missing_Mod9/ai0 (Tacho)". */
export function describeMissing(missing: readonly MissingBinding[]): string[] {
	return groupMissing(missing).map((g) => `${g.physical} (${g.names.join(', ')})`);
}

/** What the "Re-assign channels" confirm says: what is wrong now, and that the whole saved list is
 *  replaced by the automatic layout (the backend rebuilds every channel, so sensitivities, gains
 *  and virtual channels set on the NI-DAQ page go too). */
export function reassignConfirmText(bindings: readonly BoundChannel[], scan: readonly string[] | null | undefined): string {
	const missing = missingBindings(bindings, scan);
	const now = missing.length
		? `The saved channels name ${missing.length} port${missing.length === 1 ? '' : 's'} the NI-DAQ does not have: ${describeMissing(missing).join('; ')}.`
		: 'No force channel has an input assigned.';
	const n = scan?.length ?? 0;
	return `${now} Re-assign replaces the whole saved channel list (names, sensitivities, gains and virtual channels) with the automatic layout on the ${n} input${n === 1 ? '' : 's'} the NI-DAQ reports.`;
}

/** Why the pre-flight should offer Re-assign, or null when the bindings and the scan agree. */
export type ReassignReason = 'missing' | 'unbound';
export function reassignReason(bindings: readonly BoundChannel[], scan: readonly string[] | null | undefined): ReassignReason | null {
	if (missingBindings(bindings, scan).length) return 'missing';
	if (noForceBound(bindings, scan)) return 'unbound';
	return null;
}
