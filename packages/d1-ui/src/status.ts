// Status vocabularies: label and tone per value, so every page shows the same words and colours.
//
// A tone, not a hex colour: StatusBadge maps it to Directus theme variables, so light and dark
// themes both work. The values mirror the database CHECK constraints:
//   test_sessions.status            20260619000013_status_vocabulary.sql
//   machining_force_analysis.status work-queue state (pending -> processing -> done | error | skipped)
//   machining_force_analysis.diag_status  null | pending | processing | done | error
//   physical_samples.current_status active | consumed | destroyed | archived

export type Tone = 'neutral' | 'info' | 'progress' | 'success' | 'warning' | 'danger';

export interface StatusStyle {
	label: string;
	tone: Tone;
}

export type StatusKind = 'test' | 'force' | 'diag' | 'sample';

export const TEST_STATUS: Record<string, StatusStyle> = {
	registered: { label: 'Registered', tone: 'neutral' },
	pending_processing: { label: 'Pending processing', tone: 'info' },
	processing: { label: 'Processing', tone: 'progress' },
	processed: { label: 'Processed', tone: 'success' },
	analysing: { label: 'Analysing', tone: 'progress' },
	analysed: { label: 'Analysed', tone: 'success' },
	failed: { label: 'Failed', tone: 'danger' },
};

export const FORCE_STATUS: Record<string, StatusStyle> = {
	pending: { label: 'Queued', tone: 'info' },
	processing: { label: 'Processing', tone: 'progress' },
	done: { label: 'Analysed', tone: 'success' },
	error: { label: 'Error', tone: 'danger' },
	skipped: { label: 'Skipped', tone: 'neutral' },
};

export const DIAG_STATUS: Record<string, StatusStyle> = {
	pending: { label: 'Diagnostics queued', tone: 'info' },
	processing: { label: 'Diagnostics building', tone: 'progress' },
	done: { label: 'Diagnostics built', tone: 'success' },
	error: { label: 'Diagnostics error', tone: 'danger' },
};

export const SAMPLE_STATUS: Record<string, StatusStyle> = {
	active: { label: 'Active', tone: 'success' },
	consumed: { label: 'Consumed', tone: 'warning' },
	destroyed: { label: 'Destroyed', tone: 'danger' },
	archived: { label: 'Archived', tone: 'neutral' },
};

const VOCABULARIES: Record<StatusKind, Record<string, StatusStyle>> = {
	test: TEST_STATUS,
	force: FORCE_STATUS,
	diag: DIAG_STATUS,
	sample: SAMPLE_STATUS,
};

// "pending_processing" -> "Pending processing"
export function humanise(value: string): string {
	const text = value.replace(/_/g, ' ').trim();
	return text ? text.charAt(0).toUpperCase() + text.slice(1) : text;
}

// A value outside the vocabulary (a status added by a later migration) still shows, in neutral,
// rather than disappearing. A missing value is null: callers render nothing.
export function statusStyle(kind: StatusKind, value: string | null | undefined): StatusStyle | null {
	if (value === null || value === undefined || value === '') return null;
	return VOCABULARIES[kind][value] ?? { label: humanise(value), tone: 'neutral' };
}
